"""Regression tests for `_graph_lock` coverage across MCP tools.

`_graph_lock` (a `threading.RLock`) protects the module-level `_graph` cache
and `_storage` backend from races between concurrent MCP tool calls (e.g. a
query running while a sync or the dashboard thread reloads the graph).
Mutating tools historically wrapped their whole body in `with _graph_lock:`,
but most read-only tools never acquired it at all.

This file verifies two things:

1. (dynamic) For every tool that touches `_ensure_graph` / `_storage.load` /
   `_storage.exists`, the lock is actually held at the moment that access
   happens.
2. (static) The set of registered tools that do *not* acquire the lock
   anywhere in their body is exactly the documented allow-list of tools that
   only touch the coordination store (`_coordinator`), never `_graph` or
   `_storage` -- so a future tool can't silently skip the lock.
"""

from __future__ import annotations

import inspect
import json
import threading
from unittest.mock import patch

import pytest

import codegiraffe.dashboard_server as dashboard_server_module
import codegiraffe.server as server


# ---------------------------------------------------------------------------
# Allow-list: tools that only touch the coordination store (`_coordinator`),
# never `_graph` or `_storage`, and therefore do not need `_graph_lock`.
# ---------------------------------------------------------------------------

UNLOCKED_TOOLS = frozenset(
    {
        "codegiraffe_claim",
        "codegiraffe_release",
        "codegiraffe_update_agent_status",
        "codegiraffe_agents",
    }
)

# Tools whose bodies definitely call `_ensure_graph` or `_storage.load` /
# `_storage.exists` directly, so the dynamic test should observe at least one
# recorded access for each of them (a floor, to make sure the instrumentation
# below is actually exercising real code paths and not silently vacuous).
EXPECT_SHARED_STATE_ACCESS = frozenset(
    {
        "codegiraffe_query",
        "codegiraffe_context_for",
        "codegiraffe_detect_drift",
        "codegiraffe_hotspots",
        "codegiraffe_blast_radius",
        "codegiraffe_risk_assessment",
        "codegiraffe_cycles",
        "codegiraffe_contracts",
        "codegiraffe_validate_contracts",
        "codegiraffe_validate_changes",
        "codegiraffe_suggest_tests",
        "codegiraffe_file_coupling",
        "codegiraffe_order_tasks",
        "codegiraffe_export",
        "codegiraffe_status",
        "codegiraffe_patterns",
        "codegiraffe_migration_plan",
        "codegiraffe_dashboard",
    }
)


class _TrackingRLock:
    """A real RLock that also exposes whether it is currently held.

    Swapped in for `codegiraffe.server._graph_lock` so spy functions can
    observe, from inside `_ensure_graph` / `_storage.load` / `_storage.exists`,
    whether the lock was held at the moment they ran. Implements the same
    `acquire` / `release` / context-manager protocol as `threading.RLock`, so
    it is a drop-in replacement wherever the module does `with _graph_lock:`.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._depth = 0

    @property
    def held(self) -> bool:
        return self._depth > 0

    def acquire(self, *args, **kwargs):
        acquired = self._lock.acquire(*args, **kwargs)
        if acquired:
            self._depth += 1
        return acquired

    def release(self):
        self._depth -= 1
        self._lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False


@pytest.fixture()
def reset_dashboard_singleton():
    """Reset the dashboard_server module singleton around the test.

    `codegiraffe_init` and `codegiraffe_dashboard` both lazily start a
    background dashboard HTTP server; without resetting this singleton
    between tests, a server started here could leak into (or conflict
    with) other test modules. Mirrors the fixture of the same name in
    tests/test_dashboard_tool.py.
    """
    original = dashboard_server_module._server
    dashboard_server_module._server = None
    yield
    if dashboard_server_module._server is not None and dashboard_server_module._server.is_running:
        dashboard_server_module._server.stop()
    dashboard_server_module._server = original


@pytest.fixture()
def initialized_project(tmp_path, reset_dashboard_singleton):
    """Scan a tiny Flask project and return its path as a string."""
    (tmp_path / "app.py").write_text(
        "from flask import Flask\n"
        "app = Flask(__name__)\n\n"
        "@app.route('/api/users')\n"
        "def get_users():\n"
        "    return []\n"
    )
    result = server.codegiraffe_init(str(tmp_path))
    assert "Initialized" in result or "nodes" in result.lower(), result
    return str(tmp_path)


def _instrument(monkeypatch):
    """Swap in a tracking lock and spy on the shared-state chokepoints.

    Returns (tracking_lock, calls) where `calls` is a list that spy
    functions append (chokepoint_name, held) to every time `_ensure_graph`,
    `_storage.load`, or `_storage.exists` runs. Callers should clear
    `calls` between tool invocations to attribute recordings per tool.
    """
    tracking_lock = _TrackingRLock()
    monkeypatch.setattr(server, "_graph_lock", tracking_lock)

    calls: list[tuple[str, bool]] = []

    orig_ensure_graph = server._ensure_graph

    def spy_ensure_graph(project_path):
        calls.append(("_ensure_graph", tracking_lock.held))
        return orig_ensure_graph(project_path)

    monkeypatch.setattr(server, "_ensure_graph", spy_ensure_graph)

    orig_load = server._storage.load
    orig_exists = server._storage.exists

    def spy_load(project_path):
        calls.append(("_storage.load", tracking_lock.held))
        return orig_load(project_path)

    def spy_exists(project_path):
        calls.append(("_storage.exists", tracking_lock.held))
        return orig_exists(project_path)

    monkeypatch.setattr(server._storage, "load", spy_load)
    monkeypatch.setattr(server._storage, "exists", spy_exists)

    return tracking_lock, calls


def _candidate_calls(project_path: str) -> dict[str, dict]:
    """Every graph/storage-reading tool (plus a couple of harmless neighbors
    from the same audit) paired with minimal valid kwargs."""
    return {
        "codegiraffe_query": {"project_path": project_path},
        "codegiraffe_context_for": {"project_path": project_path, "task": "find auth issues"},
        "codegiraffe_detect_drift": {"project_path": project_path},
        "codegiraffe_hotspots": {"project_path": project_path},
        "codegiraffe_blast_radius": {"project_path": project_path},
        "codegiraffe_risk_assessment": {"project_path": project_path},
        "codegiraffe_cycles": {"project_path": project_path},
        "codegiraffe_contracts": {"project_path": project_path},
        "codegiraffe_validate_contracts": {"project_path": project_path},
        "codegiraffe_validate_changes": {"project_path": project_path, "auto": False, "diff": ""},
        "codegiraffe_suggest_tests": {"project_path": project_path, "auto": False, "diff": ""},
        "codegiraffe_file_coupling": {"project_path": project_path},
        "codegiraffe_order_tasks": {
            "project_path": project_path,
            "tasks": json.dumps([{"name": "Refactor auth module", "target_files": ["app.py"]}]),
        },
        "codegiraffe_export": {"project_path": project_path},
        "codegiraffe_status": {"project_path": project_path},
        "codegiraffe_history": {"project_path": project_path},
        "codegiraffe_diff": {"project_path": project_path, "version_a": 1},
        "codegiraffe_snapshot": {"project_path": project_path, "message": "test snapshot"},
        "codegiraffe_federate": {"project_paths": [project_path]},
        "codegiraffe_cross_query": {"node_id": "repo:x::service:Missing"},
        "codegiraffe_cross_edges": {},
        "codegiraffe_cypher": {"project_path": project_path, "query": "MATCH (n) RETURN n LIMIT 1"},
        "codegiraffe_patterns": {"project_path": project_path, "node_type": "endpoint"},
        "codegiraffe_pr_diff": {"project_path": project_path, "base_ref": "HEAD"},
        "codegiraffe_migration_plan": {"project_path": project_path, "description": "test migration"},
        "codegiraffe_dashboard": {"project_path": project_path},
    }


def test_graph_lock_held_during_shared_state_access(initialized_project, monkeypatch):
    """Every read tool that touches `_ensure_graph`/`_storage` must do so
    while `_graph_lock` is held."""
    tracking_lock, calls = _instrument(monkeypatch)

    calls_by_tool: dict[str, list[tuple[str, bool]]] = {}
    for name, kwargs in _candidate_calls(initialized_project).items():
        fn = getattr(server, name)
        calls.clear()
        if name == "codegiraffe_dashboard":
            with patch("webbrowser.open"):
                fn(**kwargs)
        else:
            fn(**kwargs)
        calls_by_tool[name] = list(calls)

    # No chokepoint ever ran with the lock unheld.
    for name, recorded in calls_by_tool.items():
        assert all(held for (_choke, held) in recorded), (
            f"{name} accessed _ensure_graph/_storage without holding "
            f"_graph_lock: {recorded}"
        )

    # Sanity floor: the tools known to touch shared state directly must have
    # actually produced at least one recorded access, otherwise this test
    # would be vacuously passing.
    for name in EXPECT_SHARED_STATE_ACCESS:
        assert calls_by_tool[name], (
            f"{name} did not invoke _ensure_graph/_storage.load/_storage.exists "
            "-- instrumentation may be broken, or the tool no longer touches "
            "shared state and should be removed from EXPECT_SHARED_STATE_ACCESS"
        )


def test_unlocked_tools_match_documented_allow_list():
    """Every registered tool must hold `_graph_lock` somewhere in its body
    (either via the `_with_graph_lock` decorator or a manual `with
    _graph_lock:` block), except the documented coordination-only allow-list.

    `inspect.getsource` follows `__wrapped__` (set by `functools.wraps` in
    `_with_graph_lock`), so this picks up the original source -- including
    the `@_with_graph_lock` decorator line or an inline `with _graph_lock:`
    -- for every tool, decorated or not.
    """
    tools = {t.name: t for t in server.mcp._tool_manager.list_tools()}
    assert tools, "no tools registered -- FastMCP tool discovery may be broken"

    unlocked = {
        name for name, tool in tools.items() if "_graph_lock" not in inspect.getsource(tool.fn)
    }

    assert unlocked == UNLOCKED_TOOLS

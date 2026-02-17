"""Tests for order_tasks() (T062-T063) — dependency-aware task ordering.

TDD Step 1: These tests are written BEFORE the implementation and should
initially fail. They cover:
  T062 - Task ordering logic via graph dependencies
  T063 - Parallel groups, dependency edges, contract/API surface tests
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

import codegiraffe.server as server_module
from codegiraffe.graph import ArchGraph, Edge, Node
from codegiraffe.query import order_tasks
from codegiraffe.schema import EdgeType, NodeType
from codegiraffe.storage import JSONStorage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_graph_with_import() -> ArchGraph:
    """auth.py imports db.py — auth depends on db."""
    g = ArchGraph()
    g.add_node(Node(id="module:src/auth.py", type=NodeType.MODULE, label="auth", file_path="src/auth.py"))
    g.add_node(Node(id="module:src/db.py", type=NodeType.MODULE, label="db", file_path="src/db.py"))
    g.add_edge(Edge(source="module:src/auth.py", target="module:src/db.py", type=EdgeType.IMPORTS))
    return g


def _make_disjoint_graph() -> ArchGraph:
    """Two modules with no edges between them."""
    g = ArchGraph()
    g.add_node(Node(id="module:src/foo.py", type=NodeType.MODULE, label="foo", file_path="src/foo.py"))
    g.add_node(Node(id="module:src/bar.py", type=NodeType.MODULE, label="bar", file_path="src/bar.py"))
    return g


def _make_cycle_graph() -> ArchGraph:
    """A imports B, B imports A — circular dependency."""
    g = ArchGraph()
    g.add_node(Node(id="module:src/a.py", type=NodeType.MODULE, label="a", file_path="src/a.py"))
    g.add_node(Node(id="module:src/b.py", type=NodeType.MODULE, label="b", file_path="src/b.py"))
    g.add_edge(Edge(source="module:src/a.py", target="module:src/b.py", type=EdgeType.IMPORTS))
    g.add_edge(Edge(source="module:src/b.py", target="module:src/a.py", type=EdgeType.IMPORTS))
    return g


# ---------------------------------------------------------------------------
# T062: Task ordering tests
# ---------------------------------------------------------------------------


class TestOrderTasks:
    """T062 — Core ordering logic."""

    def test_db_before_auth_because_auth_imports_db(self):
        """Task modifying imported file (db) appears before task modifying importer (auth)."""
        graph = _make_graph_with_import()
        tasks = [
            {"name": "Update auth logic", "target_files": ["src/auth.py"]},
            {"name": "Update DB schema", "target_files": ["src/db.py"]},
        ]
        result = order_tasks(graph, tasks)

        ordered = result["ordered_tasks"]
        assert len(ordered) == 2

        # Find order positions
        db_order = next(t["order"] for t in ordered if t["name"] == "Update DB schema")
        auth_order = next(t["order"] for t in ordered if t["name"] == "Update auth logic")

        # DB must come first (lower order number)
        assert db_order < auth_order, (
            f"Expected DB task (order={db_order}) before auth task (order={auth_order})"
        )

    def test_independent_tasks_are_parallelizable(self):
        """Tasks C and D with no graph overlap should be in the same parallel group."""
        graph = _make_disjoint_graph()
        tasks = [
            {"name": "Task C", "target_files": ["src/foo.py"]},
            {"name": "Task D", "target_files": ["src/bar.py"]},
        ]
        result = order_tasks(graph, tasks)

        parallel_groups = result["parallel_groups"]
        # Both tasks should appear in a single parallel group together
        flat_indices = [idx for group in parallel_groups for idx in group]
        assert 0 in flat_indices
        assert 1 in flat_indices
        assert len(parallel_groups) >= 1

        # Both should be in the same group
        found_same_group = any(0 in g and 1 in g for g in parallel_groups)
        assert found_same_group, f"Tasks 0 and 1 should be in same group, got: {parallel_groups}"

    def test_conflict_zone_detected_for_shared_file(self):
        """Tasks touching the same file are flagged as conflict zones."""
        graph = _make_graph_with_import()
        tasks = [
            {"name": "Refactor auth A", "target_files": ["src/auth.py"]},
            {"name": "Refactor auth B", "target_files": ["src/auth.py"]},
        ]
        result = order_tasks(graph, tasks)

        conflict_zones = result["conflict_zones"]
        assert len(conflict_zones) >= 1

        # The shared file should be in a conflict zone
        conflict_files = [cz["file"] for cz in conflict_zones]
        assert "src/auth.py" in conflict_files

    def test_conflict_zone_lists_task_names(self):
        """Conflict zone entry includes names of all conflicting tasks."""
        graph = _make_graph_with_import()
        tasks = [
            {"name": "Refactor auth A", "target_files": ["src/auth.py"]},
            {"name": "Refactor auth B", "target_files": ["src/auth.py"]},
        ]
        result = order_tasks(graph, tasks)

        conflict_zones = result["conflict_zones"]
        auth_conflict = next(cz for cz in conflict_zones if cz["file"] == "src/auth.py")
        assert "Refactor auth A" in auth_conflict["tasks"]
        assert "Refactor auth B" in auth_conflict["tasks"]

    def test_circular_dependency_detected_and_reported(self):
        """Cyclic task dependency is detected and reported rather than crashing."""
        graph = _make_cycle_graph()
        tasks = [
            {"name": "Update A", "target_files": ["src/a.py"]},
            {"name": "Update B", "target_files": ["src/b.py"]},
        ]
        result = order_tasks(graph, tasks)

        # Must return a result dict with the expected keys even on cycle
        assert "ordered_tasks" in result
        assert "parallel_groups" in result
        assert "conflict_zones" in result
        assert "dependency_edges" in result

        # Should report the cycle — either in a "cycle" key or via a warning
        # The function should not raise; it should surface cycle info
        has_cycle_info = (
            "cycle" in result
            or any(
                "cycle" in str(t.get("note", "")).lower()
                for t in result["ordered_tasks"]
            )
        )
        assert has_cycle_info, f"No cycle information found in result: {result}"

    def test_empty_tasks_list_returns_empty_plan(self):
        """No tasks means empty ordered plan."""
        graph = _make_graph_with_import()
        result = order_tasks(graph, [])

        assert result["ordered_tasks"] == []
        assert result["parallel_groups"] == []
        assert result["conflict_zones"] == []
        assert result["dependency_edges"] == []

    def test_result_contains_required_keys(self):
        """Result dict always contains the four required keys."""
        graph = _make_graph_with_import()
        tasks = [{"name": "Do something", "target_files": ["src/auth.py"]}]
        result = order_tasks(graph, tasks)

        assert "ordered_tasks" in result
        assert "parallel_groups" in result
        assert "conflict_zones" in result
        assert "dependency_edges" in result

    def test_task_preserves_name_and_files(self):
        """Each entry in ordered_tasks preserves name and target_files."""
        graph = _make_graph_with_import()
        tasks = [{"name": "Do X", "target_files": ["src/auth.py"]}]
        result = order_tasks(graph, tasks)

        assert len(result["ordered_tasks"]) == 1
        entry = result["ordered_tasks"][0]
        assert entry["name"] == "Do X"
        assert entry["target_files"] == ["src/auth.py"]
        assert "order" in entry


# ---------------------------------------------------------------------------
# T063: Parallel groups and dependency edge tests
# ---------------------------------------------------------------------------


class TestParallelGroupsAndDependencyEdges:
    """T063 — Parallel groups, dependency_edges, single task, and contract tests."""

    def test_parallel_groups_at_same_topological_level(self):
        """Tasks at the same topological level appear in the same parallel group."""
        graph = _make_disjoint_graph()
        tasks = [
            {"name": "Task C", "target_files": ["src/foo.py"]},
            {"name": "Task D", "target_files": ["src/bar.py"]},
        ]
        result = order_tasks(graph, tasks)

        # With no ordering constraints, both tasks are at level 0
        assert len(result["parallel_groups"]) == 1
        assert set(result["parallel_groups"][0]) == {0, 1}

    def test_dependency_edges_includes_from_to_reason(self):
        """dependency_edges contains dicts with 'from', 'to', and 'reason' keys."""
        graph = _make_graph_with_import()
        tasks = [
            {"name": "Update DB schema", "target_files": ["src/db.py"]},
            {"name": "Update auth logic", "target_files": ["src/auth.py"]},
        ]
        result = order_tasks(graph, tasks)

        dep_edges = result["dependency_edges"]
        assert len(dep_edges) >= 1

        edge = dep_edges[0]
        assert "from" in edge
        assert "to" in edge
        assert "reason" in edge

    def test_dependency_edge_direction_db_to_auth(self):
        """Dependency edge runs from DB task to auth task (DB must precede auth)."""
        graph = _make_graph_with_import()
        tasks = [
            {"name": "Update DB schema", "target_files": ["src/db.py"]},
            {"name": "Update auth logic", "target_files": ["src/auth.py"]},
        ]
        result = order_tasks(graph, tasks)

        dep_edges = result["dependency_edges"]
        # There should be an edge indicating DB precedes auth
        found = any(
            e["from"] == "Update DB schema" and e["to"] == "Update auth logic"
            for e in dep_edges
        )
        assert found, f"Expected DB->auth dependency edge, got: {dep_edges}"

    def test_dependency_edge_reason_contains_imports(self):
        """dependency_edge reason mentions 'imports' as the relationship."""
        graph = _make_graph_with_import()
        tasks = [
            {"name": "Update DB schema", "target_files": ["src/db.py"]},
            {"name": "Update auth logic", "target_files": ["src/auth.py"]},
        ]
        result = order_tasks(graph, tasks)

        dep_edges = result["dependency_edges"]
        assert any("imports" in e["reason"].lower() for e in dep_edges)

    def test_single_task_returns_trivial_plan(self):
        """Single task produces trivial plan: one group with one item, no edges."""
        graph = _make_graph_with_import()
        tasks = [{"name": "Only task", "target_files": ["src/auth.py"]}]
        result = order_tasks(graph, tasks)

        assert len(result["ordered_tasks"]) == 1
        assert len(result["parallel_groups"]) == 1
        assert result["parallel_groups"] == [[0]]
        assert result["dependency_edges"] == []

    def test_two_sequential_tasks_form_two_groups(self):
        """auth depends on db, so they form two separate sequential groups."""
        graph = _make_graph_with_import()
        tasks = [
            {"name": "Update DB schema", "target_files": ["src/db.py"]},
            {"name": "Update auth logic", "target_files": ["src/auth.py"]},
        ]
        result = order_tasks(graph, tasks)

        parallel_groups = result["parallel_groups"]
        assert len(parallel_groups) == 2, (
            f"Expected 2 sequential groups, got {len(parallel_groups)}: {parallel_groups}"
        )
        # Each group should have exactly 1 task
        assert all(len(g) == 1 for g in parallel_groups)

    def test_tasks_with_no_matching_nodes_have_no_dependencies(self):
        """Tasks targeting files not in the graph produce no dependency edges."""
        graph = _make_graph_with_import()
        tasks = [
            {"name": "Unknown A", "target_files": ["src/unknown_x.py"]},
            {"name": "Unknown B", "target_files": ["src/unknown_y.py"]},
        ]
        result = order_tasks(graph, tasks)

        # No graph-derived dependencies possible for unknown files
        assert result["dependency_edges"] == []
        # Both tasks should still appear
        assert len(result["ordered_tasks"]) == 2


# ---------------------------------------------------------------------------
# T063: Contract/API surface test for codegiraffe_order_tasks MCP tool
# ---------------------------------------------------------------------------


class TestOrderTasksTool:
    """Contract tests for the codegiraffe_order_tasks MCP tool."""

    @pytest.fixture(autouse=True)
    def reset_server_state(self):
        """Reset server module globals before each test."""
        server_module._graph = None
        server_module._storage = JSONStorage()
        yield
        server_module._graph = None
        server_module._storage = JSONStorage()

    def _build_and_cache_graph(self, project_path: str) -> None:
        """Build a small graph and persist it so _ensure_graph works."""
        g = ArchGraph()
        g.add_node(Node(id="module:src/auth.py", type=NodeType.MODULE, label="auth", file_path="src/auth.py"))
        g.add_node(Node(id="module:src/db.py", type=NodeType.MODULE, label="db", file_path="src/db.py"))
        g.add_edge(Edge(source="module:src/auth.py", target="module:src/db.py", type=EdgeType.IMPORTS))
        data = g.to_data()
        data.project_path = project_path
        server_module._storage.save(project_path, data)
        server_module._graph = None

    def test_tool_accepts_project_path_and_tasks_json(self):
        """codegiraffe_order_tasks accepts project_path and tasks (JSON string)."""
        from codegiraffe.server import codegiraffe_order_tasks

        project_path = "/tmp/test_order_tasks_contract"
        self._build_and_cache_graph(project_path)

        tasks_json = json.dumps([
            {"name": "Update DB schema", "target_files": ["src/db.py"]},
            {"name": "Update auth logic", "target_files": ["src/auth.py"]},
        ])

        result = codegiraffe_order_tasks(project_path=project_path, tasks=tasks_json)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_tool_returns_ordered_tasks_section(self):
        """Tool output contains an 'Ordered Tasks' section."""
        from codegiraffe.server import codegiraffe_order_tasks

        project_path = "/tmp/test_order_tasks_section"
        self._build_and_cache_graph(project_path)

        tasks_json = json.dumps([
            {"name": "Update DB schema", "target_files": ["src/db.py"]},
            {"name": "Update auth logic", "target_files": ["src/auth.py"]},
        ])

        result = codegiraffe_order_tasks(project_path=project_path, tasks=tasks_json)
        assert "Update DB schema" in result
        assert "Update auth logic" in result

    def test_tool_returns_parallel_groups_section(self):
        """Tool output mentions parallel groups."""
        from codegiraffe.server import codegiraffe_order_tasks

        project_path = "/tmp/test_order_tasks_parallel"
        self._build_and_cache_graph(project_path)

        tasks_json = json.dumps([
            {"name": "Update DB schema", "target_files": ["src/db.py"]},
            {"name": "Update auth logic", "target_files": ["src/auth.py"]},
        ])

        result = codegiraffe_order_tasks(project_path=project_path, tasks=tasks_json)
        assert "parallel" in result.lower() or "group" in result.lower()

    def test_tool_handles_invalid_json_gracefully(self):
        """Tool returns an error string for invalid JSON tasks input."""
        from codegiraffe.server import codegiraffe_order_tasks

        project_path = "/tmp/test_order_tasks_badjson"
        self._build_and_cache_graph(project_path)

        result = codegiraffe_order_tasks(project_path=project_path, tasks="not valid json")
        assert "error" in result.lower()

    def test_tool_handles_missing_graph(self):
        """Tool returns an error string when no graph has been initialized."""
        from codegiraffe.server import codegiraffe_order_tasks

        tasks_json = json.dumps([{"name": "Some task", "target_files": ["src/x.py"]}])
        result = codegiraffe_order_tasks(
            project_path="/tmp/nonexistent_project_xyz",
            tasks=tasks_json,
        )
        assert "error" in result.lower()

    def test_tool_empty_tasks_returns_gracefully(self):
        """Tool handles empty task list without error."""
        from codegiraffe.server import codegiraffe_order_tasks

        project_path = "/tmp/test_order_tasks_empty"
        self._build_and_cache_graph(project_path)

        result = codegiraffe_order_tasks(project_path=project_path, tasks="[]")
        assert isinstance(result, str)
        # Should mention no tasks or return a harmless message
        assert "error" not in result.lower() or "no tasks" in result.lower()

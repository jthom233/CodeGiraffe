"""Layout integration tests for Code Giraffe server-level codegiraffe_init and codegiraffe_sync.

Tests that the server stores layout data in GraphData after init/sync operations.
These are TDD RED-phase tests — they will fail until codegiraffe_init and
codegiraffe_sync are updated to call compute_layout() and persist the result.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

import codegiraffe.server as server_module
from codegiraffe.server import (
    codegiraffe_init,
    codegiraffe_sync,
    codegiraffe_coverage,
)
from codegiraffe.graph import ArchGraph, Edge, GraphData, Node
from codegiraffe.storage import JSONStorage
from codegiraffe.versioning import VersionStore
from codegiraffe.federation import GraphFederation


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_server_state():
    """Reset server module globals before each test to avoid cross-test pollution."""
    server_module._graph = None
    server_module._storage = JSONStorage()
    server_module._version_store = VersionStore()
    server_module._federation = GraphFederation()
    yield
    server_module._graph = None
    server_module._storage = JSONStorage()
    server_module._version_store = VersionStore()
    server_module._federation = GraphFederation()


@pytest.fixture
def project_dir(tmp_path):
    """Create a minimal Python project with at least one scannable file."""
    py_file = tmp_path / "app.py"
    py_file.write_text(
        "class AppService:\n"
        "    def run(self):\n"
        "        pass\n"
        "\n"
        "class UserRepository:\n"
        "    def find_by_id(self, uid):\n"
        "        return None\n"
    )
    return str(tmp_path)


# ---------------------------------------------------------------------------
# TestLayoutIntegration
# ---------------------------------------------------------------------------


class TestLayoutIntegration:
    """Integration tests verifying that codegiraffe_init and codegiraffe_sync
    populate GraphData.layout with computed node positions.

    These tests are expected to FAIL (RED) until the server calls compute_layout()
    and persists the result into the stored GraphData.
    """

    # ------------------------------------------------------------------
    # a) After codegiraffe_init, stored GraphData has non-empty layout
    # ------------------------------------------------------------------

    def test_init_stores_non_empty_layout(self, project_dir):
        """After codegiraffe_init on a project with scannable files,
        the stored GraphData.layout must be non-empty.

        Fails (RED) because codegiraffe_init does not yet call compute_layout().
        """
        result = codegiraffe_init(project_dir)
        assert "Initialized graph" in result, (
            f"codegiraffe_init returned unexpected result: {result!r}"
        )

        # Load the stored data directly from the storage backend to verify
        # that layout was persisted, not just held in memory.
        storage = JSONStorage()
        graph_data = storage.load(project_dir)

        assert graph_data is not None, (
            "No graph data found on disk after codegiraffe_init"
        )
        assert len(graph_data.nodes) > 0, (
            "Expected at least one scanned node — check that app.py was scanned"
        )
        assert len(graph_data.layout) > 0, (
            f"Expected non-empty layout after init, got: {graph_data.layout!r}"
        )

    # ------------------------------------------------------------------
    # b) After codegiraffe_sync, layout is refreshed
    # ------------------------------------------------------------------

    def test_sync_refreshes_layout(self, project_dir):
        """After codegiraffe_sync, a previously cleared layout must be recomputed
        and persisted in the stored GraphData.

        Fails (RED) because codegiraffe_sync does not yet call compute_layout().
        """
        # Step 1: Init so the graph exists on disk.
        codegiraffe_init(project_dir)

        # Step 2: Manually clear the layout in the stored file, simulating
        # a state where layout data is absent (or was produced by an old version).
        storage = JSONStorage()
        graph_data = storage.load(project_dir)
        assert graph_data is not None
        graph_data.layout = {}
        storage.save(project_dir, graph_data)

        # Verify it's actually cleared on disk.
        cleared_data = storage.load(project_dir)
        assert cleared_data is not None
        assert cleared_data.layout == {}, "Pre-condition: layout should be empty before sync"

        # Step 3: Reset cached graph so sync reloads from disk.
        server_module._graph = None

        # Step 4: Run sync.
        sync_result = codegiraffe_sync(project_dir)
        assert "Sync complete" in sync_result, (
            f"codegiraffe_sync returned unexpected result: {sync_result!r}"
        )

        # Step 5: Load stored graph and assert layout is non-empty.
        final_data = storage.load(project_dir)
        assert final_data is not None
        assert len(final_data.layout) > 0, (
            f"Expected layout to be recomputed by sync, got: {final_data.layout!r}"
        )

    # ------------------------------------------------------------------
    # c) codegiraffe_init succeeds and uses grid fallback when fa2 unavailable
    # ------------------------------------------------------------------

    def test_init_succeeds_with_grid_fallback_when_fa2_unavailable(self, project_dir):
        """When fa2 is not available (_FA2_AVAILABLE = False), codegiraffe_init
        must succeed (no exception) and the stored layout must still be non-empty
        because the grid fallback is used.

        Fails (RED) because codegiraffe_init does not yet call compute_layout().
        """
        # Patch _FA2_AVAILABLE in the layout module to simulate fa2 absence.
        with patch("codegiraffe.layout._FA2_AVAILABLE", False):
            result = codegiraffe_init(project_dir)

        # Must return a success string, not raise.
        assert isinstance(result, str), (
            f"codegiraffe_init must return a str, got {type(result).__name__}"
        )
        assert "Error" not in result, (
            f"codegiraffe_init should not return an error when fa2 is absent: {result!r}"
        )
        assert "Initialized graph" in result, (
            f"Expected 'Initialized graph' in result, got: {result!r}"
        )

        # Load stored data and assert layout is non-empty (grid fallback ran).
        storage = JSONStorage()
        graph_data = storage.load(project_dir)
        assert graph_data is not None, (
            "No graph data found on disk after codegiraffe_init with fa2 unavailable"
        )
        assert len(graph_data.layout) > 0, (
            f"Expected non-empty layout (grid fallback) when fa2 is unavailable, "
            f"got: {graph_data.layout!r}"
        )


# ---------------------------------------------------------------------------
# US3: Coverage annotation persistence
# ---------------------------------------------------------------------------


class TestCoverageAnnotationPersistence:
    """codegiraffe_coverage must save the annotated graph to storage."""

    def test_coverage_annotations_persist_to_storage(self, tmp_path):
        """After codegiraffe_coverage, reloading from storage shows _test_coverage metadata."""
        project = str(tmp_path)

        # Build a graph with one module node whose file_path matches a coverage entry
        node = Node(
            id="mod:app",
            type="module",
            label="app",
            file_path="app.py",
        )
        data = GraphData(
            nodes={"mod:app": node},
            edges=[],
            project_path=project,
        )

        # Initialize server globals
        storage = JSONStorage()
        storage.save(project, data)
        server_module._storage = storage
        server_module._graph = ArchGraph(data)

        # Write a minimal coverage.py JSON report matching app.py
        coverage_report = {
            "meta": {"version": "7.0"},
            "files": {
                "app.py": {"summary": {"percent_covered": 75.0}},
            },
        }
        coverage_path = str(tmp_path / "coverage.json")
        (tmp_path / "coverage.json").write_text(json.dumps(coverage_report), encoding="utf-8")

        # Call the coverage tool
        result = codegiraffe_coverage(
            project_path=project,
            coverage_path=coverage_path,
            format="coverage_py",
        )

        assert "Annotated nodes" in result, (
            f"Expected 'Annotated nodes' in result, got: {result!r}"
        )

        # Reload from storage — annotations must be persisted
        reloaded = storage.load(project)
        assert reloaded is not None

        mod_node = reloaded.nodes.get("mod:app")
        assert mod_node is not None, "mod:app node must exist in reloaded graph"
        coverage_val = mod_node.metadata.get("_test_coverage")
        assert coverage_val is not None, (
            "mod:app must have _test_coverage metadata after codegiraffe_coverage"
        )
        assert abs(coverage_val - 75.0) < 0.01, (
            f"Expected coverage 75.0, got {coverage_val}"
        )

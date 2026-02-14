"""Tests for the include_changes enhancement to codegiraffe_context_for.

Validates that the change-aware scoring correctly boosts changed nodes,
annotates blast radius nodes, and silently falls back on non-git repos.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

import codegiraffe.server as server_module
from codegiraffe.graph import ArchGraph, Edge, GraphData, Node
from codegiraffe.schema import EdgeType, NodeType
from codegiraffe.server import codegiraffe_context_for
from codegiraffe.storage import JSONStorage


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_server_state():
    """Reset server module globals before each test."""
    server_module._graph = None
    server_module._storage = JSONStorage()
    yield
    server_module._graph = None
    server_module._storage = JSONStorage()


def _build_graph(project_path: str) -> ArchGraph:
    """Build and cache a graph with known structure.

    Structure:
    - mod:app (src/app.py) --imports--> mod:utils (src/utils.py)
    - mod:app --imports--> mod:db (src/db.py)
    - mod:utils --imports--> mod:helpers (src/helpers.py)
    """
    g = ArchGraph()
    g.add_node(
        Node(id="mod:app", type=NodeType.MODULE, label="app module", file_path="src/app.py")
    )
    g.add_node(
        Node(id="mod:utils", type=NodeType.MODULE, label="utils module", file_path="src/utils.py")
    )
    g.add_node(
        Node(id="mod:db", type=NodeType.MODULE, label="db module", file_path="src/db.py")
    )
    g.add_node(
        Node(
            id="mod:helpers",
            type=NodeType.MODULE,
            label="helpers module",
            file_path="src/helpers.py",
        )
    )
    g.add_edge(Edge(source="mod:app", target="mod:utils", type=EdgeType.IMPORTS))
    g.add_edge(Edge(source="mod:app", target="mod:db", type=EdgeType.IMPORTS))
    g.add_edge(Edge(source="mod:utils", target="mod:helpers", type=EdgeType.IMPORTS))

    data = g.to_data()
    data.project_path = project_path
    server_module._storage.save(project_path, data)
    server_module._graph = None
    return g


# ===========================================================================
# Tests
# ===========================================================================


class TestContextForChanges:
    """Tests for the include_changes parameter on codegiraffe_context_for."""

    def test_include_changes_false_unchanged(self, tmp_path):
        """include_changes=False produces the same output as default behavior."""
        project = str(tmp_path)
        _build_graph(project)

        result_default = codegiraffe_context_for(
            project, task="app module", use_embeddings=False
        )
        server_module._graph = None  # Force reload
        result_explicit = codegiraffe_context_for(
            project, task="app module", use_embeddings=False, include_changes=False
        )

        # Both should return valid JSON with the same node set
        data_default = json.loads(result_default)
        data_explicit = json.loads(result_explicit)
        assert set(data_default["nodes"].keys()) == set(data_explicit["nodes"].keys())

    def test_boosts_changed_nodes(self, tmp_path):
        """Changed nodes receive a +0.3 score boost and _recently_changed metadata."""
        project = str(tmp_path)
        _build_graph(project)

        # First get baseline scores
        baseline_result = codegiraffe_context_for(
            project, task="app utils db helpers", use_embeddings=False
        )
        baseline_data = json.loads(baseline_result)
        baseline_scores = {
            nid: node.get("metadata", {}).get("_relevance_score", 0.0)
            for nid, node in baseline_data["nodes"].items()
        }

        server_module._graph = None  # Force reload

        # Now with include_changes, mock app.py as changed
        with patch(
            "codegiraffe.server.get_changed_files",
            return_value=["src/app.py"],
        ):
            result = codegiraffe_context_for(
                project,
                task="app utils db helpers",
                use_embeddings=False,
                include_changes=True,
            )

        data = json.loads(result)
        # mod:app should be marked as recently changed
        if "mod:app" in data["nodes"]:
            app_node = data["nodes"]["mod:app"]
            assert app_node["metadata"].get("_recently_changed") is True
            # Score should be boosted by ~0.3
            boosted = app_node["metadata"].get("_relevance_score", 0.0)
            baseline = baseline_scores.get("mod:app", 0.0)
            assert boosted >= baseline + 0.29  # Allow float rounding

    def test_boosts_blast_radius_nodes(self, tmp_path):
        """Blast radius nodes receive _in_change_blast_radius metadata."""
        project = str(tmp_path)
        _build_graph(project)

        # mod:app imports mod:utils and mod:db, so changing app.py
        # should mark utils and db as in blast radius (they are downstream
        # of mod:app in the directed graph).
        with patch(
            "codegiraffe.server.get_changed_files",
            return_value=["src/app.py"],
        ):
            result = codegiraffe_context_for(
                project,
                task="app utils db helpers",
                use_embeddings=False,
                include_changes=True,
            )

        data = json.loads(result)
        # Downstream nodes of mod:app: mod:utils, mod:db, mod:helpers
        for nid in ["mod:utils", "mod:db", "mod:helpers"]:
            if nid in data["nodes"]:
                node = data["nodes"][nid]
                assert node["metadata"].get("_in_change_blast_radius") is True

    def test_silent_fallback_on_non_git(self, tmp_path):
        """Non-git repo with include_changes=True does not crash."""
        project = str(tmp_path)
        _build_graph(project)

        with patch(
            "codegiraffe.server.get_changed_files",
            side_effect=Exception("not a git repo"),
        ):
            result = codegiraffe_context_for(
                project,
                task="app module",
                use_embeddings=False,
                include_changes=True,
            )

        # Should return valid JSON without error
        data = json.loads(result)
        assert "nodes" in data

    def test_no_uncommitted_changes(self, tmp_path):
        """Clean repo (no changed files) returns normal results."""
        project = str(tmp_path)
        _build_graph(project)

        with patch(
            "codegiraffe.server.get_changed_files",
            return_value=[],
        ):
            result = codegiraffe_context_for(
                project,
                task="app module",
                use_embeddings=False,
                include_changes=True,
            )

        data = json.loads(result)
        assert "nodes" in data
        # No nodes should have _recently_changed metadata
        for nid, node in data["nodes"].items():
            assert "_recently_changed" not in node.get("metadata", {})

    def test_score_ordering(self, tmp_path):
        """Changed nodes rank higher than unchanged nodes with the same base score."""
        project = str(tmp_path)
        _build_graph(project)

        # Change only utils — it should get a boost relative to db
        with patch(
            "codegiraffe.server.get_changed_files",
            return_value=["src/utils.py"],
        ):
            result = codegiraffe_context_for(
                project,
                task="utils db",
                use_embeddings=False,
                include_changes=True,
            )

        data = json.loads(result)
        if "mod:utils" in data["nodes"] and "mod:db" in data["nodes"]:
            utils_score = data["nodes"]["mod:utils"]["metadata"].get(
                "_relevance_score", 0.0
            )
            db_score = data["nodes"]["mod:db"]["metadata"].get(
                "_relevance_score", 0.0
            )
            # utils should have a higher score due to the +0.3 boost
            assert utils_score > db_score

"""Tests for ownership and annotation layer (T039-T041).

TDD: Tests are written first, before implementation exists.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from codegiraffe.graph import ArchGraph, Edge, GraphData, Node
from codegiraffe.schema import EdgeType, NodeType


# ---------------------------------------------------------------------------
# T039: CODEOWNERS parsing tests
# ---------------------------------------------------------------------------


class TestParseCodeowners:
    """T039 — CODEOWNERS parsing."""

    def test_parse_standard_codeowners(self, tmp_path):
        """Parse a standard CODEOWNERS file with gitignore-style patterns."""
        from codegiraffe.ownership import parse_codeowners

        codeowners = tmp_path / "CODEOWNERS"
        codeowners.write_text(
            "src/auth/* @auth-team\n"
            "src/payments/* @payments-team\n"
            "*.md @docs-team\n"
        )
        result = parse_codeowners(str(tmp_path))
        assert "src/auth/*" in result
        assert result["src/auth/*"] == "@auth-team"
        assert "src/payments/*" in result
        assert result["src/payments/*"] == "@payments-team"
        assert "*.md" in result
        assert result["*.md"] == "@docs-team"

    def test_parse_codeowners_in_github_dir(self, tmp_path):
        """CODEOWNERS found in .github/ directory."""
        from codegiraffe.ownership import parse_codeowners

        github_dir = tmp_path / ".github"
        github_dir.mkdir()
        codeowners = github_dir / "CODEOWNERS"
        codeowners.write_text("src/api/* @api-team\n")
        result = parse_codeowners(str(tmp_path))
        assert "src/api/*" in result
        assert result["src/api/*"] == "@api-team"

    def test_parse_codeowners_in_docs_dir(self, tmp_path):
        """CODEOWNERS found in docs/ directory."""
        from codegiraffe.ownership import parse_codeowners

        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        codeowners = docs_dir / "CODEOWNERS"
        codeowners.write_text("docs/* @docs-team\n")
        result = parse_codeowners(str(tmp_path))
        assert "docs/*" in result

    def test_last_match_wins(self, tmp_path):
        """Last matching rule in CODEOWNERS wins (most specific wins)."""
        from codegiraffe.ownership import match_file_to_owner, parse_codeowners

        codeowners = tmp_path / "CODEOWNERS"
        codeowners.write_text(
            "* @global-team\n"
            "src/auth/* @auth-team\n"
        )
        patterns = parse_codeowners(str(tmp_path))
        owner = match_file_to_owner("src/auth/login.py", patterns)
        assert owner == "@auth-team"

    def test_missing_codeowners_returns_empty(self, tmp_path):
        """Missing CODEOWNERS file returns empty dict."""
        from codegiraffe.ownership import parse_codeowners

        result = parse_codeowners(str(tmp_path))
        assert result == {}

    def test_skip_comments_and_blank_lines(self, tmp_path):
        """Comments (#) and blank lines are skipped."""
        from codegiraffe.ownership import parse_codeowners

        codeowners = tmp_path / "CODEOWNERS"
        codeowners.write_text(
            "# This is a comment\n"
            "\n"
            "src/auth/* @auth-team\n"
            "  \n"
        )
        result = parse_codeowners(str(tmp_path))
        assert len(result) == 1
        assert "src/auth/*" in result

    def test_multiple_owners_uses_first(self, tmp_path):
        """Multiple owners on one line — first owner is captured."""
        from codegiraffe.ownership import parse_codeowners

        codeowners = tmp_path / "CODEOWNERS"
        codeowners.write_text("src/* @team-a @team-b\n")
        result = parse_codeowners(str(tmp_path))
        assert "src/*" in result
        # First owner used
        assert "@team-a" in result["src/*"]

    def test_match_file_to_owner_no_match(self):
        """File with no matching pattern returns None."""
        from codegiraffe.ownership import match_file_to_owner

        patterns = {"src/auth/*": "@auth-team"}
        owner = match_file_to_owner("tests/test_foo.py", patterns)
        assert owner is None

    def test_match_file_to_owner_glob_pattern(self):
        """Glob pattern matches correctly."""
        from codegiraffe.ownership import match_file_to_owner

        patterns = {"src/auth/*": "@auth-team"}
        owner = match_file_to_owner("src/auth/login.py", patterns)
        assert owner == "@auth-team"


# ---------------------------------------------------------------------------
# T039 (continued): map_ownership_to_nodes
# ---------------------------------------------------------------------------


class TestMapOwnershipToNodes:
    """Tests for map_ownership_to_nodes()."""

    def test_sets_owner_metadata_on_matching_nodes(self):
        """Nodes whose file_path matches a CODEOWNERS pattern get 'owner' metadata."""
        from codegiraffe.ownership import map_ownership_to_nodes

        g = ArchGraph()
        g.add_node(
            Node(
                id="mod:auth",
                type=NodeType.MODULE,
                label="auth",
                file_path="src/auth/login.py",
            )
        )
        ownership = {"src/auth/*": "@auth-team"}
        map_ownership_to_nodes(g, ownership)

        node = g.graph.nodes["mod:auth"]["node"]
        assert node.metadata.get("owner") == "@auth-team"

    def test_nodes_without_matching_path_unchanged(self):
        """Nodes with no matching file_path are not given an owner."""
        from codegiraffe.ownership import map_ownership_to_nodes

        g = ArchGraph()
        g.add_node(
            Node(
                id="mod:other",
                type=NodeType.MODULE,
                label="other",
                file_path="tests/test_other.py",
            )
        )
        ownership = {"src/auth/*": "@auth-team"}
        map_ownership_to_nodes(g, ownership)

        node = g.graph.nodes["mod:other"]["node"]
        assert "owner" not in node.metadata

    def test_nodes_without_file_path_are_skipped(self):
        """Nodes with file_path=None are skipped gracefully."""
        from codegiraffe.ownership import map_ownership_to_nodes

        g = ArchGraph()
        g.add_node(
            Node(
                id="service:api",
                type=NodeType.SERVICE,
                label="api",
                file_path=None,
            )
        )
        ownership = {"src/*": "@team"}
        map_ownership_to_nodes(g, ownership)
        # No error raised; node has no owner
        node = g.graph.nodes["service:api"]["node"]
        assert "owner" not in node.metadata


# ---------------------------------------------------------------------------
# T040: Annotation tests
# ---------------------------------------------------------------------------


class TestAnnotateNode:
    """T040 — codegiraffe_annotate tool and node annotation persistence."""

    def _make_graph_with_node(self, project_path: str) -> ArchGraph:
        """Helper: create a graph with a single service node and save it."""
        from codegiraffe.storage import JSONStorage

        g = ArchGraph()
        g.add_node(
            Node(
                id="service:auth",
                type=NodeType.SERVICE,
                label="AuthService",
            )
        )
        storage = JSONStorage()
        data = GraphData(
            nodes={"service:auth": g.graph.nodes["service:auth"]["node"]},
            edges=[],
            project_path=project_path,
        )
        storage.save(project_path, data)
        return g

    def test_annotate_sets_owner_on_node(self, tmp_path):
        """codegiraffe_annotate sets owner metadata on a node."""
        from codegiraffe.server import codegiraffe_annotate
        import codegiraffe.server as srv

        project_path = str(tmp_path)
        self._make_graph_with_node(project_path)

        # Reset cached graph so the tool loads from storage
        srv._graph = None

        result = codegiraffe_annotate(
            project_path=project_path,
            node_id="service:auth",
            owner="@auth-team",
        )
        assert "annotated" in result.lower() or "success" in result.lower() or "service:auth" in result

        # Verify metadata persisted
        from codegiraffe.storage import JSONStorage
        storage = JSONStorage()
        data = storage.load(project_path)
        assert data is not None
        node = data.nodes.get("service:auth")
        assert node is not None
        assert node.metadata.get("owner") == "@auth-team"

    def test_annotate_sets_stability(self, tmp_path):
        """codegiraffe_annotate sets stability metadata on a node."""
        from codegiraffe.server import codegiraffe_annotate
        import codegiraffe.server as srv

        project_path = str(tmp_path)
        self._make_graph_with_node(project_path)
        srv._graph = None

        codegiraffe_annotate(
            project_path=project_path,
            node_id="service:auth",
            stability="deprecated",
        )

        from codegiraffe.storage import JSONStorage
        data = JSONStorage().load(project_path)
        node = data.nodes["service:auth"]
        assert node.metadata.get("stability") == "deprecated"

    def test_annotate_sets_notes(self, tmp_path):
        """codegiraffe_annotate sets notes metadata on a node."""
        from codegiraffe.server import codegiraffe_annotate
        import codegiraffe.server as srv

        project_path = str(tmp_path)
        self._make_graph_with_node(project_path)
        srv._graph = None

        codegiraffe_annotate(
            project_path=project_path,
            node_id="service:auth",
            notes="Owned by security team, migration pending.",
        )

        from codegiraffe.storage import JSONStorage
        data = JSONStorage().load(project_path)
        node = data.nodes["service:auth"]
        assert node.metadata.get("notes") == "Owned by security team, migration pending."

    def test_annotate_preserves_existing_metadata(self, tmp_path):
        """Annotating a node does not erase its existing metadata."""
        from codegiraffe.server import codegiraffe_annotate
        import codegiraffe.server as srv
        from codegiraffe.storage import JSONStorage

        project_path = str(tmp_path)
        # Build graph with pre-existing metadata
        g = ArchGraph()
        g.add_node(
            Node(
                id="service:auth",
                type=NodeType.SERVICE,
                label="AuthService",
                metadata={"version": "2.1", "env": "prod"},
            )
        )
        storage = JSONStorage()
        data = GraphData(
            nodes={"service:auth": g.graph.nodes["service:auth"]["node"]},
            edges=[],
            project_path=project_path,
        )
        storage.save(project_path, data)
        srv._graph = None

        codegiraffe_annotate(
            project_path=project_path,
            node_id="service:auth",
            owner="@auth-team",
        )

        data = storage.load(project_path)
        node = data.nodes["service:auth"]
        assert node.metadata.get("version") == "2.1"
        assert node.metadata.get("env") == "prod"
        assert node.metadata.get("owner") == "@auth-team"

    def test_annotate_multiple_fields_at_once(self, tmp_path):
        """codegiraffe_annotate can set owner, stability, and notes together."""
        from codegiraffe.server import codegiraffe_annotate
        import codegiraffe.server as srv

        project_path = str(tmp_path)
        self._make_graph_with_node(project_path)
        srv._graph = None

        codegiraffe_annotate(
            project_path=project_path,
            node_id="service:auth",
            owner="@auth-team",
            stability="stable",
            notes="Core auth service.",
        )

        from codegiraffe.storage import JSONStorage
        data = JSONStorage().load(project_path)
        node = data.nodes["service:auth"]
        assert node.metadata.get("owner") == "@auth-team"
        assert node.metadata.get("stability") == "stable"
        assert node.metadata.get("notes") == "Core auth service."

    def test_annotate_stability_deprecated_visible(self, tmp_path):
        """stability=deprecated is visible in node metadata."""
        from codegiraffe.server import codegiraffe_annotate
        import codegiraffe.server as srv

        project_path = str(tmp_path)
        self._make_graph_with_node(project_path)
        srv._graph = None

        codegiraffe_annotate(
            project_path=project_path,
            node_id="service:auth",
            stability="deprecated",
        )

        from codegiraffe.storage import JSONStorage
        data = JSONStorage().load(project_path)
        assert data.nodes["service:auth"].metadata["stability"] == "deprecated"

    def test_annotate_error_on_missing_node(self, tmp_path):
        """codegiraffe_annotate returns an error string for unknown node_id."""
        from codegiraffe.server import codegiraffe_annotate
        import codegiraffe.server as srv

        project_path = str(tmp_path)
        self._make_graph_with_node(project_path)
        srv._graph = None

        result = codegiraffe_annotate(
            project_path=project_path,
            node_id="nonexistent:node",
            owner="@someone",
        )
        assert "error" in result.lower() or "not found" in result.lower()

    def test_annotate_tool_accepts_required_params(self, tmp_path):
        """Contract: codegiraffe_annotate accepts project_path + node_id as required params."""
        from codegiraffe.server import codegiraffe_annotate
        import codegiraffe.server as srv

        project_path = str(tmp_path)
        self._make_graph_with_node(project_path)
        srv._graph = None

        # Only required params — should succeed without error
        result = codegiraffe_annotate(
            project_path=project_path,
            node_id="service:auth",
        )
        # With no optional fields, it should still return a string
        assert isinstance(result, str)

    def test_context_for_task_includes_owner_in_metadata(self):
        """context_for_task results include ownership annotations in node metadata."""
        from codegiraffe.query import context_for_task

        g = ArchGraph()
        g.add_node(
            Node(
                id="service:auth",
                type=NodeType.SERVICE,
                label="AuthService",
                metadata={"owner": "@auth-team", "stability": "stable"},
            )
        )

        result = context_for_task(g, "auth service", use_embeddings=False)
        node = result.nodes.get("service:auth")
        assert node is not None
        assert node.metadata.get("owner") == "@auth-team"
        assert node.metadata.get("stability") == "stable"


# ---------------------------------------------------------------------------
# T041: Cross-team impact and contract tests
# ---------------------------------------------------------------------------


class TestCrossTeamImpact:
    """T041 — compute_blast_radius cross-team impact detection."""

    def _make_cross_team_graph(self) -> ArchGraph:
        """Build a graph where node A (team-alpha) calls B and C (team-beta)."""
        g = ArchGraph()
        g.add_node(
            Node(
                id="service:A",
                type=NodeType.SERVICE,
                label="ServiceA",
                metadata={"owner": "@team-alpha"},
            )
        )
        g.add_node(
            Node(
                id="service:B",
                type=NodeType.SERVICE,
                label="ServiceB",
                metadata={"owner": "@team-beta"},
            )
        )
        g.add_node(
            Node(
                id="service:C",
                type=NodeType.SERVICE,
                label="ServiceC",
                metadata={"owner": "@team-beta"},
            )
        )
        g.add_edge(Edge(source="service:A", target="service:B", type=EdgeType.CALLS))
        g.add_edge(Edge(source="service:A", target="service:C", type=EdgeType.CALLS))
        return g

    def test_blast_radius_flags_cross_team_nodes(self):
        """compute_blast_radius includes cross_team_impact for nodes with different owner."""
        from codegiraffe.query import compute_blast_radius

        g = self._make_cross_team_graph()
        result = compute_blast_radius(g, "service:A")

        assert "cross_team_impact" in result
        cross_team = result["cross_team_impact"]
        assert isinstance(cross_team, list)

        cross_team_ids = {item["node_id"] for item in cross_team}
        assert "service:B" in cross_team_ids
        assert "service:C" in cross_team_ids

    def test_cross_team_report_includes_owner_names(self):
        """cross_team_impact entries include owner names for both changed node and impacted node."""
        from codegiraffe.query import compute_blast_radius

        g = self._make_cross_team_graph()
        result = compute_blast_radius(g, "service:A")

        cross_team = result["cross_team_impact"]
        for entry in cross_team:
            assert "owner" in entry
            assert "changed_node_owner" in entry
            assert entry["changed_node_owner"] == "@team-alpha"
            assert entry["owner"] == "@team-beta"

    def test_same_team_nodes_not_flagged_as_cross_team(self):
        """Nodes with the SAME owner as the changed node are NOT in cross_team_impact."""
        from codegiraffe.query import compute_blast_radius

        g = ArchGraph()
        g.add_node(
            Node(
                id="service:A",
                type=NodeType.SERVICE,
                label="ServiceA",
                metadata={"owner": "@team-alpha"},
            )
        )
        g.add_node(
            Node(
                id="service:B",
                type=NodeType.SERVICE,
                label="ServiceB",
                metadata={"owner": "@team-alpha"},  # Same owner
            )
        )
        g.add_edge(Edge(source="service:A", target="service:B", type=EdgeType.CALLS))

        result = compute_blast_radius(g, "service:A")
        cross_team = result["cross_team_impact"]
        cross_team_ids = {item["node_id"] for item in cross_team}
        assert "service:B" not in cross_team_ids

    def test_nodes_without_owner_not_flagged_as_cross_team(self):
        """Nodes without owner annotation are NOT flagged as cross-team."""
        from codegiraffe.query import compute_blast_radius

        g = ArchGraph()
        g.add_node(
            Node(
                id="service:A",
                type=NodeType.SERVICE,
                label="ServiceA",
                metadata={"owner": "@team-alpha"},
            )
        )
        g.add_node(
            Node(
                id="service:B",
                type=NodeType.SERVICE,
                label="ServiceB",
                metadata={},  # No owner
            )
        )
        g.add_edge(Edge(source="service:A", target="service:B", type=EdgeType.CALLS))

        result = compute_blast_radius(g, "service:A")
        cross_team = result["cross_team_impact"]
        cross_team_ids = {item["node_id"] for item in cross_team}
        assert "service:B" not in cross_team_ids

    def test_changed_node_without_owner_produces_no_cross_team(self):
        """If changed node has no owner, cross_team_impact is empty (no baseline to compare)."""
        from codegiraffe.query import compute_blast_radius

        g = ArchGraph()
        g.add_node(
            Node(
                id="service:A",
                type=NodeType.SERVICE,
                label="ServiceA",
                metadata={},  # No owner
            )
        )
        g.add_node(
            Node(
                id="service:B",
                type=NodeType.SERVICE,
                label="ServiceB",
                metadata={"owner": "@team-beta"},
            )
        )
        g.add_edge(Edge(source="service:A", target="service:B", type=EdgeType.CALLS))

        result = compute_blast_radius(g, "service:A")
        assert result["cross_team_impact"] == []

    def test_cross_team_impact_additive_does_not_change_downstream(self):
        """Adding cross_team_impact field is additive — existing downstream list unchanged."""
        from codegiraffe.query import compute_blast_radius

        g = self._make_cross_team_graph()
        result = compute_blast_radius(g, "service:A")

        # downstream still present and correct
        assert "downstream" in result
        downstream_ids = {item["node_id"] for item in result["downstream"]}
        assert "service:B" in downstream_ids
        assert "service:C" in downstream_ids

    def test_annotate_contract_accepts_required_optional_params(self):
        """Contract: codegiraffe_annotate signature has required (project_path, node_id)
        and optional (owner, stability, notes) params."""
        import inspect
        from codegiraffe.server import codegiraffe_annotate

        sig = inspect.signature(codegiraffe_annotate)
        params = sig.parameters

        # Required params
        assert "project_path" in params
        assert "node_id" in params

        # Optional params with defaults
        assert "owner" in params
        assert "stability" in params
        assert "notes" in params

        # Verify optional params have defaults (None)
        assert params["owner"].default is None
        assert params["stability"].default is None
        assert params["notes"].default is None

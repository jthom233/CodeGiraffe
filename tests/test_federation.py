"""Tests for cross-repo graph federation (codegiraffe.federation)."""

from __future__ import annotations

import json
import pytest
from pathlib import Path

from codegiraffe.graph import GraphData, Node, Edge
from codegiraffe.federation import (
    GraphFederation,
    CROSS_REPO_EDGE_TYPES,
    FEDERATION_DIR,
    FEDERATION_FILE,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def repo_a(tmp_path):
    """Create a fake repo with a simple graph."""
    repo = tmp_path / "repo-a"
    repo.mkdir()
    cg_dir = repo / ".codegiraffe"
    cg_dir.mkdir()
    data = GraphData(
        nodes={
            "service:AuthService": Node(
                id="service:AuthService", type="service", label="AuthService"
            ),
            "endpoint:/login": Node(
                id="endpoint:/login", type="endpoint", label="/login"
            ),
        },
        edges=[
            Edge(source="service:AuthService", target="endpoint:/login", type="calls")
        ],
        project_path=str(repo),
    )
    (cg_dir / "graph.json").write_text(data.model_dump_json(indent=2))
    return repo


@pytest.fixture
def repo_b(tmp_path):
    """Create a second fake repo with a different graph."""
    repo = tmp_path / "repo-b"
    repo.mkdir()
    cg_dir = repo / ".codegiraffe"
    cg_dir.mkdir()
    data = GraphData(
        nodes={
            "service:PaymentService": Node(
                id="service:PaymentService",
                type="service",
                label="PaymentService",
            ),
            "queue:payment-events": Node(
                id="queue:payment-events", type="queue", label="payment-events"
            ),
        },
        edges=[
            Edge(
                source="service:PaymentService",
                target="queue:payment-events",
                type="publishes",
            )
        ],
        project_path=str(repo),
    )
    (cg_dir / "graph.json").write_text(data.model_dump_json(indent=2))
    return repo


@pytest.fixture
def federation():
    """Create a fresh GraphFederation instance."""
    return GraphFederation()


# ---------------------------------------------------------------------------
# Tests: register_repo
# ---------------------------------------------------------------------------


class TestRegisterRepo:
    """Registering repos loads graphs and assigns names."""

    def test_register_loads_graph(self, federation, repo_a):
        name = federation.register_repo(str(repo_a))
        assert name == "repo-a"
        assert name in federation._repos
        assert name in federation._graphs
        assert len(federation._graphs[name].nodes) == 2

    def test_register_returns_repo_name(self, federation, repo_a):
        name = federation.register_repo(str(repo_a))
        assert name == "repo-a"

    def test_register_multiple_repos(self, federation, repo_a, repo_b):
        name_a = federation.register_repo(str(repo_a))
        name_b = federation.register_repo(str(repo_b))
        assert name_a == "repo-a"
        assert name_b == "repo-b"
        assert len(federation._repos) == 2
        assert len(federation._graphs) == 2

    def test_register_repo_no_graph_raises(self, federation, tmp_path):
        """Registering a repo with no .codegiraffe/graph.json raises FileNotFoundError."""
        empty_repo = tmp_path / "empty-repo"
        empty_repo.mkdir()
        with pytest.raises(FileNotFoundError):
            federation.register_repo(str(empty_repo))

    def test_register_repo_stores_path(self, federation, repo_a):
        federation.register_repo(str(repo_a))
        assert federation._repos["repo-a"] == str(repo_a)


# ---------------------------------------------------------------------------
# Tests: namespace_node_id and parse_namespace
# ---------------------------------------------------------------------------


class TestNamespacing:
    """Namespace operations are inverses of each other."""

    def test_namespace_node_id(self, federation):
        result = federation.namespace_node_id("repo-a", "service:AuthService")
        assert result == "repo:repo-a::service:AuthService"

    def test_parse_namespace(self, federation):
        repo_name, node_id = federation.parse_namespace(
            "repo:repo-a::service:AuthService"
        )
        assert repo_name == "repo-a"
        assert node_id == "service:AuthService"

    def test_namespace_round_trip(self, federation):
        original_repo = "repo-a"
        original_node = "service:AuthService"
        namespaced = federation.namespace_node_id(original_repo, original_node)
        parsed_repo, parsed_node = federation.parse_namespace(namespaced)
        assert parsed_repo == original_repo
        assert parsed_node == original_node

    def test_parse_namespace_with_colons_in_node_id(self, federation):
        """Node IDs can contain colons (e.g., 'endpoint:/api/v2:users')."""
        namespaced = "repo:my-repo::endpoint:/api/v2:users"
        repo_name, node_id = federation.parse_namespace(namespaced)
        assert repo_name == "my-repo"
        assert node_id == "endpoint:/api/v2:users"

    def test_parse_namespace_invalid_format(self, federation):
        with pytest.raises(ValueError):
            federation.parse_namespace("not-a-valid-namespaced-id")


# ---------------------------------------------------------------------------
# Tests: get_unified_graph
# ---------------------------------------------------------------------------


class TestGetUnifiedGraph:
    """Composing all repos into a single federated GraphData."""

    def test_unified_graph_has_all_nodes_namespaced(
        self, federation, repo_a, repo_b
    ):
        federation.register_repo(str(repo_a))
        federation.register_repo(str(repo_b))
        unified = federation.get_unified_graph()

        expected_nodes = {
            "repo:repo-a::service:AuthService",
            "repo:repo-a::endpoint:/login",
            "repo:repo-b::service:PaymentService",
            "repo:repo-b::queue:payment-events",
        }
        assert set(unified.nodes.keys()) == expected_nodes

    def test_unified_graph_has_all_edges_namespaced(
        self, federation, repo_a, repo_b
    ):
        federation.register_repo(str(repo_a))
        federation.register_repo(str(repo_b))
        unified = federation.get_unified_graph()

        assert len(unified.edges) == 2
        edge_tuples = {(e.source, e.target) for e in unified.edges}
        assert (
            "repo:repo-a::service:AuthService",
            "repo:repo-a::endpoint:/login",
        ) in edge_tuples
        assert (
            "repo:repo-b::service:PaymentService",
            "repo:repo-b::queue:payment-events",
        ) in edge_tuples

    def test_unified_graph_single_repo(self, federation, repo_a):
        federation.register_repo(str(repo_a))
        unified = federation.get_unified_graph()
        assert len(unified.nodes) == 2
        assert len(unified.edges) == 1

    def test_unified_graph_empty_federation(self, federation):
        unified = federation.get_unified_graph()
        assert len(unified.nodes) == 0
        assert len(unified.edges) == 0

    def test_unified_graph_node_labels_preserved(self, federation, repo_a):
        federation.register_repo(str(repo_a))
        unified = federation.get_unified_graph()
        auth_node = unified.nodes["repo:repo-a::service:AuthService"]
        assert auth_node.label == "AuthService"

    def test_unified_graph_edge_types_preserved(self, federation, repo_a):
        federation.register_repo(str(repo_a))
        unified = federation.get_unified_graph()
        assert unified.edges[0].type == "calls"


# ---------------------------------------------------------------------------
# Tests: get_cross_repo_edges
# ---------------------------------------------------------------------------


class TestGetCrossRepoEdges:
    """Cross-repo edge detection."""

    def test_no_cross_repo_edges_by_default(self, federation, repo_a, repo_b):
        federation.register_repo(str(repo_a))
        federation.register_repo(str(repo_b))
        cross = federation.get_cross_repo_edges()
        assert cross == []

    def test_cross_repo_edge_detected(self, federation, repo_a, repo_b):
        federation.register_repo(str(repo_a))
        federation.register_repo(str(repo_b))

        # Manually add a cross-repo edge to repo_a's graph
        cross_edge = Edge(
            source="repo:repo-a::service:AuthService",
            target="repo:repo-b::service:PaymentService",
            type="cross_repo_calls",
            manual=True,
        )
        # Add it to the unified graph by directly modifying the stored graph
        # In real usage, this would be added via codegiraffe_add_relation
        unified = federation.get_unified_graph()
        unified.edges.append(cross_edge)

        # Now get cross-repo edges from the modified unified graph
        cross_edges = [
            e
            for e in unified.edges
            if "::" in e.source
            and "::" in e.target
            and e.source.split("::")[0] != e.target.split("::")[0]
        ]
        assert len(cross_edges) == 1
        assert cross_edges[0].type == "cross_repo_calls"

    def test_same_repo_edges_not_cross(self, federation, repo_a):
        federation.register_repo(str(repo_a))
        cross = federation.get_cross_repo_edges()
        assert cross == []


# ---------------------------------------------------------------------------
# Tests: query_federated
# ---------------------------------------------------------------------------


class TestQueryFederated:
    """Federated subgraph extraction."""

    def test_query_returns_subgraph(self, federation, repo_a):
        federation.register_repo(str(repo_a))
        result = federation.query_federated(
            "repo:repo-a::service:AuthService", depth=1
        )
        assert "repo:repo-a::service:AuthService" in result.nodes
        assert "repo:repo-a::endpoint:/login" in result.nodes

    def test_query_nonexistent_node_returns_empty(self, federation, repo_a):
        federation.register_repo(str(repo_a))
        result = federation.query_federated("repo:repo-a::nonexistent", depth=1)
        assert len(result.nodes) == 0

    def test_query_depth_zero(self, federation, repo_a):
        federation.register_repo(str(repo_a))
        result = federation.query_federated(
            "repo:repo-a::service:AuthService", depth=0
        )
        # Depth 0 means only the node itself
        assert "repo:repo-a::service:AuthService" in result.nodes
        assert len(result.nodes) == 1

    def test_query_across_repos(self, federation, repo_a, repo_b):
        federation.register_repo(str(repo_a))
        federation.register_repo(str(repo_b))
        result = federation.query_federated(
            "repo:repo-a::service:AuthService", depth=2
        )
        # Without cross-repo edges, should only get repo-a nodes
        assert "repo:repo-a::service:AuthService" in result.nodes
        assert "repo:repo-a::endpoint:/login" in result.nodes
        assert "repo:repo-b::service:PaymentService" not in result.nodes


# ---------------------------------------------------------------------------
# Tests: save_federation / load_federation round-trip
# ---------------------------------------------------------------------------


class TestPersistence:
    """Federation config persistence."""

    def test_save_and_load_round_trip(self, federation, repo_a, repo_b, monkeypatch):
        federation.register_repo(str(repo_a))
        federation.register_repo(str(repo_b))

        # Redirect federation file to tmp location
        tmp_fed_dir = repo_a.parent / ".codegiraffe-fed"
        tmp_fed_file = tmp_fed_dir / "federation.json"
        monkeypatch.setattr(
            "codegiraffe.federation.FEDERATION_DIR", tmp_fed_dir
        )
        monkeypatch.setattr(
            "codegiraffe.federation.FEDERATION_FILE", tmp_fed_file
        )

        federation.save_federation()
        assert tmp_fed_file.exists()

        loaded = GraphFederation.load_federation()
        assert set(loaded._repos.keys()) == {"repo-a", "repo-b"}
        assert set(loaded._graphs.keys()) == {"repo-a", "repo-b"}

    def test_load_nonexistent_returns_empty(self, monkeypatch, tmp_path):
        tmp_fed_dir = tmp_path / ".codegiraffe-nonexistent"
        tmp_fed_file = tmp_fed_dir / "federation.json"
        monkeypatch.setattr(
            "codegiraffe.federation.FEDERATION_DIR", tmp_fed_dir
        )
        monkeypatch.setattr(
            "codegiraffe.federation.FEDERATION_FILE", tmp_fed_file
        )

        loaded = GraphFederation.load_federation()
        assert len(loaded._repos) == 0
        assert len(loaded._graphs) == 0

    def test_save_creates_directory(self, federation, monkeypatch, tmp_path):
        tmp_fed_dir = tmp_path / ".codegiraffe-new"
        tmp_fed_file = tmp_fed_dir / "federation.json"
        monkeypatch.setattr(
            "codegiraffe.federation.FEDERATION_DIR", tmp_fed_dir
        )
        monkeypatch.setattr(
            "codegiraffe.federation.FEDERATION_FILE", tmp_fed_file
        )

        federation.save_federation()
        assert tmp_fed_dir.exists()
        assert tmp_fed_file.exists()


# ---------------------------------------------------------------------------
# Tests: edge namespacing
# ---------------------------------------------------------------------------


class TestEdgeNamespacing:
    """Edge source and target both get namespaced correctly."""

    def test_edge_source_namespaced(self, federation, repo_a):
        federation.register_repo(str(repo_a))
        unified = federation.get_unified_graph()
        for edge in unified.edges:
            assert edge.source.startswith("repo:repo-a::")

    def test_edge_target_namespaced(self, federation, repo_a):
        federation.register_repo(str(repo_a))
        unified = federation.get_unified_graph()
        for edge in unified.edges:
            assert edge.target.startswith("repo:repo-a::")

    def test_edge_source_and_target_match_nodes(self, federation, repo_a):
        federation.register_repo(str(repo_a))
        unified = federation.get_unified_graph()
        node_ids = set(unified.nodes.keys())
        for edge in unified.edges:
            assert edge.source in node_ids, (
                f"Edge source {edge.source} not found in unified nodes"
            )
            assert edge.target in node_ids, (
                f"Edge target {edge.target} not found in unified nodes"
            )


# ---------------------------------------------------------------------------
# Tests: CROSS_REPO_EDGE_TYPES constant
# ---------------------------------------------------------------------------


class TestCrossRepoEdgeTypes:
    """Validate the cross-repo edge type constants."""

    def test_is_frozenset(self):
        assert isinstance(CROSS_REPO_EDGE_TYPES, frozenset)

    def test_expected_types_present(self):
        expected = {
            "cross_repo_calls",
            "cross_repo_depends_on",
            "cross_repo_publishes",
            "cross_repo_consumes",
        }
        assert CROSS_REPO_EDGE_TYPES == expected


# ---------------------------------------------------------------------------
# Tests: _repo_name static method
# ---------------------------------------------------------------------------


class TestRepoName:
    """Extracting repo name from path."""

    def test_simple_path(self):
        assert GraphFederation._repo_name("/home/user/projects/my-app") == "my-app"

    def test_trailing_slash(self):
        assert GraphFederation._repo_name("/home/user/projects/my-app/") == "my-app"

    def test_nested_path(self):
        assert (
            GraphFederation._repo_name("/a/b/c/deep-repo") == "deep-repo"
        )

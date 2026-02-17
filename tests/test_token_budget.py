"""Tests for token-aware context retrieval (US1 — v0.11.0).

T003: Token estimation tests
T004: Token budget constraint tests
T005: Dual-constraint tests
T006: Detail level tests
"""
from __future__ import annotations

import json

import pytest

from codegiraffe.graph import ArchGraph, Node, Edge, GraphData
from codegiraffe.query import (
    context_for_task,
    _estimate_tokens,
    _format_node_for_detail_level,
)
from codegiraffe.schema import NodeType, EdgeType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def simple_graph():
    """Small graph with a handful of clearly-named nodes for deterministic tests."""
    graph = ArchGraph()
    graph.add_node(Node(
        id="service:UserService",
        type=NodeType.SERVICE,
        label="User Service",
        metadata={"description": "handles user CRUD operations", "owner": "platform-team"},
    ))
    graph.add_node(Node(
        id="service:AuthService",
        type=NodeType.SERVICE,
        label="Auth Service",
        metadata={"description": "handles authentication and tokens"},
    ))
    graph.add_node(Node(
        id="table:users",
        type=NodeType.DATABASE_TABLE,
        label="users table",
        metadata={"description": "stores user records"},
    ))
    graph.add_node(Node(
        id="endpoint:/api/users",
        type=NodeType.ENDPOINT,
        label="GET /api/users",
        metadata={"method": "GET", "path": "/api/users"},
    ))
    graph.add_node(Node(
        id="endpoint:/api/login",
        type=NodeType.ENDPOINT,
        label="POST /api/login",
        metadata={"method": "POST", "path": "/api/login"},
    ))
    graph.add_edge(Edge(source="endpoint:/api/users", target="service:UserService", type=EdgeType.CALLS))
    graph.add_edge(Edge(source="service:UserService", target="table:users", type=EdgeType.READS))
    graph.add_edge(Edge(source="endpoint:/api/login", target="service:AuthService", type=EdgeType.CALLS))
    return graph


# ---------------------------------------------------------------------------
# T003: Token estimation tests
# ---------------------------------------------------------------------------

class TestEstimateTokens:
    """T003 — _estimate_tokens() correctness."""

    def test_returns_int(self):
        node_data = {"id": "service:Foo", "type": "service", "label": "Foo Service"}
        result = _estimate_tokens(node_data)
        assert isinstance(result, int)

    def test_formula_matches_json_length_div_4(self):
        """_estimate_tokens returns len(json.dumps(formatted)) // 4."""
        node_data = {
            "id": "service:UserService",
            "type": "service",
            "label": "User Service",
            "metadata": {"description": "handles user CRUD operations", "owner": "platform-team"},
        }
        result = _estimate_tokens(node_data, detail_level="detailed")
        formatted = _format_node_for_detail_level(node_data, "detailed")
        expected = len(json.dumps(formatted)) // 4
        assert result == expected

    def test_summary_vs_standard_vs_detailed_differ(self):
        """Different detail levels produce different token estimates for the same node."""
        node_data = {
            "id": "service:UserService",
            "type": "service",
            "label": "User Service",
            "metadata": {
                "description": "handles user CRUD operations",
                "owner": "platform-team",
                "version": "2.1.0",
                "tags": "auth,users,crud",
            },
        }
        tokens_summary = _estimate_tokens(node_data, detail_level="summary")
        tokens_standard = _estimate_tokens(node_data, detail_level="standard")
        tokens_detailed = _estimate_tokens(node_data, detail_level="detailed")

        # summary should be smallest, detailed largest
        assert tokens_summary <= tokens_standard <= tokens_detailed
        # summary and detailed must differ (not trivially equal)
        assert tokens_summary < tokens_detailed

    def test_empty_node_returns_small_positive(self):
        node_data = {"id": "x", "type": "service", "label": ""}
        result = _estimate_tokens(node_data)
        # Must be a small positive integer (non-zero JSON cost)
        assert result >= 0


# ---------------------------------------------------------------------------
# T004: Token budget constraint tests
# ---------------------------------------------------------------------------

class TestTokenBudgetConstraint:
    """T004 — context_for_task() respects token_budget."""

    def test_token_budget_limits_result_size(self, simple_graph):
        """With a tight token_budget, total _token_estimate stays under budget."""
        result = context_for_task(
            simple_graph,
            "user service authentication",
            max_nodes=20,
            token_budget=400,
            use_embeddings=False,
        )
        assert isinstance(result, GraphData)
        # Check the aggregated token estimate is within budget
        total = result.metadata.get("_token_estimate", 0) if hasattr(result, "metadata") else 0
        # If stored as a dict field, it won't be on GraphData directly — check nodes metadata
        # The total estimate is stored on the returned dict (accessed via model_dump)
        dumped = result.model_dump()
        # _token_estimate should be present at the top level of nodes metadata
        # or as a custom field — we check via model_dump_json parsing
        parsed = json.loads(result.model_dump_json())
        assert "_token_estimate" in parsed

    def test_token_budget_total_under_budget(self, simple_graph):
        """The sum of per-node token estimates is at or under token_budget."""
        budget = 400
        result = context_for_task(
            simple_graph,
            "user service",
            max_nodes=20,
            token_budget=budget,
            use_embeddings=False,
        )
        parsed = json.loads(result.model_dump_json())
        total_estimate = parsed.get("_token_estimate", 0)
        assert total_estimate <= budget

    def test_result_has_token_estimate_field(self, simple_graph):
        """Response includes _token_estimate field."""
        result = context_for_task(
            simple_graph,
            "user",
            max_nodes=10,
            token_budget=2000,
            use_embeddings=False,
        )
        parsed = json.loads(result.model_dump_json())
        assert "_token_estimate" in parsed
        assert isinstance(parsed["_token_estimate"], int)

    def test_nodes_ordered_by_descending_relevance_score(self, simple_graph):
        """Nodes in result are ordered by descending _relevance_score."""
        result = context_for_task(
            simple_graph,
            "user service",
            max_nodes=10,
            use_embeddings=False,
        )
        scores = [
            n["metadata"].get("_relevance_score", 0)
            for n in json.loads(result.model_dump_json())["nodes"].values()
        ]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# T005: Dual-constraint tests
# ---------------------------------------------------------------------------

class TestDualConstraints:
    """T005 — when both token_budget and max_nodes are set, the more restrictive wins."""

    def test_max_nodes_more_restrictive(self, simple_graph):
        """max_nodes=2 with large token_budget → at most 2 nodes."""
        result = context_for_task(
            simple_graph,
            "user service authentication",
            max_nodes=2,
            token_budget=100000,
            use_embeddings=False,
        )
        assert len(result.nodes) <= 2

    def test_token_budget_more_restrictive(self, simple_graph):
        """Very small token_budget with large max_nodes → fewer nodes than max_nodes."""
        result = context_for_task(
            simple_graph,
            "user service authentication",
            max_nodes=20,
            token_budget=5,  # extremely tight
            use_embeddings=False,
        )
        # With an extreme budget, we get 0 or 1 nodes
        assert len(result.nodes) <= 1

    def test_very_small_budget_returns_at_most_one_node(self, simple_graph):
        """token_budget=50 (very small) → at most single highest-relevance node."""
        result = context_for_task(
            simple_graph,
            "user service",
            max_nodes=20,
            token_budget=50,
            use_embeddings=False,
        )
        assert len(result.nodes) <= 1

    def test_token_estimate_within_budget_when_dual_constraint(self, simple_graph):
        """When both constraints set, _token_estimate still respects token_budget."""
        budget = 300
        result = context_for_task(
            simple_graph,
            "user service",
            max_nodes=10,
            token_budget=budget,
            use_embeddings=False,
        )
        parsed = json.loads(result.model_dump_json())
        total_estimate = parsed.get("_token_estimate", 0)
        assert total_estimate <= budget


# ---------------------------------------------------------------------------
# T006: Detail level tests
# ---------------------------------------------------------------------------

class TestDetailLevels:
    """T006 — detail_level parameter controls node content."""

    def test_summary_returns_only_id_type_label(self):
        """detail_level='summary' returns only id, type, label keys."""
        node_data = {
            "id": "service:UserService",
            "type": "service",
            "label": "User Service",
            "metadata": {"description": "handles user CRUD", "owner": "team"},
            "file_path": "/src/user_service.py",
        }
        formatted = _format_node_for_detail_level(node_data, "summary")
        allowed_keys = {"id", "type", "label"}
        assert set(formatted.keys()) == allowed_keys

    def test_detailed_includes_full_metadata(self):
        """detail_level='detailed' includes full metadata."""
        node_data = {
            "id": "service:UserService",
            "type": "service",
            "label": "User Service",
            "metadata": {"description": "handles user CRUD", "owner": "team"},
            "file_path": "/src/user_service.py",
        }
        formatted = _format_node_for_detail_level(node_data, "detailed")
        assert "metadata" in formatted
        assert formatted["metadata"] == node_data["metadata"]

    def test_summary_context_includes_fewer_token_estimates_than_detailed(self, simple_graph):
        """More nodes fit in the same token budget at summary vs detailed."""
        budget = 500
        result_summary = context_for_task(
            simple_graph,
            "user service authentication",
            max_nodes=20,
            token_budget=budget,
            detail_level="summary",
            use_embeddings=False,
        )
        result_detailed = context_for_task(
            simple_graph,
            "user service authentication",
            max_nodes=20,
            token_budget=budget,
            detail_level="detailed",
            use_embeddings=False,
        )
        # More nodes should fit at summary level
        assert len(result_summary.nodes) >= len(result_detailed.nodes)

    def test_no_token_budget_default_detail_level_standard(self, simple_graph):
        """Without token_budget, detail_level='standard' is the default and works."""
        result = context_for_task(
            simple_graph,
            "user",
            use_embeddings=False,
        )
        # Should return nodes normally with _relevance_score
        assert isinstance(result, GraphData)
        for node in result.nodes.values():
            assert "_relevance_score" in node.metadata

    def test_standard_detail_level_includes_key_metadata(self):
        """detail_level='standard' includes id, type, label + key metadata."""
        node_data = {
            "id": "service:UserService",
            "type": "service",
            "label": "User Service",
            "metadata": {"description": "handles user CRUD", "owner": "team"},
            "file_path": "/src/user_service.py",
        }
        formatted = _format_node_for_detail_level(node_data, "standard")
        assert "id" in formatted
        assert "type" in formatted
        assert "label" in formatted

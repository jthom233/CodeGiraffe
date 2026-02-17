"""Tests for intent-aware navigation (US2 — v0.11.0).

T010: Intent classification tests
T011: Intent-specific retrieval tests
T012: Retrieval strategy response tests
"""
from __future__ import annotations

import json

import pytest

from codegiraffe.graph import ArchGraph, Node, Edge, GraphData
from codegiraffe.query import (
    _classify_intent,
    context_for_task,
)
from codegiraffe.schema import NodeType, EdgeType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def import_graph():
    """Graph with import edges between modules for dependency-chain tests."""
    graph = ArchGraph()
    # Module A imports module B, module B imports module C
    graph.add_node(Node(
        id="module:a",
        type=NodeType.MODULE,
        label="module_a",
        metadata={"file_path": "src/a.py"},
    ))
    graph.add_node(Node(
        id="module:b",
        type=NodeType.MODULE,
        label="module_b",
        metadata={"file_path": "src/b.py"},
    ))
    graph.add_node(Node(
        id="module:c",
        type=NodeType.MODULE,
        label="module_c",
        metadata={"file_path": "src/c.py"},
    ))
    graph.add_node(Node(
        id="module:unrelated",
        type=NodeType.MODULE,
        label="module_unrelated",
        metadata={"file_path": "src/unrelated.py"},
    ))
    # a imports b, b imports c
    graph.add_edge(Edge(source="module:a", target="module:b", type=EdgeType.IMPORTS))
    graph.add_edge(Edge(source="module:b", target="module:c", type=EdgeType.IMPORTS))
    return graph


@pytest.fixture
def service_graph():
    """Graph with services of the same type for exemplar tests."""
    graph = ArchGraph()
    graph.add_node(Node(
        id="service:UserService",
        type=NodeType.SERVICE,
        label="User Service",
        metadata={"description": "handles user CRUD"},
    ))
    graph.add_node(Node(
        id="service:AuthService",
        type=NodeType.SERVICE,
        label="Auth Service",
        metadata={"description": "handles authentication"},
    ))
    graph.add_node(Node(
        id="service:PaymentService",
        type=NodeType.SERVICE,
        label="Payment Service",
        metadata={"description": "handles payments"},
    ))
    graph.add_node(Node(
        id="table:users",
        type=NodeType.DATABASE_TABLE,
        label="users table",
        metadata={},
    ))
    graph.add_edge(Edge(source="service:UserService", target="table:users", type=EdgeType.READS))
    return graph


@pytest.fixture
def blast_graph():
    """Graph with downstream dependents for blast-radius tests."""
    graph = ArchGraph()
    graph.add_node(Node(
        id="service:CoreService",
        type=NodeType.SERVICE,
        label="Core Service",
        metadata={"description": "core service being deleted"},
    ))
    graph.add_node(Node(
        id="service:DependentA",
        type=NodeType.SERVICE,
        label="Dependent A",
        metadata={},
    ))
    graph.add_node(Node(
        id="service:DependentB",
        type=NodeType.SERVICE,
        label="Dependent B",
        metadata={},
    ))
    graph.add_node(Node(
        id="service:Unrelated",
        type=NodeType.SERVICE,
        label="Unrelated",
        metadata={},
    ))
    # DependentA and DependentB call CoreService (CoreService has downstream callers)
    graph.add_edge(Edge(source="service:DependentA", target="service:CoreService", type=EdgeType.CALLS))
    graph.add_edge(Edge(source="service:DependentB", target="service:CoreService", type=EdgeType.CALLS))
    return graph


@pytest.fixture
def cycle_graph():
    """Graph with a cycle for refactor tests."""
    graph = ArchGraph()
    graph.add_node(Node(
        id="module:alpha",
        type=NodeType.MODULE,
        label="module_alpha",
        metadata={"description": "alpha module refactor target"},
    ))
    graph.add_node(Node(
        id="module:beta",
        type=NodeType.MODULE,
        label="module_beta",
        metadata={},
    ))
    graph.add_node(Node(
        id="module:gamma",
        type=NodeType.MODULE,
        label="module_gamma",
        metadata={},
    ))
    # alpha -> beta -> gamma -> alpha (cycle)
    graph.add_edge(Edge(source="module:alpha", target="module:beta", type=EdgeType.IMPORTS))
    graph.add_edge(Edge(source="module:beta", target="module:gamma", type=EdgeType.IMPORTS))
    graph.add_edge(Edge(source="module:gamma", target="module:alpha", type=EdgeType.IMPORTS))
    return graph


# ---------------------------------------------------------------------------
# T010: Intent classification tests
# ---------------------------------------------------------------------------

class TestClassifyIntent:
    """T010 — _classify_intent() correctly identifies task intent."""

    def test_create_intent(self):
        assert _classify_intent("create a new payment service") == "create"

    def test_add_maps_to_create(self):
        assert _classify_intent("add a new endpoint for user registration") == "create"

    def test_debug_intent(self):
        assert _classify_intent("debug the timeout error") == "debug"

    def test_fix_maps_to_debug(self):
        assert _classify_intent("fix the broken authentication") == "debug"

    def test_refactor_intent(self):
        assert _classify_intent("refactor the auth module") == "refactor"

    def test_delete_intent(self):
        assert _classify_intent("delete the deprecated endpoint") == "delete"

    def test_remove_maps_to_delete(self):
        assert _classify_intent("remove the old payment handler") == "delete"

    def test_test_intent(self):
        assert _classify_intent("test the login flow") == "test"

    def test_coverage_maps_to_test(self):
        assert _classify_intent("increase coverage for the auth module") == "test"

    def test_default_modify_intent(self):
        """No specific intent keywords → default 'modify'."""
        assert _classify_intent("update the config") == "modify"

    def test_unknown_task_returns_modify(self):
        """Totally unrecognized text → default 'modify'."""
        assert _classify_intent("the database thing") == "modify"

    def test_case_insensitive(self):
        """Intent classification is case-insensitive."""
        assert _classify_intent("CREATE a new module") == "create"
        assert _classify_intent("DEBUG the error") == "debug"

    def test_priority_ordered_first_match_wins(self):
        """When multiple intent keywords appear, the first (highest-priority) match wins."""
        # "refactor" appears before "test" in priority order → should return "refactor"
        result = _classify_intent("refactor and test the module")
        # create > debug > refactor > delete > test — so refactor wins over test
        assert result == "refactor"


# ---------------------------------------------------------------------------
# T011: Intent-specific retrieval tests
# ---------------------------------------------------------------------------

class TestIntentRetrieval:
    """T011 — context_for_task() applies intent-specific retrieval strategies."""

    def test_create_intent_returns_exemplar_nodes_of_same_type(self, service_graph):
        """Create intent boosts exemplar nodes of the same type as the target."""
        result = context_for_task(
            service_graph,
            "create a new service for payments",
            max_nodes=20,
            use_embeddings=False,
        )
        # With create intent on "service", other service nodes should appear as exemplars
        returned_ids = set(result.nodes.keys())
        # Should include at least one existing service node (exemplar)
        service_ids = {"service:UserService", "service:AuthService", "service:PaymentService"}
        assert len(returned_ids & service_ids) >= 1

    def test_debug_intent_includes_upstream_dependencies(self, import_graph):
        """Debug intent returns upstream dependency chain for the target."""
        # "debug module_a" — module_a imports module_b which imports module_c
        # So upstream of module_a are its imports (b, c) and recursively
        result = context_for_task(
            import_graph,
            "debug the error in module_a",
            max_nodes=20,
            use_embeddings=False,
        )
        returned_ids = set(result.nodes.keys())
        # module:a should be in result (it's the target)
        assert "module:a" in returned_ids
        # Upstream dependencies (b is imported by a, c is imported by b) should be present
        assert "module:b" in returned_ids

    def test_delete_intent_includes_blast_radius(self, blast_graph):
        """Delete intent includes downstream dependents (blast radius) of the target."""
        result = context_for_task(
            blast_graph,
            "delete the core service",
            max_nodes=20,
            use_embeddings=False,
        )
        returned_ids = set(result.nodes.keys())
        # CoreService is the target
        assert "service:CoreService" in returned_ids
        # DependentA and DependentB call CoreService — they are downstream callers
        assert "service:DependentA" in returned_ids or "service:DependentB" in returned_ids

    def test_refactor_intent_includes_coupled_nodes(self, cycle_graph):
        """Refactor intent includes nodes sharing edges with the target."""
        result = context_for_task(
            cycle_graph,
            "refactor the alpha module",
            max_nodes=20,
            use_embeddings=False,
        )
        returned_ids = set(result.nodes.keys())
        # alpha is the target; beta and gamma are coupled (cycle)
        assert "module:alpha" in returned_ids
        # The coupled/cycle-related modules should appear
        assert "module:beta" in returned_ids or "module:gamma" in returned_ids

    def test_modify_intent_matches_default_behavior(self, service_graph):
        """Modify intent (default) returns keyword-scored results as before."""
        result = context_for_task(
            service_graph,
            "update the user service config",
            max_nodes=20,
            use_embeddings=False,
        )
        # Should return results (normal keyword scoring)
        assert isinstance(result, GraphData)
        # Nodes should have _relevance_score
        for node in result.nodes.values():
            assert "_relevance_score" in node.metadata

    def test_test_intent_includes_nodes_with_test_metadata(self, service_graph):
        """Test intent includes nodes with source: test metadata."""
        # Add a test node to the graph
        service_graph.add_node(Node(
            id="module:test_user_service",
            type=NodeType.MODULE,
            label="test_user_service",
            metadata={"source": "test", "file_path": "tests/test_user_service.py"},
        ))
        service_graph.add_edge(Edge(
            source="module:test_user_service",
            target="service:UserService",
            type=EdgeType.DEPENDS_ON,
        ))

        result = context_for_task(
            service_graph,
            "test the user service",
            max_nodes=20,
            use_embeddings=False,
        )
        returned_ids = set(result.nodes.keys())
        # Test node should be included
        assert "module:test_user_service" in returned_ids


# ---------------------------------------------------------------------------
# T012: Retrieval strategy response tests
# ---------------------------------------------------------------------------

class TestRetrievalStrategyField:
    """T012 — context_for_task() always returns _retrieval_strategy field."""

    def test_result_includes_retrieval_strategy_field(self, service_graph):
        """Every context_for_task response includes _retrieval_strategy."""
        result = context_for_task(
            service_graph,
            "update the user service",
            max_nodes=20,
            use_embeddings=False,
        )
        parsed = json.loads(result.model_dump_json())
        assert "_retrieval_strategy" in parsed

    def test_create_intent_strategy_field_value(self, service_graph):
        """_retrieval_strategy matches 'create' when task uses create keywords."""
        result = context_for_task(
            service_graph,
            "create a new service",
            max_nodes=20,
            use_embeddings=False,
        )
        parsed = json.loads(result.model_dump_json())
        assert parsed["_retrieval_strategy"] == "create"

    def test_debug_intent_strategy_field_value(self, import_graph):
        """_retrieval_strategy matches 'debug' when task uses debug keywords."""
        result = context_for_task(
            import_graph,
            "debug the error in module_a",
            max_nodes=20,
            use_embeddings=False,
        )
        parsed = json.loads(result.model_dump_json())
        assert parsed["_retrieval_strategy"] == "debug"

    def test_refactor_intent_strategy_field_value(self, cycle_graph):
        """_retrieval_strategy matches 'refactor' when task uses refactor keywords."""
        result = context_for_task(
            cycle_graph,
            "refactor the alpha module",
            max_nodes=20,
            use_embeddings=False,
        )
        parsed = json.loads(result.model_dump_json())
        assert parsed["_retrieval_strategy"] == "refactor"

    def test_delete_intent_strategy_field_value(self, blast_graph):
        """_retrieval_strategy matches 'delete' when task uses delete keywords."""
        result = context_for_task(
            blast_graph,
            "delete the core service",
            max_nodes=20,
            use_embeddings=False,
        )
        parsed = json.loads(result.model_dump_json())
        assert parsed["_retrieval_strategy"] == "delete"

    def test_modify_default_strategy_field_value(self, service_graph):
        """_retrieval_strategy is 'modify' for default/unrecognized intent."""
        result = context_for_task(
            service_graph,
            "the database thing",
            max_nodes=20,
            use_embeddings=False,
        )
        parsed = json.loads(result.model_dump_json())
        assert parsed["_retrieval_strategy"] == "modify"

    def test_ambiguous_intent_uses_priority_first_match(self, service_graph):
        """Ambiguous task (refactor and test) uses priority-ordered first match."""
        result = context_for_task(
            service_graph,
            "refactor and test the user service module",
            max_nodes=20,
            use_embeddings=False,
        )
        parsed = json.loads(result.model_dump_json())
        # refactor has higher priority than test
        assert parsed["_retrieval_strategy"] == "refactor"

    def test_retrieval_strategy_present_with_empty_graph(self):
        """Even with empty graph, _retrieval_strategy is present."""
        graph = ArchGraph()
        result = context_for_task(
            graph,
            "create a new service",
            max_nodes=20,
            use_embeddings=False,
        )
        parsed = json.loads(result.model_dump_json())
        assert "_retrieval_strategy" in parsed
        assert parsed["_retrieval_strategy"] == "create"

    def test_retrieval_strategy_preserved_with_token_budget(self, service_graph):
        """_retrieval_strategy is present even when token_budget is applied."""
        result = context_for_task(
            service_graph,
            "debug the user service",
            max_nodes=20,
            token_budget=500,
            use_embeddings=False,
        )
        parsed = json.loads(result.model_dump_json())
        assert "_retrieval_strategy" in parsed
        assert parsed["_retrieval_strategy"] == "debug"

"""Tests for cross-system contract inference in the scanner pipeline."""

from __future__ import annotations

import pytest

from codegiraffe.graph import Edge, Node
from codegiraffe.scanner import ScanResult, _infer_contract_edges
from codegiraffe.schema import EdgeType, NodeType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_node(result: ScanResult, node_id: str) -> Node | None:
    return next((n for n in result.nodes if n.id == node_id), None)


def _find_edges(result: ScanResult, *, type: str) -> list[Edge]:
    return [e for e in result.edges if e.type == type]


def _contract_nodes(result: ScanResult) -> list[Node]:
    return [n for n in result.nodes if n.type == NodeType.CONTRACT.value]


# ===========================================================================
# API contract inference
# ===========================================================================


class TestApiContractInference:
    """Tests for _infer_api_contracts (endpoint + external_api matching)."""

    def test_api_contract_inferred_from_endpoint_and_external_api(self):
        """Matching endpoint path and external_api URL creates a contract."""
        result = ScanResult(
            nodes=[
                Node(
                    id="endpoint:GET /api/users",
                    type=NodeType.ENDPOINT.value,
                    label="GET /api/users",
                ),
                Node(
                    id="external_api:https://svc.example.com/api/users",
                    type=NodeType.EXTERNAL_API.value,
                    label="https://svc.example.com/api/users",
                ),
            ],
            edges=[],
        )

        _infer_contract_edges(result)

        contracts = _contract_nodes(result)
        assert len(contracts) == 1
        c = contracts[0]
        assert c.id == "contract:api:/api/users"
        assert c.type == NodeType.CONTRACT.value
        assert c.metadata["contract_type"] == "api"
        assert c.metadata["producer"] == "endpoint:GET /api/users"
        assert c.metadata["status"] == "active"

        produces = _find_edges(result, type=EdgeType.PRODUCES.value)
        assert len(produces) == 1
        assert produces[0].source == "endpoint:GET /api/users"
        assert produces[0].target == "contract:api:/api/users"

        consumes = _find_edges(result, type=EdgeType.CONSUMES_CONTRACT.value)
        assert len(consumes) == 1
        assert consumes[0].source == "external_api:https://svc.example.com/api/users"

    def test_api_contract_not_inferred_for_unmatched_paths(self):
        """Non-matching paths produce no contract."""
        result = ScanResult(
            nodes=[
                Node(
                    id="endpoint:GET /api/users",
                    type=NodeType.ENDPOINT.value,
                    label="GET /api/users",
                ),
                Node(
                    id="external_api:https://svc.example.com/api/orders",
                    type=NodeType.EXTERNAL_API.value,
                    label="https://svc.example.com/api/orders",
                ),
            ],
            edges=[],
        )

        _infer_contract_edges(result)

        assert _contract_nodes(result) == []

    def test_api_contract_deduplication(self):
        """A contract with the same ID is not created twice."""
        result = ScanResult(
            nodes=[
                Node(
                    id="endpoint:GET /api/users",
                    type=NodeType.ENDPOINT.value,
                    label="GET /api/users",
                ),
                Node(
                    id="external_api:https://a.example.com/api/users",
                    type=NodeType.EXTERNAL_API.value,
                    label="https://a.example.com/api/users",
                ),
            ],
            edges=[],
        )

        # Run inference twice
        _infer_contract_edges(result)
        _infer_contract_edges(result)

        contracts = _contract_nodes(result)
        assert len(contracts) == 1

    def test_api_contract_multiple_consumers(self):
        """One endpoint matched by two external_api nodes creates one contract with two consumers."""
        result = ScanResult(
            nodes=[
                Node(
                    id="endpoint:POST /api/users",
                    type=NodeType.ENDPOINT.value,
                    label="POST /api/users",
                ),
                Node(
                    id="external_api:https://a.example.com/api/users",
                    type=NodeType.EXTERNAL_API.value,
                    label="https://a.example.com/api/users",
                ),
                Node(
                    id="external_api:https://b.example.com/api/users",
                    type=NodeType.EXTERNAL_API.value,
                    label="https://b.example.com/api/users",
                ),
            ],
            edges=[],
        )

        _infer_contract_edges(result)

        contracts = _contract_nodes(result)
        assert len(contracts) == 1
        assert len(contracts[0].metadata["consumers"]) == 2

        consumes = _find_edges(result, type=EdgeType.CONSUMES_CONTRACT.value)
        assert len(consumes) == 2


# ===========================================================================
# Event contract inference
# ===========================================================================


class TestEventContractInference:
    """Tests for _infer_event_contracts (matching event labels)."""

    def test_event_contract_inferred_from_matching_labels(self):
        """Two event nodes with the same label produce a contract."""
        result = ScanResult(
            nodes=[
                Node(id="event:user_created_1", type=NodeType.EVENT.value, label="user_created"),
                Node(id="event:user_created_2", type=NodeType.EVENT.value, label="user_created"),
            ],
            edges=[],
        )

        _infer_contract_edges(result)

        contracts = _contract_nodes(result)
        assert len(contracts) == 1
        c = contracts[0]
        assert c.id == "contract:event:user_created"
        assert c.metadata["contract_type"] == "event"

    def test_event_contract_not_inferred_for_single_event(self):
        """A single event node (no pair) produces no contract."""
        result = ScanResult(
            nodes=[
                Node(id="event:order_placed", type=NodeType.EVENT.value, label="order_placed"),
            ],
            edges=[],
        )

        _infer_contract_edges(result)

        assert _contract_nodes(result) == []

    def test_event_contract_identifies_publisher_via_publishes_edge(self):
        """The node targeted by a 'publishes' edge becomes the producer."""
        result = ScanResult(
            nodes=[
                Node(id="event:payment_done_1", type=NodeType.EVENT.value, label="payment_done"),
                Node(id="event:payment_done_2", type=NodeType.EVENT.value, label="payment_done"),
                Node(id="service:payments", type=NodeType.SERVICE.value, label="payments"),
            ],
            edges=[
                Edge(
                    source="service:payments",
                    target="event:payment_done_2",
                    type=EdgeType.PUBLISHES.value,
                ),
            ],
        )

        _infer_contract_edges(result)

        contracts = _contract_nodes(result)
        assert len(contracts) == 1
        assert contracts[0].metadata["producer"] == "event:payment_done_2"


# ===========================================================================
# Config contract inference
# ===========================================================================


class TestConfigContractInference:
    """Tests for _infer_config_contracts (env_var referenced by 2+ services)."""

    def test_config_contract_inferred_from_multiple_references(self):
        """An env_var with edges from two distinct nodes creates a contract."""
        result = ScanResult(
            nodes=[
                Node(id="env:DATABASE_URL", type=NodeType.ENV_VAR.value, label="DATABASE_URL"),
                Node(id="service:api", type=NodeType.SERVICE.value, label="api"),
                Node(id="service:worker", type=NodeType.SERVICE.value, label="worker"),
            ],
            edges=[
                Edge(
                    source="service:api",
                    target="env:DATABASE_URL",
                    type=EdgeType.CONFIGURES.value,
                ),
                Edge(
                    source="service:worker",
                    target="env:DATABASE_URL",
                    type=EdgeType.DEPENDS_ON.value,
                ),
            ],
        )

        _infer_contract_edges(result)

        contracts = _contract_nodes(result)
        assert len(contracts) == 1
        c = contracts[0]
        assert c.id == "contract:config:DATABASE_URL"
        assert c.metadata["contract_type"] == "config"
        # Producer is alphabetically first
        assert c.metadata["producer"] == "service:api"
        assert "service:worker" in c.metadata["consumers"]

    def test_config_contract_not_inferred_single_reference(self):
        """Only one service references the env_var -- no contract."""
        result = ScanResult(
            nodes=[
                Node(id="env:SECRET_KEY", type=NodeType.ENV_VAR.value, label="SECRET_KEY"),
                Node(id="service:api", type=NodeType.SERVICE.value, label="api"),
            ],
            edges=[
                Edge(
                    source="service:api",
                    target="env:SECRET_KEY",
                    type=EdgeType.CONFIGURES.value,
                ),
            ],
        )

        _infer_contract_edges(result)

        assert _contract_nodes(result) == []

    def test_config_contract_not_inferred_without_edges(self):
        """An env_var with no edges at all -- no contract."""
        result = ScanResult(
            nodes=[
                Node(id="env:EMPTY", type=NodeType.ENV_VAR.value, label="EMPTY"),
            ],
            edges=[],
        )

        _infer_contract_edges(result)

        assert _contract_nodes(result) == []


# ===========================================================================
# Data contract inference
# ===========================================================================


class TestDataContractInference:
    """Tests for _infer_data_contracts (database_table with distinct writers/readers)."""

    def test_data_contract_inferred_from_writer_and_reader(self):
        """A table with a writer and a different reader creates a data contract."""
        result = ScanResult(
            nodes=[
                Node(
                    id="table:users",
                    type=NodeType.DATABASE_TABLE.value,
                    label="users",
                ),
                Node(id="service:auth", type=NodeType.SERVICE.value, label="auth"),
                Node(id="service:reporting", type=NodeType.SERVICE.value, label="reporting"),
            ],
            edges=[
                Edge(
                    source="service:auth",
                    target="table:users",
                    type=EdgeType.WRITES.value,
                ),
                Edge(
                    source="service:reporting",
                    target="table:users",
                    type=EdgeType.READS.value,
                ),
            ],
        )

        _infer_contract_edges(result)

        contracts = _contract_nodes(result)
        assert len(contracts) == 1
        c = contracts[0]
        assert c.id == "contract:data:users"
        assert c.metadata["contract_type"] == "data"
        assert c.metadata["producer"] == "service:auth"
        assert "service:reporting" in c.metadata["consumers"]

    def test_data_contract_not_inferred_for_single_accessor(self):
        """Only a writer or only a reader -- no contract."""
        result = ScanResult(
            nodes=[
                Node(
                    id="table:orders",
                    type=NodeType.DATABASE_TABLE.value,
                    label="orders",
                ),
                Node(id="service:api", type=NodeType.SERVICE.value, label="api"),
            ],
            edges=[
                Edge(
                    source="service:api",
                    target="table:orders",
                    type=EdgeType.WRITES.value,
                ),
            ],
        )

        _infer_contract_edges(result)

        assert _contract_nodes(result) == []

    def test_data_contract_not_inferred_when_same_node(self):
        """Same node writes and reads -- no contract (no distinct reader)."""
        result = ScanResult(
            nodes=[
                Node(
                    id="table:sessions",
                    type=NodeType.DATABASE_TABLE.value,
                    label="sessions",
                ),
                Node(id="service:api", type=NodeType.SERVICE.value, label="api"),
            ],
            edges=[
                Edge(
                    source="service:api",
                    target="table:sessions",
                    type=EdgeType.WRITES.value,
                ),
                Edge(
                    source="service:api",
                    target="table:sessions",
                    type=EdgeType.READS.value,
                ),
            ],
        )

        _infer_contract_edges(result)

        assert _contract_nodes(result) == []


# ===========================================================================
# Orchestrator
# ===========================================================================


class TestContractInferenceOrchestrator:
    """Tests for the top-level _infer_contract_edges orchestrator."""

    def test_infer_contract_edges_all_types(self):
        """A single ScanResult with candidates for all 4 contract types."""
        result = ScanResult(
            nodes=[
                # API contract candidates
                Node(
                    id="endpoint:GET /api/items",
                    type=NodeType.ENDPOINT.value,
                    label="GET /api/items",
                ),
                Node(
                    id="external_api:https://partner.io/api/items",
                    type=NodeType.EXTERNAL_API.value,
                    label="https://partner.io/api/items",
                ),
                # Event contract candidates
                Node(id="event:item_sold_a", type=NodeType.EVENT.value, label="item_sold"),
                Node(id="event:item_sold_b", type=NodeType.EVENT.value, label="item_sold"),
                # Config contract candidates
                Node(id="env:REDIS_URL", type=NodeType.ENV_VAR.value, label="REDIS_URL"),
                Node(id="service:cache", type=NodeType.SERVICE.value, label="cache"),
                Node(id="service:queue", type=NodeType.SERVICE.value, label="queue"),
                # Data contract candidates
                Node(
                    id="table:products",
                    type=NodeType.DATABASE_TABLE.value,
                    label="products",
                ),
                Node(id="service:catalog", type=NodeType.SERVICE.value, label="catalog"),
                Node(id="service:analytics", type=NodeType.SERVICE.value, label="analytics"),
            ],
            edges=[
                # Config edges
                Edge(
                    source="service:cache",
                    target="env:REDIS_URL",
                    type=EdgeType.CONFIGURES.value,
                ),
                Edge(
                    source="service:queue",
                    target="env:REDIS_URL",
                    type=EdgeType.DEPENDS_ON.value,
                ),
                # Data edges
                Edge(
                    source="service:catalog",
                    target="table:products",
                    type=EdgeType.WRITES.value,
                ),
                Edge(
                    source="service:analytics",
                    target="table:products",
                    type=EdgeType.READS.value,
                ),
            ],
        )

        _infer_contract_edges(result)

        contracts = _contract_nodes(result)
        contract_types = {c.metadata["contract_type"] for c in contracts}
        assert contract_types == {"api", "event", "config", "data"}
        assert len(contracts) == 4

    def test_infer_contract_edges_empty(self):
        """Empty ScanResult does not crash."""
        result = ScanResult()

        _infer_contract_edges(result)

        assert _contract_nodes(result) == []
        assert result.edges == []

    def test_contract_node_metadata_structure(self):
        """Every contract node must contain contract_type, producer, consumers, status."""
        result = ScanResult(
            nodes=[
                Node(
                    id="endpoint:DELETE /api/items",
                    type=NodeType.ENDPOINT.value,
                    label="DELETE /api/items",
                ),
                Node(
                    id="external_api:https://x.io/api/items",
                    type=NodeType.EXTERNAL_API.value,
                    label="https://x.io/api/items",
                ),
            ],
            edges=[],
        )

        _infer_contract_edges(result)

        contracts = _contract_nodes(result)
        assert len(contracts) == 1
        meta = contracts[0].metadata
        assert "contract_type" in meta
        assert "producer" in meta
        assert "consumers" in meta
        assert "status" in meta
        assert meta["status"] == "active"

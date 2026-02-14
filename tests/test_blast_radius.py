"""Tests for blast radius and impact summary functionality."""

from __future__ import annotations

import pytest

from codegiraffe.graph import ArchGraph, Edge, Node
from codegiraffe.query import (
    _compute_severity,
    compute_blast_radius,
    generate_impact_summary,
)
from codegiraffe.schema import EdgeType, NodeType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def linear_chain_graph():
    """A -> B -> C -> D -> E (5 nodes, 4 edges)."""
    g = ArchGraph()
    for name in ["A", "B", "C", "D", "E"]:
        g.add_node(
            Node(
                id=f"mod:{name}",
                type=NodeType.MODULE,
                label=name,
                file_path=f"{name}.py",
            )
        )
    for s, t in [("A", "B"), ("B", "C"), ("C", "D"), ("D", "E")]:
        g.add_edge(
            Edge(source=f"mod:{s}", target=f"mod:{t}", type=EdgeType.IMPORTS)
        )
    return g


@pytest.fixture
def diamond_graph():
    """A -> B, A -> C, B -> D, C -> D."""
    g = ArchGraph()
    for name in ["A", "B", "C", "D"]:
        g.add_node(
            Node(
                id=f"mod:{name}",
                type=NodeType.MODULE,
                label=name,
                file_path=f"{name}.py",
            )
        )
    for s, t in [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")]:
        g.add_edge(
            Edge(source=f"mod:{s}", target=f"mod:{t}", type=EdgeType.IMPORTS)
        )
    return g


@pytest.fixture
def cyclic_graph():
    """A -> B -> C -> A, plus C -> D."""
    g = ArchGraph()
    for name in ["A", "B", "C", "D"]:
        g.add_node(
            Node(
                id=f"mod:{name}",
                type=NodeType.MODULE,
                label=name,
                file_path=f"{name}.py",
            )
        )
    for s, t in [("A", "B"), ("B", "C"), ("C", "A"), ("C", "D")]:
        g.add_edge(
            Edge(source=f"mod:{s}", target=f"mod:{t}", type=EdgeType.IMPORTS)
        )
    return g


# ---------------------------------------------------------------------------
# TestComputeSeverity
# ---------------------------------------------------------------------------


class TestComputeSeverity:
    """Tests for _compute_severity() helper."""

    def test_distance_one_is_direct(self):
        assert _compute_severity(1) == "direct"

    def test_distance_two_and_three_are_transitive(self):
        assert _compute_severity(2) == "transitive"
        assert _compute_severity(3) == "transitive"

    def test_distance_above_three_is_indirect(self):
        assert _compute_severity(4) == "indirect"
        assert _compute_severity(10) == "indirect"
        assert _compute_severity(100) == "indirect"


# ---------------------------------------------------------------------------
# TestComputeBlastRadius
# ---------------------------------------------------------------------------


class TestComputeBlastRadius:
    """Tests for compute_blast_radius()."""

    def test_linear_chain(self, linear_chain_graph):
        """A's blast radius covers B, C, D, E with correct distances and severities."""
        result = compute_blast_radius(linear_chain_graph, "mod:A")
        assert result["total_impact_count"] == 4
        severities = {item["node_id"]: item["severity"] for item in result["downstream"]}
        assert severities["mod:B"] == "direct"
        assert severities["mod:C"] == "transitive"
        assert severities["mod:D"] == "transitive"
        assert severities["mod:E"] == "indirect"
        # Verify distances
        distances = {item["node_id"]: item["distance"] for item in result["downstream"]}
        assert distances["mod:B"] == 1
        assert distances["mod:C"] == 2
        assert distances["mod:D"] == 3
        assert distances["mod:E"] == 4

    def test_diamond(self, diamond_graph):
        """A's blast radius is {B, C, D}; D is 2 hops."""
        result = compute_blast_radius(diamond_graph, "mod:A")
        assert result["total_impact_count"] == 3
        distances = {item["node_id"]: item["distance"] for item in result["downstream"]}
        assert distances["mod:B"] == 1
        assert distances["mod:C"] == 1
        assert distances["mod:D"] == 2

    def test_cyclic(self, cyclic_graph):
        """Handles cycles correctly and includes them in the result."""
        result = compute_blast_radius(cyclic_graph, "mod:A")
        # All of B, C, D should be reachable
        downstream_ids = {item["node_id"] for item in result["downstream"]}
        assert "mod:B" in downstream_ids
        assert "mod:C" in downstream_ids
        assert "mod:D" in downstream_ids
        # Should detect at least one cycle involving A
        assert len(result["cycles"]) >= 1
        cycle_members = set()
        for c in result["cycles"]:
            cycle_members.update(c)
        assert "mod:A" in cycle_members

    def test_isolated_node(self):
        """A node with no edges produces an empty blast radius."""
        g = ArchGraph()
        g.add_node(
            Node(id="mod:lone", type=NodeType.MODULE, label="Lone", file_path="lone.py")
        )
        result = compute_blast_radius(g, "mod:lone")
        assert result["total_impact_count"] == 0
        assert result["downstream"] == []

    def test_missing_node(self, linear_chain_graph):
        """Raises ValueError for a node that does not exist."""
        with pytest.raises(ValueError, match="not found"):
            compute_blast_radius(linear_chain_graph, "nonexistent")

    def test_with_upstream(self, linear_chain_graph):
        """include_upstream=True returns ancestor nodes."""
        result = compute_blast_radius(
            linear_chain_graph, "mod:C", include_upstream=True
        )
        assert "upstream" in result
        upstream_ids = {item["node_id"] for item in result["upstream"]}
        assert "mod:A" in upstream_ids
        assert "mod:B" in upstream_ids
        assert len(result["upstream"]) == 2

    def test_max_depth(self, linear_chain_graph):
        """max_depth limits results to that many hops."""
        result = compute_blast_radius(linear_chain_graph, "mod:A", max_depth=2)
        distances = [item["distance"] for item in result["downstream"]]
        assert all(d <= 2 for d in distances)
        downstream_ids = {item["node_id"] for item in result["downstream"]}
        assert "mod:B" in downstream_ids
        assert "mod:C" in downstream_ids
        assert "mod:D" not in downstream_ids
        assert "mod:E" not in downstream_ids

    def test_critical_paths(self, diamond_graph):
        """Hotspots are computed correctly within the impact subgraph."""
        result = compute_blast_radius(diamond_graph, "mod:A")
        # critical_paths should be a list of dicts
        assert isinstance(result["critical_paths"], list)
        for cp in result["critical_paths"]:
            assert "node_id" in cp
            assert "label" in cp
            assert "centrality" in cp


# ---------------------------------------------------------------------------
# TestGenerateImpactSummary
# ---------------------------------------------------------------------------


class TestGenerateImpactSummary:
    """Tests for generate_impact_summary()."""

    def test_has_sections(self, linear_chain_graph):
        """Output contains expected section headers."""
        blast = compute_blast_radius(linear_chain_graph, "mod:A")
        summary = generate_impact_summary(blast, linear_chain_graph)
        assert "## Impact Analysis" in summary
        assert "### Direct Dependencies" in summary

    def test_omits_empty_sections(self, linear_chain_graph):
        """Empty sections are not included in the output."""
        blast = compute_blast_radius(linear_chain_graph, "mod:A")
        summary = generate_impact_summary(blast, linear_chain_graph)
        # Linear chain has no cycles, so this section should be absent
        assert "### Circular Dependencies" not in summary
        # No upstream was requested
        assert "### Upstream Dependencies" not in summary

    def test_correct_counts(self, linear_chain_graph):
        """Section headers contain correct counts."""
        blast = compute_blast_radius(linear_chain_graph, "mod:A")
        summary = generate_impact_summary(blast, linear_chain_graph)
        assert "4 nodes affected" in summary
        assert "### Direct Dependencies (1)" in summary

    def test_formats_edge_types(self, linear_chain_graph):
        """Direct dependencies show the edge type."""
        blast = compute_blast_radius(linear_chain_graph, "mod:A")
        summary = generate_impact_summary(blast, linear_chain_graph)
        # The edge type between A and B is "imports"
        assert "imports" in summary

    def test_formats_paths(self, linear_chain_graph):
        """Transitive dependencies show the path."""
        blast = compute_blast_radius(linear_chain_graph, "mod:A")
        summary = generate_impact_summary(blast, linear_chain_graph)
        # The transitive section should show the path via ->
        assert "mod:A -> mod:B -> mod:C" in summary

    def test_recommendations(self, linear_chain_graph):
        """Has a Recommendations section when applicable."""
        blast = compute_blast_radius(linear_chain_graph, "mod:A")
        summary = generate_impact_summary(blast, linear_chain_graph)
        assert "### Recommendations" in summary


# ---------------------------------------------------------------------------
# TestBlastRadiusEdgeCases
# ---------------------------------------------------------------------------


class TestBlastRadiusEdgeCases:
    """Edge case tests for blast radius computation."""

    def test_empty_graph(self):
        """Empty ArchGraph raises ValueError for any node_id."""
        g = ArchGraph()
        with pytest.raises(ValueError, match="not found"):
            compute_blast_radius(g, "anything")

    def test_single_node(self):
        """Single node with no edges produces empty blast radius."""
        g = ArchGraph()
        g.add_node(
            Node(id="mod:only", type=NodeType.MODULE, label="Only", file_path="only.py")
        )
        result = compute_blast_radius(g, "mod:only")
        assert result["total_impact_count"] == 0
        assert result["downstream"] == []
        assert result["cycles"] == []

    def test_self_loop(self):
        """Node with a self-loop is handled gracefully."""
        g = ArchGraph()
        g.add_node(
            Node(id="mod:loop", type=NodeType.MODULE, label="Loop", file_path="loop.py")
        )
        g.add_edge(
            Edge(source="mod:loop", target="mod:loop", type=EdgeType.IMPORTS)
        )
        # Should not raise or loop infinitely
        result = compute_blast_radius(g, "mod:loop")
        assert isinstance(result, dict)
        assert result["target_node"]["id"] == "mod:loop"

    def test_very_deep_chain(self):
        """20-node chain works correctly."""
        g = ArchGraph()
        names = [f"N{i}" for i in range(20)]
        for name in names:
            g.add_node(
                Node(
                    id=f"mod:{name}",
                    type=NodeType.MODULE,
                    label=name,
                    file_path=f"{name}.py",
                )
            )
        for i in range(len(names) - 1):
            g.add_edge(
                Edge(
                    source=f"mod:{names[i]}",
                    target=f"mod:{names[i + 1]}",
                    type=EdgeType.IMPORTS,
                )
            )
        result = compute_blast_radius(g, "mod:N0")
        assert result["total_impact_count"] == 19
        # Verify last node is at distance 19 with severity "indirect"
        last = [d for d in result["downstream"] if d["node_id"] == "mod:N19"]
        assert len(last) == 1
        assert last[0]["distance"] == 19
        assert last[0]["severity"] == "indirect"

    def test_node_with_only_upstream(self, linear_chain_graph):
        """Leaf node E has no downstream but has upstream when requested."""
        result = compute_blast_radius(
            linear_chain_graph, "mod:E", include_upstream=True
        )
        assert result["total_impact_count"] == 0
        assert result["downstream"] == []
        assert "upstream" in result
        assert len(result["upstream"]) == 4  # A, B, C, D


# ---------------------------------------------------------------------------
# TestContractAwareBlastRadius
# ---------------------------------------------------------------------------


class TestContractAwareBlastRadius:
    """Tests for contract-aware blast radius computation."""

    @pytest.fixture
    def contract_graph(self):
        """Build a graph: svc:A produces contract:api consumed by svc:B and svc:C."""
        g = ArchGraph()
        g.add_node(
            Node(id="svc:A", type=NodeType.SERVICE, label="Service A", file_path="a.py")
        )
        g.add_node(
            Node(id="svc:B", type=NodeType.SERVICE, label="Service B", file_path="b.py")
        )
        g.add_node(
            Node(id="svc:C", type=NodeType.SERVICE, label="Service C", file_path="c.py")
        )
        g.add_node(
            Node(
                id="contract:api",
                type=NodeType.CONTRACT,
                label="User API Contract",
                metadata={
                    "producer": "svc:A",
                    "consumers": ["svc:B", "svc:C"],
                    "contract_type": "REST",
                },
            )
        )
        # Edge from A to the contract (produces) — optional structural edge
        g.add_edge(
            Edge(source="svc:A", target="contract:api", type=EdgeType.PRODUCES)
        )
        return g

    def test_blast_radius_includes_contract_consumers(self, contract_graph):
        """Blast radius of A should include B and C with severity 'critical'."""
        result = compute_blast_radius(contract_graph, "svc:A")
        ci = result["contract_impact"]
        consumer_ids = {item["node_id"] for item in ci}
        assert "svc:B" in consumer_ids
        assert "svc:C" in consumer_ids
        for item in ci:
            assert item["severity"] == "critical"
            assert item["distance"] == "contract"

    def test_blast_radius_no_contract_impact_without_contracts(self, linear_chain_graph):
        """Graph without contracts should have empty contract_impact."""
        result = compute_blast_radius(linear_chain_graph, "mod:A")
        assert result["contract_impact"] == []

    def test_blast_radius_contract_impact_count_in_total(self, contract_graph):
        """total_impact_count should include contract consumers."""
        result = compute_blast_radius(contract_graph, "svc:A")
        downstream_count = len(result["downstream"])
        contract_count = len(result["contract_impact"])
        assert contract_count == 2  # svc:B and svc:C
        assert result["total_impact_count"] == downstream_count + contract_count

    def test_impact_summary_includes_contract_section(self, contract_graph):
        """Markdown output should contain 'Contract Impact' section."""
        blast = compute_blast_radius(contract_graph, "svc:A")
        summary = generate_impact_summary(blast, contract_graph)
        assert "### Contract Impact" in summary
        assert "consumers at risk" in summary
        assert "Service B" in summary
        assert "Service C" in summary
        assert "REST" in summary
        assert "User API Contract" in summary
        assert "CRITICAL" in summary

    def test_impact_summary_no_contract_section_without_contracts(self, linear_chain_graph):
        """No contracts in graph means no 'Contract Impact' section."""
        blast = compute_blast_radius(linear_chain_graph, "mod:A")
        summary = generate_impact_summary(blast, linear_chain_graph)
        assert "### Contract Impact" not in summary


# ---------------------------------------------------------------------------
# Bug regression: blast radius on a contract node itself
# ---------------------------------------------------------------------------


def test_blast_radius_on_contract_node_includes_consumers():
    """Blast radius of a contract node should surface its consumers.

    Bug: calling compute_blast_radius() on a contract node returns
    total_impact_count == 0 because _compute_contract_impact only checks
    nodes whose metadata["producer"] matches node_id (the contract itself is
    never its own producer), and the BFS finds no outgoing edges since
    produces / consumes_contract edges point *to* the contract.
    """
    g = ArchGraph()

    # Producer node
    g.add_node(
        Node(
            id="mod:auth.config",
            type=NodeType.MODULE,
            label="config",
            file_path="auth/config.py",
        )
    )
    # Consumer nodes
    g.add_node(
        Node(
            id="service:UserService",
            type=NodeType.SERVICE,
            label="UserService",
            file_path="services/user.py",
        )
    )
    g.add_node(
        Node(
            id="service:PaymentService",
            type=NodeType.SERVICE,
            label="PaymentService",
            file_path="services/payment.py",
        )
    )
    # Contract node
    g.add_node(
        Node(
            id="contract:config:API_KEY",
            type=NodeType.CONTRACT,
            label="Config: API_KEY",
            metadata={
                "contract_type": "config",
                "producer": "mod:auth.config",
                "consumers": ["service:UserService", "service:PaymentService"],
                "status": "active",
                "inferred": True,
            },
        )
    )

    # Edges: producer -> contract, consumers -> contract
    g.add_edge(
        Edge(
            source="mod:auth.config",
            target="contract:config:API_KEY",
            type=EdgeType.PRODUCES,
            metadata={"inferred": True},
        )
    )
    g.add_edge(
        Edge(
            source="service:UserService",
            target="contract:config:API_KEY",
            type=EdgeType.CONSUMES_CONTRACT,
            metadata={"inferred": True},
        )
    )
    g.add_edge(
        Edge(
            source="service:PaymentService",
            target="contract:config:API_KEY",
            type=EdgeType.CONSUMES_CONTRACT,
            metadata={"inferred": True},
        )
    )

    result = compute_blast_radius(g, "contract:config:API_KEY")

    # The contract's consumers should appear somewhere in the impact
    all_impact_ids = set()
    for item in result.get("downstream", []):
        all_impact_ids.add(item["node_id"])
    for item in result.get("contract_impact", []):
        all_impact_ids.add(item["node_id"])

    assert "service:UserService" in all_impact_ids, (
        "UserService should appear in the blast radius of its contract"
    )
    assert "service:PaymentService" in all_impact_ids, (
        "PaymentService should appear in the blast radius of its contract"
    )
    assert result["total_impact_count"] > 0, (
        "Contract node blast radius must not be zero when consumers exist"
    )

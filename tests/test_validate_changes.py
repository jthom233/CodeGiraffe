"""Tests for map_files_to_nodes() and validate_changes() in query.py."""

from __future__ import annotations

import pytest

from codegiraffe.diff_parser import DiffFile
from codegiraffe.graph import ArchGraph, Edge, Node
from codegiraffe.query import map_files_to_nodes, validate_changes
from codegiraffe.schema import EdgeType, NodeType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def graph_with_modules():
    """Build a small ArchGraph with known nodes and edges.

    Structure:
    - mod:A (file_path="src/a.py") --imports--> mod:B (file_path="src/b.py")
    - mod:A --contains--> service:Foo (file_path="src/a.py")
    - mod:test_a (file_path="tests/test_a.py", source:test) --imports--> mod:A
    """
    g = ArchGraph()
    g.add_node(
        Node(
            id="mod:A",
            type=NodeType.MODULE,
            label="A",
            file_path="src/a.py",
        )
    )
    g.add_node(
        Node(
            id="mod:B",
            type=NodeType.MODULE,
            label="B",
            file_path="src/b.py",
        )
    )
    g.add_node(
        Node(
            id="service:Foo",
            type=NodeType.SERVICE,
            label="Foo",
            file_path="src/a.py",
        )
    )
    g.add_node(
        Node(
            id="mod:test_a",
            type=NodeType.MODULE,
            label="test_a",
            file_path="tests/test_a.py",
            metadata={"source": "test"},
        )
    )
    g.add_edge(
        Edge(source="mod:A", target="mod:B", type=EdgeType.IMPORTS)
    )
    g.add_edge(
        Edge(source="mod:A", target="service:Foo", type=EdgeType.CONTAINS)
    )
    g.add_edge(
        Edge(source="mod:test_a", target="mod:A", type=EdgeType.IMPORTS)
    )
    return g


@pytest.fixture
def contract_graph():
    """Build a graph with a contract: producer svc:P, consumer svc:C.

    svc:P --produces--> contract:api
    svc:C --consumes_contract--> contract:api
    """
    g = ArchGraph()
    g.add_node(
        Node(id="svc:P", type=NodeType.SERVICE, label="Producer", file_path="src/producer.py")
    )
    g.add_node(
        Node(id="svc:C", type=NodeType.SERVICE, label="Consumer", file_path="src/consumer.py")
    )
    g.add_node(
        Node(
            id="contract:api",
            type=NodeType.CONTRACT,
            label="User API",
            metadata={
                "contract_type": "api",
                "producer": "svc:P",
                "consumers": ["svc:C"],
                "status": "active",
            },
        )
    )
    g.add_edge(
        Edge(source="svc:P", target="contract:api", type=EdgeType.PRODUCES)
    )
    g.add_edge(
        Edge(source="svc:C", target="contract:api", type=EdgeType.CONSUMES_CONTRACT)
    )
    return g


# ===========================================================================
# TestMapFilesToNodes
# ===========================================================================


class TestMapFilesToNodes:
    """Tests for map_files_to_nodes()."""

    def test_exact_match(self, graph_with_modules):
        """Node with file_path='src/a.py' matched by query 'src/a.py'."""
        result = map_files_to_nodes(graph_with_modules, ["src/a.py"])
        assert "mod:A" in result["src/a.py"]

    def test_suffix_match(self):
        """Node with absolute file_path matched by relative query via suffix."""
        g = ArchGraph()
        g.add_node(
            Node(
                id="mod:foo",
                type=NodeType.MODULE,
                label="foo",
                file_path="/abs/path/src/foo.py",
            )
        )
        result = map_files_to_nodes(g, ["src/foo.py"])
        assert "mod:foo" in result["src/foo.py"]

    def test_module_id_match(self):
        """Node 'mod:codegiraffe.scanner' matches query containing 'scanner.py'."""
        g = ArchGraph()
        g.add_node(
            Node(
                id="mod:codegiraffe.scanner",
                type=NodeType.MODULE,
                label="scanner",
            )
        )
        result = map_files_to_nodes(g, ["src/codegiraffe/scanner.py"])
        assert "mod:codegiraffe.scanner" in result["src/codegiraffe/scanner.py"]

    def test_no_match(self, graph_with_modules):
        """Query for nonexistent file returns empty list."""
        result = map_files_to_nodes(graph_with_modules, ["nonexistent.py"])
        assert result["nonexistent.py"] == []

    def test_multiple_nodes_per_file(self, graph_with_modules):
        """Two nodes with same file_path both returned."""
        # mod:A and service:Foo both have file_path="src/a.py"
        result = map_files_to_nodes(graph_with_modules, ["src/a.py"])
        node_ids = result["src/a.py"]
        assert "mod:A" in node_ids
        assert "service:Foo" in node_ids

    def test_empty_graph(self):
        """Empty graph returns empty result."""
        g = ArchGraph()
        result = map_files_to_nodes(g, ["src/a.py"])
        assert result["src/a.py"] == []


# ===========================================================================
# TestValidateChanges
# ===========================================================================


class TestValidateChanges:
    """Tests for validate_changes()."""

    def test_uncovered_nodes_detected(self, graph_with_modules):
        """Change A but not B -- B appears in uncovered."""
        diff = [DiffFile(path="src/a.py", status="modified")]
        report = validate_changes(graph_with_modules, diff)
        assert "mod:B" in report.uncovered_nodes

    def test_covered_node_not_flagged(self, graph_with_modules):
        """Change both A and B -- B is covered, not uncovered."""
        diff = [
            DiffFile(path="src/a.py", status="modified"),
            DiffFile(path="src/b.py", status="modified"),
        ]
        report = validate_changes(graph_with_modules, diff)
        assert "mod:B" not in report.uncovered_nodes
        assert "mod:B" in report.covered_nodes

    def test_contract_violation(self, contract_graph):
        """Change producer but not consumer -- violation flagged."""
        diff = [DiffFile(path="src/producer.py", status="modified")]
        report = validate_changes(contract_graph, diff)
        assert len(report.contract_violations) > 0
        assert any("svc:C" in v for v in report.contract_violations)

    def test_no_contract_violation_when_consumer_changed(self, contract_graph):
        """Change both producer and consumer -- no violation."""
        diff = [
            DiffFile(path="src/producer.py", status="modified"),
            DiffFile(path="src/consumer.py", status="modified"),
        ]
        report = validate_changes(contract_graph, diff)
        assert len(report.contract_violations) == 0

    def test_empty_diff(self, graph_with_modules):
        """Empty diff_files returns empty report."""
        report = validate_changes(graph_with_modules, [])
        assert report.changed_nodes == []
        assert report.uncovered_nodes == []
        assert report.total_blast_radius == 0

    def test_files_not_in_graph(self, graph_with_modules):
        """Change a file not in graph produces empty changed_nodes."""
        diff = [DiffFile(path="src/unknown.py", status="modified")]
        report = validate_changes(graph_with_modules, diff)
        assert report.changed_nodes == []

    def test_recommendations_include_edge_type(self, graph_with_modules):
        """Uncovered nodes have recommendations mentioning edge type."""
        diff = [DiffFile(path="src/a.py", status="modified")]
        report = validate_changes(graph_with_modules, diff)
        # B is uncovered and connected via "imports" edge from A
        has_edge_mention = any("imports" in r for r in report.recommendations)
        assert has_edge_mention, f"Expected 'imports' in recommendations: {report.recommendations}"

    def test_multi_file_combined_blast_radius(self):
        """Change 2 files -- combined blast radius from both."""
        g = ArchGraph()
        # X -> Y, W -> Z (two independent chains)
        for name in ["X", "Y", "W", "Z"]:
            g.add_node(
                Node(
                    id=f"mod:{name}",
                    type=NodeType.MODULE,
                    label=name,
                    file_path=f"src/{name.lower()}.py",
                )
            )
        g.add_edge(Edge(source="mod:X", target="mod:Y", type=EdgeType.IMPORTS))
        g.add_edge(Edge(source="mod:W", target="mod:Z", type=EdgeType.IMPORTS))

        diff = [
            DiffFile(path="src/x.py", status="modified"),
            DiffFile(path="src/w.py", status="modified"),
        ]
        report = validate_changes(g, diff)
        # Both Y and Z should be in the blast radius
        assert "mod:Y" in report.uncovered_nodes
        assert "mod:Z" in report.uncovered_nodes
        assert report.total_blast_radius >= 2

"""Tests for convention mining (codegiraffe.patterns).

TDD: these tests are written before the implementation.
"""

import pytest

from codegiraffe.graph import ArchGraph, Node, Edge, GraphData
from codegiraffe.schema import NodeType, EdgeType


# ---------------------------------------------------------------------------
# Helpers — build small ArchGraphs for testing
# ---------------------------------------------------------------------------


def _make_graph(nodes, edges=None):
    g = ArchGraph()
    for n in nodes:
        g.add_node(n)
    if edges:
        for e in edges:
            g.add_edge(e)
    return g


def _endpoint_nodes():
    """4 endpoint nodes sharing a naming convention (GET /api/*)."""
    return [
        Node(
            id="endpoint:GET /api/users",
            type=NodeType.ENDPOINT,
            label="GET /api/users",
            metadata={"method": "GET", "auth": True},
        ),
        Node(
            id="endpoint:GET /api/orders",
            type=NodeType.ENDPOINT,
            label="GET /api/orders",
            metadata={"method": "GET", "auth": True},
        ),
        Node(
            id="endpoint:GET /api/products",
            type=NodeType.ENDPOINT,
            label="GET /api/products",
            metadata={"method": "GET", "auth": True},
        ),
        Node(
            id="endpoint:GET /api/reviews",
            type=NodeType.ENDPOINT,
            label="GET /api/reviews",
            metadata={"method": "GET", "auth": True},
        ),
    ]


def _service_nodes_with_outlier():
    """3 service nodes following *Service suffix, plus one outlier."""
    return [
        Node(
            id="service:UserService",
            type=NodeType.SERVICE,
            label="UserService",
            metadata={"language": "python", "version": "1.0"},
        ),
        Node(
            id="service:OrderService",
            type=NodeType.SERVICE,
            label="OrderService",
            metadata={"language": "python", "version": "1.0"},
        ),
        Node(
            id="service:PaymentService",
            type=NodeType.SERVICE,
            label="PaymentService",
            metadata={"language": "python", "version": "1.0"},
        ),
        # Outlier: different naming and missing common attributes
        Node(
            id="service:auth",
            type=NodeType.SERVICE,
            label="auth",
            metadata={},
        ),
    ]


# ---------------------------------------------------------------------------
# T023: Pattern extraction tests
# ---------------------------------------------------------------------------


class TestExtractPatterns:
    """T023 — pattern extraction from node clusters."""

    def test_extract_patterns_returns_dict(self):
        from codegiraffe.patterns import extract_patterns

        graph = _make_graph(_endpoint_nodes())
        result = extract_patterns(graph, NodeType.ENDPOINT)

        assert isinstance(result, dict)

    def test_extract_patterns_naming_pattern(self):
        from codegiraffe.patterns import extract_patterns

        graph = _make_graph(_endpoint_nodes())
        result = extract_patterns(graph, NodeType.ENDPOINT)

        assert "naming_pattern" in result
        # All IDs start with "endpoint:GET /api/" so prefix should be detected
        assert result["naming_pattern"] != ""

    def test_extract_patterns_common_attributes(self):
        from codegiraffe.patterns import extract_patterns

        graph = _make_graph(_endpoint_nodes())
        result = extract_patterns(graph, NodeType.ENDPOINT)

        assert "common_attributes" in result
        # "method" and "auth" are present in all 4 nodes (100% > 66%)
        assert "method" in result["common_attributes"]
        assert "auth" in result["common_attributes"]

    def test_extract_patterns_exemplar_present(self):
        from codegiraffe.patterns import extract_patterns

        graph = _make_graph(_endpoint_nodes())
        result = extract_patterns(graph, NodeType.ENDPOINT)

        assert "exemplar" in result
        # exemplar must be a valid node ID
        node_ids = {n.id for n in _endpoint_nodes()}
        assert result["exemplar"] in node_ids

    def test_extract_patterns_sample_size(self):
        from codegiraffe.patterns import extract_patterns

        nodes = _endpoint_nodes()
        graph = _make_graph(nodes)
        result = extract_patterns(graph, NodeType.ENDPOINT)

        assert result["sample_size"] == len(nodes)

    def test_extract_patterns_node_type_in_result(self):
        from codegiraffe.patterns import extract_patterns

        graph = _make_graph(_endpoint_nodes())
        result = extract_patterns(graph, NodeType.ENDPOINT)

        assert result["node_type"] == NodeType.ENDPOINT

    def test_outlier_flagged_as_anti_pattern(self):
        """Node deviating from >50% of conventions is flagged as outlier."""
        from codegiraffe.patterns import extract_patterns

        graph = _make_graph(_service_nodes_with_outlier())
        result = extract_patterns(graph, NodeType.SERVICE)

        assert "outliers" in result
        # "service:auth" is missing language/version metadata that 75% of nodes have
        # and doesn't match the *Service suffix that 75% of nodes follow
        assert "service:auth" in result["outliers"]

    def test_well_formed_nodes_not_outliers(self):
        """Nodes conforming to the pattern should not be listed as outliers."""
        from codegiraffe.patterns import extract_patterns

        graph = _make_graph(_service_nodes_with_outlier())
        result = extract_patterns(graph, NodeType.SERVICE)

        # The 3 conforming service nodes should NOT be outliers
        assert "service:UserService" not in result["outliers"]
        assert "service:OrderService" not in result["outliers"]
        assert "service:PaymentService" not in result["outliers"]


# ---------------------------------------------------------------------------
# T024: Minimum cluster tests
# ---------------------------------------------------------------------------


class TestMinimumCluster:
    """T024 — minimum cluster size enforcement."""

    def test_fewer_than_3_returns_message(self):
        from codegiraffe.patterns import extract_patterns

        nodes = [
            Node(id="service:A", type=NodeType.SERVICE, label="A"),
            Node(id="service:B", type=NodeType.SERVICE, label="B"),
        ]
        graph = _make_graph(nodes)
        result = extract_patterns(graph, NodeType.SERVICE)

        assert "message" in result
        assert "insufficient" in result["message"].lower()

    def test_fewer_than_3_returns_sample_size(self):
        from codegiraffe.patterns import extract_patterns

        nodes = [
            Node(id="service:A", type=NodeType.SERVICE, label="A"),
            Node(id="service:B", type=NodeType.SERVICE, label="B"),
        ]
        graph = _make_graph(nodes)
        result = extract_patterns(graph, NodeType.SERVICE)

        assert result["sample_size"] == 2

    def test_fewer_than_3_no_exception(self):
        """Should return a message dict, not raise."""
        from codegiraffe.patterns import extract_patterns

        nodes = [Node(id="service:A", type=NodeType.SERVICE, label="A")]
        graph = _make_graph(nodes)
        result = extract_patterns(graph, NodeType.SERVICE)

        assert isinstance(result, dict)
        assert "message" in result

    def test_exactly_3_nodes_works(self):
        """3 nodes is the minimum — should return full pattern result."""
        from codegiraffe.patterns import extract_patterns

        nodes = [
            Node(
                id="service:UserService",
                type=NodeType.SERVICE,
                label="UserService",
                metadata={"lang": "python"},
            ),
            Node(
                id="service:OrderService",
                type=NodeType.SERVICE,
                label="OrderService",
                metadata={"lang": "python"},
            ),
            Node(
                id="service:PayService",
                type=NodeType.SERVICE,
                label="PayService",
                metadata={"lang": "python"},
            ),
        ]
        graph = _make_graph(nodes)
        result = extract_patterns(graph, NodeType.SERVICE)

        assert "message" not in result
        assert result["sample_size"] == 3
        assert "naming_pattern" in result

    def test_no_nodes_of_type_returns_message(self):
        """Node type with no instances returns message dict."""
        from codegiraffe.patterns import extract_patterns

        # Graph has only endpoints, no queues
        graph = _make_graph(_endpoint_nodes())
        result = extract_patterns(graph, NodeType.QUEUE)

        assert "message" in result
        assert result["sample_size"] == 0

    def test_custom_min_cluster(self):
        """Custom min_cluster=5 with only 4 nodes should return insufficient."""
        from codegiraffe.patterns import extract_patterns

        graph = _make_graph(_endpoint_nodes())  # 4 nodes
        result = extract_patterns(graph, NodeType.ENDPOINT, min_cluster=5)

        assert "message" in result
        assert result["sample_size"] == 4


# ---------------------------------------------------------------------------
# T025: Pattern similarity and contract tests
# ---------------------------------------------------------------------------


class TestNamingPattern:
    """T025 — _extract_naming_pattern internals."""

    def test_common_prefix_detected(self):
        from codegiraffe.patterns import _extract_naming_pattern

        node_ids = [
            "service:UserService",
            "service:OrderService",
            "service:PaymentService",
        ]
        pattern = _extract_naming_pattern(node_ids)

        # All start with "service:" so that prefix should be in pattern
        assert "service:" in pattern

    def test_common_suffix_detected(self):
        from codegiraffe.patterns import _extract_naming_pattern

        node_ids = [
            "service:UserService",
            "service:OrderService",
            "service:PaymentService",
        ]
        pattern = _extract_naming_pattern(node_ids)

        # All end with "Service" so suffix should appear
        assert "Service" in pattern

    def test_no_common_pattern_returns_string(self):
        from codegiraffe.patterns import _extract_naming_pattern

        node_ids = ["aaa:xyz", "bbb:abc", "ccc:def"]
        pattern = _extract_naming_pattern(node_ids)

        # Should return some string even if no common pattern
        assert isinstance(pattern, str)

    def test_single_node_id(self):
        from codegiraffe.patterns import _extract_naming_pattern

        pattern = _extract_naming_pattern(["service:FooService"])
        assert isinstance(pattern, str)
        # With single item, the whole thing is the "pattern"
        assert len(pattern) > 0

    def test_empty_list_returns_empty(self):
        from codegiraffe.patterns import _extract_naming_pattern

        pattern = _extract_naming_pattern([])
        assert isinstance(pattern, str)


class TestCommonAttributes:
    """T025 — common_attributes populated from >66% threshold."""

    def test_common_attributes_threshold(self):
        from codegiraffe.patterns import extract_patterns

        # 4 nodes: 3 have "version" (75%), 1 does not
        nodes = [
            Node(
                id="service:A",
                type=NodeType.SERVICE,
                label="A",
                metadata={"version": "1.0", "env": "prod"},
            ),
            Node(
                id="service:B",
                type=NodeType.SERVICE,
                label="B",
                metadata={"version": "1.0", "env": "prod"},
            ),
            Node(
                id="service:C",
                type=NodeType.SERVICE,
                label="C",
                metadata={"version": "2.0", "env": "prod"},
            ),
            Node(
                id="service:D",
                type=NodeType.SERVICE,
                label="D",
                metadata={"env": "prod"},  # missing "version"
            ),
        ]
        graph = _make_graph(nodes)
        result = extract_patterns(graph, NodeType.SERVICE)

        # "env" present in 100% → should be in common_attributes
        assert "env" in result["common_attributes"]
        # "version" present in 75% (>66%) → should be in common_attributes
        assert "version" in result["common_attributes"]

    def test_rare_attribute_not_in_common(self):
        from codegiraffe.patterns import extract_patterns

        # Only 1 out of 4 nodes has "rare_attr" (25% < 66%)
        nodes = [
            Node(id="service:A", type=NodeType.SERVICE, label="A", metadata={"rare_attr": "x"}),
            Node(id="service:B", type=NodeType.SERVICE, label="B", metadata={}),
            Node(id="service:C", type=NodeType.SERVICE, label="C", metadata={}),
            Node(id="service:D", type=NodeType.SERVICE, label="D", metadata={}),
        ]
        graph = _make_graph(nodes)
        result = extract_patterns(graph, NodeType.SERVICE)

        assert "rare_attr" not in result["common_attributes"]

    def test_fifty_fifty_split_reported_as_alternatives(self):
        """50/50 split attributes are not reported as common (below 66% threshold)."""
        from codegiraffe.patterns import extract_patterns

        nodes = [
            Node(id="service:A", type=NodeType.SERVICE, label="A", metadata={"split_attr": "yes"}),
            Node(id="service:B", type=NodeType.SERVICE, label="B", metadata={"split_attr": "yes"}),
            Node(id="service:C", type=NodeType.SERVICE, label="C", metadata={}),
            Node(id="service:D", type=NodeType.SERVICE, label="D", metadata={}),
        ]
        graph = _make_graph(nodes)
        result = extract_patterns(graph, NodeType.SERVICE)

        # 50% is below 66% threshold → should NOT be in common_attributes
        assert "split_attr" not in result["common_attributes"]


class TestPatternsToolContract:
    """T025 — contract test for codegiraffe_patterns MCP tool structure."""

    def test_tool_accepts_project_path_and_node_type(self, tmp_path):
        """codegiraffe_patterns should accept project_path and node_type params."""
        from codegiraffe.server import codegiraffe_patterns
        import inspect

        sig = inspect.signature(codegiraffe_patterns)
        params = sig.parameters

        assert "project_path" in params
        assert "node_type" in params

    def test_tool_has_optional_min_cluster(self):
        """codegiraffe_patterns should have optional min_cluster param."""
        from codegiraffe.server import codegiraffe_patterns
        import inspect

        sig = inspect.signature(codegiraffe_patterns)
        params = sig.parameters

        assert "min_cluster" in params
        # Verify it has a default value
        assert params["min_cluster"].default == 3

    def test_tool_returns_string(self, tmp_path):
        """codegiraffe_patterns returns a string (MCP tools return str)."""
        import json
        from unittest.mock import patch
        from codegiraffe.patterns import extract_patterns
        from codegiraffe.server import codegiraffe_patterns
        from codegiraffe.graph import ArchGraph, Node
        from codegiraffe.schema import NodeType

        # Build a graph with 4 service nodes
        graph = ArchGraph()
        for i, name in enumerate(["UserService", "OrderService", "PayService", "AuthService"]):
            graph.add_node(
                Node(
                    id=f"service:{name}",
                    type=NodeType.SERVICE,
                    label=name,
                    metadata={"lang": "python"},
                )
            )

        with patch("codegiraffe.server._ensure_graph", return_value=graph):
            result = codegiraffe_patterns(
                project_path=str(tmp_path),
                node_type=NodeType.SERVICE,
            )

        assert isinstance(result, str)
        assert len(result) > 0

    def test_tool_result_contains_pattern_info(self, tmp_path):
        """The string result should contain naming_pattern or sample_size info."""
        from unittest.mock import patch
        from codegiraffe.server import codegiraffe_patterns
        from codegiraffe.graph import ArchGraph, Node
        from codegiraffe.schema import NodeType

        graph = ArchGraph()
        for name in ["UserService", "OrderService", "PayService", "AuthService"]:
            graph.add_node(
                Node(
                    id=f"service:{name}",
                    type=NodeType.SERVICE,
                    label=name,
                    metadata={"lang": "python"},
                )
            )

        with patch("codegiraffe.server._ensure_graph", return_value=graph):
            result = codegiraffe_patterns(
                project_path=str(tmp_path),
                node_type=NodeType.SERVICE,
            )

        # Result should be readable markdown with pattern info
        assert "service" in result.lower() or "pattern" in result.lower() or "4" in result

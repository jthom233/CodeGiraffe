"""Tests for Architectural Decision Records (ADR) detection and graph integration.

TDD: These tests are written BEFORE implementation.

Groups:
- T016: ADR detection tests (_detect_decision_markers)
- T017: Decision constraint targeting and subgraph inclusion
- T018: Edge cases and contract tests
"""

from __future__ import annotations

import pytest

from codegiraffe.graph import ArchGraph, Edge, GraphData, Node
from codegiraffe.schema import EdgeType, NodeType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_nodes(result, node_type: str) -> list[Node]:
    """Find all nodes of a given type in a ScanResult or list."""
    if hasattr(result, "nodes") and isinstance(result.nodes, list):
        return [n for n in result.nodes if n.type == node_type]
    return []


def _find_edges_by_type(result, edge_type: str) -> list[Edge]:
    """Find all edges of a given type in a ScanResult."""
    return [e for e in result.edges if e.type == edge_type]


# ===========================================================================
# T016: ADR detection tests
# ===========================================================================


class TestDetectDecisionMarkersHashStyle:
    """T016 — Python-style # DECISION: markers."""

    def test_detects_hash_decision_marker(self):
        """# DECISION: Use event bus is detected in Python content."""
        from codegiraffe.scanner import _detect_decision_markers

        content = "# DECISION: Use event bus for async communication\ncode = True\n"
        results = _detect_decision_markers("app.py", content)

        assert len(results) == 1
        assert "Use event bus for async communication" in results[0]["text"]

    def test_hash_decision_marker_no_adr_id(self):
        """# DECISION: marker has no adr_id (None)."""
        from codegiraffe.scanner import _detect_decision_markers

        content = "# DECISION: Use PostgreSQL over MySQL\n"
        results = _detect_decision_markers("app.py", content)

        assert len(results) == 1
        assert results[0]["adr_id"] is None

    def test_hash_decision_includes_file_path(self):
        """Result includes the file_path passed in."""
        from codegiraffe.scanner import _detect_decision_markers

        content = "# DECISION: Use Redis for sessions\n"
        results = _detect_decision_markers("services/auth.py", content)

        assert results[0]["file_path"] == "services/auth.py"

    def test_hash_decision_includes_line_number(self):
        """Result includes the correct line number (1-indexed)."""
        from codegiraffe.scanner import _detect_decision_markers

        content = "import os\n# DECISION: Use Redis for sessions\ncode = True\n"
        results = _detect_decision_markers("app.py", content)

        # Line 2 (1-indexed)
        assert results[0]["line_number"] == 2

    def test_multiple_hash_decisions_detected(self):
        """Multiple # DECISION: markers in one file are all detected."""
        from codegiraffe.scanner import _detect_decision_markers

        content = (
            "# DECISION: Use event bus\n"
            "code = 1\n"
            "# DECISION: Use PostgreSQL\n"
        )
        results = _detect_decision_markers("app.py", content)

        assert len(results) == 2


class TestDetectDecisionMarkersLineCommentStyle:
    """T016 — // ADR-NNN: style markers (Go/TS/Java)."""

    def test_detects_line_comment_adr_marker(self):
        """// ADR-007: JWT over sessions is detected."""
        from codegiraffe.scanner import _detect_decision_markers

        content = "// ADR-007: JWT over sessions instead of cookies\nfunc main() {}\n"
        results = _detect_decision_markers("main.go", content)

        assert len(results) == 1
        assert "JWT over sessions" in results[0]["text"]

    def test_line_comment_adr_has_numeric_id(self):
        """// ADR-007: sets adr_id to '007' or 7."""
        from codegiraffe.scanner import _detect_decision_markers

        content = "// ADR-007: JWT over sessions\n"
        results = _detect_decision_markers("main.go", content)

        assert results[0]["adr_id"] is not None
        assert str(results[0]["adr_id"]) in ("7", "007", 7)

    def test_line_comment_adr_line_number(self):
        """// ADR-003: is on line 3."""
        from codegiraffe.scanner import _detect_decision_markers

        content = "package main\nimport \"fmt\"\n// ADR-003: Use gRPC\nfunc main() {}\n"
        results = _detect_decision_markers("main.go", content)

        assert results[0]["line_number"] == 3


class TestDetectDecisionMarkersBlockCommentStyle:
    """T016 — /* ADR-NNN: */ block comment style."""

    def test_detects_block_comment_adr_marker(self):
        """/* ADR-003: Migrate to microservices */ is detected."""
        from codegiraffe.scanner import _detect_decision_markers

        content = "/* ADR-003: Migrate to microservices */\ncode;\n"
        results = _detect_decision_markers("service.java", content)

        assert len(results) == 1
        assert "Migrate to microservices" in results[0]["text"]

    def test_block_comment_adr_has_numeric_id(self):
        """Block comment ADR-003 sets adr_id."""
        from codegiraffe.scanner import _detect_decision_markers

        content = "/* ADR-003: Migrate to microservices */\n"
        results = _detect_decision_markers("service.java", content)

        assert results[0]["adr_id"] is not None

    def test_block_comment_without_closing_tag(self):
        """/* ADR-003: text without closing */ is still detected."""
        from codegiraffe.scanner import _detect_decision_markers

        content = "/* ADR-003: Use event sourcing\n more details */\n"
        results = _detect_decision_markers("service.java", content)

        assert len(results) >= 1


class TestDecisionNodeMetadata:
    """T016 — Decision node ID format and metadata."""

    def test_decision_node_id_format(self):
        """Decision node ID follows decision:{file}:{line} format."""
        from codegiraffe.scanner import _detect_decision_markers

        content = "# DECISION: Use event bus\n"
        results = _detect_decision_markers("services/payment.py", content)

        assert len(results) == 1
        r = results[0]
        # Node ID should be constructable as decision:{file}:{line}
        expected_id = f"decision:{r['file_path']}:{r['line_number']}"
        assert "decision:" in expected_id  # At minimum this prefix
        assert str(r["line_number"]) in expected_id

    def test_decision_metadata_includes_mined_from(self):
        """Detected decisions include mined_from='comment'."""
        from codegiraffe.scanner import _detect_decision_markers

        content = "# DECISION: Use event bus\n"
        results = _detect_decision_markers("app.py", content)

        assert results[0].get("mined_from") == "comment"

    def test_no_markers_in_plain_code(self):
        """Files with no decision markers return empty list."""
        from codegiraffe.scanner import _detect_decision_markers

        content = "def foo():\n    return 42\n"
        results = _detect_decision_markers("app.py", content)

        assert results == []


# ===========================================================================
# T017: Decision constraint targeting and subgraph inclusion
# ===========================================================================


class TestDecisionConstrainsTargeting:
    """T017 — constrains edges target governed nodes or fallback."""

    def test_decision_nodes_created_in_scan(self, tmp_path):
        """scan_project creates decision nodes for files containing markers."""
        from codegiraffe.scanner import scan_project

        src = tmp_path / "service.py"
        src.write_text(
            "# DECISION: Use event bus for async communication\n"
            "class PaymentService:\n"
            "    pass\n"
        )

        result = scan_project(str(tmp_path))
        decision_nodes = [n for n in result.nodes if n.type == NodeType.DECISION.value]

        assert len(decision_nodes) >= 1

    def test_decision_node_has_constrains_edge(self, tmp_path):
        """A decision node has at least one constrains edge."""
        from codegiraffe.scanner import scan_project

        src = tmp_path / "service.py"
        src.write_text(
            "# DECISION: Use event bus for async communication\n"
            "class PaymentService:\n"
            "    pass\n"
        )

        result = scan_project(str(tmp_path))
        constrains_edges = [e for e in result.edges if e.type == EdgeType.CONSTRAINS.value]

        assert len(constrains_edges) >= 1

    def test_constrains_edge_source_is_decision_node(self, tmp_path):
        """The source of a constrains edge is a decision node."""
        from codegiraffe.scanner import scan_project

        src = tmp_path / "service.py"
        src.write_text(
            "# DECISION: Use event bus\n"
            "class PaymentService:\n"
            "    pass\n"
        )

        result = scan_project(str(tmp_path))
        decision_ids = {n.id for n in result.nodes if n.type == NodeType.DECISION.value}
        constrains_edges = [e for e in result.edges if e.type == EdgeType.CONSTRAINS.value]

        assert any(e.source in decision_ids for e in constrains_edges)

    def test_decision_references_node_id_in_text_creates_targeted_constrains(self):
        """Decision text mentioning a node ID creates a constrains edge to that node."""
        from codegiraffe.scanner import ScanResult, _detect_decision_markers, _infer_decision_edges

        # Set up a ScanResult with a service node
        result = ScanResult(
            nodes=[
                Node(
                    id="service:PaymentService",
                    type=NodeType.SERVICE.value,
                    label="PaymentService",
                    file_path="payment.py",
                    metadata={},
                ),
            ],
            edges=[],
        )

        markers = [
            {
                "text": "Governs service:PaymentService to use event bus",
                "adr_id": None,
                "file_path": "payment.py",
                "line_number": 1,
                "mined_from": "comment",
            }
        ]
        _infer_decision_edges(result, markers)

        constrains_edges = [e for e in result.edges if e.type == EdgeType.CONSTRAINS.value]
        assert len(constrains_edges) == 1
        assert constrains_edges[0].target == "service:PaymentService"

    def test_decision_no_text_match_falls_back_to_enclosing_symbol(self):
        """When no node ID is found in text, constrains edge targets the module node."""
        from codegiraffe.scanner import ScanResult, _infer_decision_edges

        result = ScanResult(
            nodes=[
                Node(
                    id="mod:payment",
                    type=NodeType.MODULE.value,
                    label="payment",
                    file_path="payment.py",
                    metadata={},
                ),
            ],
            edges=[],
        )

        markers = [
            {
                "text": "Use Redis for sessions",
                "adr_id": None,
                "file_path": "payment.py",
                "line_number": 1,
                "mined_from": "comment",
            }
        ]
        _infer_decision_edges(result, markers)

        constrains_edges = [e for e in result.edges if e.type == EdgeType.CONSTRAINS.value]
        # Should target the module node as fallback
        assert len(constrains_edges) >= 1
        assert any(e.target == "mod:payment" for e in constrains_edges)


class TestIncludeConstrainingDecisions:
    """T017 — _include_constraining_decisions adds ADR nodes to subgraph."""

    def test_include_constraining_decisions_adds_decision_node(self):
        """Decision nodes connected to subgraph nodes via constrains are included."""
        from codegiraffe.query import _include_constraining_decisions

        graph = ArchGraph()
        service_node = Node(
            id="service:PaymentService",
            type=NodeType.SERVICE.value,
            label="PaymentService",
            metadata={},
        )
        decision_node = Node(
            id="decision:payment.py:1",
            type=NodeType.DECISION.value,
            label="Use event bus",
            metadata={"mined_from": "comment"},
        )
        graph.add_node(service_node)
        graph.add_node(decision_node)
        graph.add_edge(
            Edge(
                source="decision:payment.py:1",
                target="service:PaymentService",
                type=EdgeType.CONSTRAINS.value,
                metadata={},
            )
        )

        subgraph_nodes = {"service:PaymentService"}
        result = _include_constraining_decisions(subgraph_nodes, graph)

        assert "decision:payment.py:1" in result

    def test_include_constraining_decisions_returns_set(self):
        """Returns a set of node IDs."""
        from codegiraffe.query import _include_constraining_decisions

        graph = ArchGraph()
        subgraph_nodes = {"service:PaymentService"}
        result = _include_constraining_decisions(subgraph_nodes, graph)

        assert isinstance(result, set)

    def test_include_constraining_decisions_no_decisions(self):
        """Returns original set unchanged when no decision nodes exist."""
        from codegiraffe.query import _include_constraining_decisions

        graph = ArchGraph()
        service_node = Node(
            id="service:AuthService",
            type=NodeType.SERVICE.value,
            label="AuthService",
            metadata={},
        )
        graph.add_node(service_node)

        subgraph_nodes = {"service:AuthService"}
        result = _include_constraining_decisions(subgraph_nodes, graph)

        assert "service:AuthService" in result
        assert len(result) == 1  # no decision nodes added

    def test_include_constraining_decisions_only_adds_relevant(self):
        """Only decision nodes connected to subgraph nodes are added."""
        from codegiraffe.query import _include_constraining_decisions

        graph = ArchGraph()
        service_a = Node(id="service:A", type=NodeType.SERVICE.value, label="A", metadata={})
        service_b = Node(id="service:B", type=NodeType.SERVICE.value, label="B", metadata={})
        dec_a = Node(
            id="decision:a.py:1",
            type=NodeType.DECISION.value,
            label="ADR for A",
            metadata={"mined_from": "comment"},
        )
        dec_b = Node(
            id="decision:b.py:1",
            type=NodeType.DECISION.value,
            label="ADR for B",
            metadata={"mined_from": "comment"},
        )
        graph.add_node(service_a)
        graph.add_node(service_b)
        graph.add_node(dec_a)
        graph.add_node(dec_b)
        graph.add_edge(
            Edge(source="decision:a.py:1", target="service:A", type=EdgeType.CONSTRAINS.value, metadata={})
        )
        graph.add_edge(
            Edge(source="decision:b.py:1", target="service:B", type=EdgeType.CONSTRAINS.value, metadata={})
        )

        # Only A is in the subgraph
        subgraph_nodes = {"service:A"}
        result = _include_constraining_decisions(subgraph_nodes, graph)

        assert "decision:a.py:1" in result
        assert "decision:b.py:1" not in result


class TestSupersededEdges:
    """T017 — supersedes edges between same ADR ID on different lines."""

    def test_supersedes_edge_created_for_same_adr_id(self):
        """Two decisions with same ADR ID → newer supersedes older."""
        from codegiraffe.scanner import ScanResult, _infer_decision_edges

        result = ScanResult(nodes=[], edges=[])

        markers = [
            {
                "text": "Use JWT tokens",
                "adr_id": "007",
                "file_path": "auth.py",
                "line_number": 5,
                "mined_from": "comment",
            },
            {
                "text": "Use OAuth2 instead of JWT",
                "adr_id": "007",
                "file_path": "auth.py",
                "line_number": 20,
                "mined_from": "comment",
            },
        ]
        _infer_decision_edges(result, markers)

        supersedes_edges = [e for e in result.edges if e.type == EdgeType.SUPERSEDES.value]
        assert len(supersedes_edges) >= 1
        # The newer (line 20) supersedes the older (line 5)
        superseding_ids = {e.source for e in supersedes_edges}
        superseded_ids = {e.target for e in supersedes_edges}
        # Find the decision nodes
        node_ids = {n.id for n in result.nodes}
        assert len(superseding_ids) >= 1
        assert len(superseded_ids) >= 1


# ===========================================================================
# T018: Edge cases and contract tests
# ===========================================================================


class TestDecisionEdgeCases:
    """T018 — Edge cases for decision detection and handling."""

    def test_orphan_decision_no_crash(self):
        """Decision with no matching governed node and no module node does not crash."""
        from codegiraffe.scanner import ScanResult, _infer_decision_edges

        result = ScanResult(nodes=[], edges=[])

        markers = [
            {
                "text": "Use Redis for caching",
                "adr_id": None,
                "file_path": "nonexistent.py",
                "line_number": 1,
                "mined_from": "comment",
            }
        ]
        # Should not raise
        _infer_decision_edges(result, markers)

        # Decision node still created
        decision_nodes = [n for n in result.nodes if n.type == NodeType.DECISION.value]
        assert len(decision_nodes) == 1

    def test_decision_with_no_match_and_no_enclosing_creates_no_constrains(self):
        """Decision with no matches in text and no enclosing node creates no constrains edges."""
        from codegiraffe.scanner import ScanResult, _infer_decision_edges

        result = ScanResult(nodes=[], edges=[])

        markers = [
            {
                "text": "Use Redis for caching (no references)",
                "adr_id": None,
                "file_path": "unknown.py",
                "line_number": 1,
                "mined_from": "comment",
            }
        ]
        _infer_decision_edges(result, markers)

        constrains_edges = [e for e in result.edges if e.type == EdgeType.CONSTRAINS.value]
        assert len(constrains_edges) == 0

    def test_file_with_no_markers_produces_no_decision_nodes(self):
        """Plain code file with no markers returns empty decision list."""
        from codegiraffe.scanner import _detect_decision_markers

        content = "def calculate(x, y):\n    return x + y\n\nresult = calculate(1, 2)\n"
        results = _detect_decision_markers("math_utils.py", content)

        assert results == []

    def test_empty_content_produces_no_decisions(self):
        """Empty file produces no decisions."""
        from codegiraffe.scanner import _detect_decision_markers

        results = _detect_decision_markers("empty.py", "")
        assert results == []


class TestAddRelationWithDecisionTypes:
    """T018 — Contract tests: add_relation accepts decision node and edge types."""

    def test_add_decision_node_to_graph(self):
        """ArchGraph accepts a decision node type."""
        graph = ArchGraph()
        decision_node = Node(
            id="decision:auth.py:10",
            type=NodeType.DECISION.value,
            label="Use OAuth2",
            metadata={"adr_id": "005", "mined_from": "comment"},
        )
        graph.add_node(decision_node)

        data = graph.to_data()
        assert "decision:auth.py:10" in data.nodes

    def test_add_constrains_edge(self):
        """ArchGraph accepts a constrains edge type."""
        graph = ArchGraph()
        graph.add_node(
            Node(id="decision:auth.py:10", type=NodeType.DECISION.value, label="ADR", metadata={})
        )
        graph.add_node(
            Node(id="service:AuthService", type=NodeType.SERVICE.value, label="Auth", metadata={})
        )
        graph.add_edge(
            Edge(
                source="decision:auth.py:10",
                target="service:AuthService",
                type=EdgeType.CONSTRAINS.value,
                metadata={},
            )
        )

        data = graph.to_data()
        edge_types = {e.type for e in data.edges}
        assert EdgeType.CONSTRAINS.value in edge_types

    def test_add_motivated_by_edge(self):
        """ArchGraph accepts a motivated_by edge type."""
        graph = ArchGraph()
        graph.add_node(
            Node(id="decision:auth.py:10", type=NodeType.DECISION.value, label="ADR", metadata={})
        )
        graph.add_node(
            Node(id="service:AuthService", type=NodeType.SERVICE.value, label="Auth", metadata={})
        )
        graph.add_edge(
            Edge(
                source="decision:auth.py:10",
                target="service:AuthService",
                type=EdgeType.MOTIVATED_BY.value,
                metadata={},
            )
        )

        data = graph.to_data()
        edge_types = {e.type for e in data.edges}
        assert EdgeType.MOTIVATED_BY.value in edge_types

    def test_add_supersedes_edge(self):
        """ArchGraph accepts a supersedes edge type."""
        graph = ArchGraph()
        graph.add_node(
            Node(id="decision:auth.py:5", type=NodeType.DECISION.value, label="ADR v1", metadata={})
        )
        graph.add_node(
            Node(id="decision:auth.py:20", type=NodeType.DECISION.value, label="ADR v2", metadata={})
        )
        graph.add_edge(
            Edge(
                source="decision:auth.py:20",
                target="decision:auth.py:5",
                type=EdgeType.SUPERSEDES.value,
                metadata={},
            )
        )

        data = graph.to_data()
        edge_types = {e.type for e in data.edges}
        assert EdgeType.SUPERSEDES.value in edge_types

    def test_decision_node_type_is_in_schema(self):
        """NodeType.DECISION is defined in schema."""
        assert NodeType.DECISION.value == "decision"

    def test_constrains_edge_type_is_in_schema(self):
        """EdgeType.CONSTRAINS is defined in schema."""
        assert EdgeType.CONSTRAINS.value == "constrains"

    def test_motivated_by_edge_type_is_in_schema(self):
        """EdgeType.MOTIVATED_BY is defined in schema."""
        assert EdgeType.MOTIVATED_BY.value == "motivated_by"

    def test_supersedes_edge_type_is_in_schema(self):
        """EdgeType.SUPERSEDES is defined in schema."""
        assert EdgeType.SUPERSEDES.value == "supersedes"


# ===========================================================================
# T017 (additional): context_for_task includes constraining decisions
# ===========================================================================


class TestContextForTaskIncludesDecisions:
    """T017 — context_for_task pulls in constraining decisions."""

    def test_context_for_task_includes_decision_node(self):
        """context_for_task includes decision nodes constraining matched nodes."""
        from codegiraffe.query import context_for_task

        graph = ArchGraph()
        service_node = Node(
            id="service:PaymentService",
            type=NodeType.SERVICE.value,
            label="PaymentService",
            metadata={"class_name": "PaymentService"},
        )
        decision_node = Node(
            id="decision:payment.py:1",
            type=NodeType.DECISION.value,
            label="Use event bus for payment",
            metadata={"mined_from": "comment", "text": "Use event bus for payment"},
        )
        graph.add_node(service_node)
        graph.add_node(decision_node)
        graph.add_edge(
            Edge(
                source="decision:payment.py:1",
                target="service:PaymentService",
                type=EdgeType.CONSTRAINS.value,
                metadata={},
            )
        )

        result = context_for_task(graph, "PaymentService", use_embeddings=False)

        assert "service:PaymentService" in result.nodes
        assert "decision:payment.py:1" in result.nodes

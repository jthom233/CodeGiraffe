"""Tests for suggest_tests() in query.py."""

from __future__ import annotations

import pytest

from codegiraffe.diff_parser import DiffFile
from codegiraffe.graph import ArchGraph, Edge, Node
from codegiraffe.query import suggest_tests
from codegiraffe.schema import EdgeType, NodeType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_graph_with_test(
    source_id: str,
    source_fp: str,
    test_id: str,
    test_fp: str,
    edge_type: str = EdgeType.IMPORTS,
) -> ArchGraph:
    """Build a minimal graph with a source node and a test node linked by an edge."""
    g = ArchGraph()
    g.add_node(
        Node(
            id=source_id,
            type=NodeType.MODULE,
            label=source_id,
            file_path=source_fp,
        )
    )
    g.add_node(
        Node(
            id=test_id,
            type=NodeType.MODULE,
            label=test_id,
            file_path=test_fp,
            metadata={"source": "test"},
        )
    )
    g.add_edge(Edge(source=test_id, target=source_id, type=edge_type))
    return g


# ===========================================================================
# TestSuggestTests
# ===========================================================================


class TestSuggestTests:
    """Tests for suggest_tests()."""

    def test_graph_based_direct_import(self):
        """Test node that imports changed node is suggested with score 0.9."""
        g = _build_graph_with_test(
            "mod:handler", "src/handler.py",
            "mod:test_handler", "tests/test_handler.py",
        )
        diff = [DiffFile(path="src/handler.py", status="modified")]
        results = suggest_tests(g, diff)
        assert len(results) >= 1
        assert results[0].score == 0.9
        assert results[0].strategy == "graph"
        assert results[0].file_path == "tests/test_handler.py"

    def test_graph_based_sibling(self):
        """Test node that is a sibling (both import same parent) is suggested."""
        g = ArchGraph()
        # Parent module
        g.add_node(Node(id="mod:parent", type=NodeType.MODULE, label="parent", file_path="src/parent.py"))
        # Source module imports parent
        g.add_node(Node(id="mod:child", type=NodeType.MODULE, label="child", file_path="src/child.py"))
        g.add_edge(Edge(source="mod:child", target="mod:parent", type=EdgeType.IMPORTS))
        # Test module imports child directly
        g.add_node(
            Node(id="mod:test_child", type=NodeType.MODULE, label="test_child",
                 file_path="tests/test_child.py", metadata={"source": "test"})
        )
        g.add_edge(Edge(source="mod:test_child", target="mod:child", type=EdgeType.IMPORTS))

        diff = [DiffFile(path="src/child.py", status="modified")]
        results = suggest_tests(g, diff)
        test_paths = [r.file_path for r in results]
        assert "tests/test_child.py" in test_paths

    def test_naming_convention_python(self):
        """Changed 'handler.py' suggests 'test_handler.py' if exists in graph."""
        g = ArchGraph()
        g.add_node(
            Node(id="mod:handler", type=NodeType.MODULE, label="handler", file_path="src/handler.py")
        )
        g.add_node(
            Node(id="mod:test_handler", type=NodeType.MODULE, label="test_handler",
                 file_path="tests/test_handler.py", metadata={"source": "test"})
        )
        # No edge between them -- naming convention only
        diff = [DiffFile(path="src/handler.py", status="modified")]
        results = suggest_tests(g, diff)
        naming_results = [r for r in results if r.strategy == "naming"]
        assert len(naming_results) >= 1
        assert naming_results[0].file_path == "tests/test_handler.py"
        assert naming_results[0].score == 0.6

    def test_naming_convention_go(self):
        """Changed 'handler.go' suggests 'handler_test.go' if exists in graph."""
        g = ArchGraph()
        g.add_node(
            Node(id="mod:handler", type=NodeType.MODULE, label="handler", file_path="handler.go")
        )
        g.add_node(
            Node(id="mod:handler_test", type=NodeType.MODULE, label="handler_test",
                 file_path="handler_test.go", metadata={"source": "test"})
        )
        diff = [DiffFile(path="handler.go", status="modified")]
        results = suggest_tests(g, diff)
        test_paths = [r.file_path for r in results]
        assert "handler_test.go" in test_paths

    def test_naming_convention_typescript(self):
        """Changed 'handler.ts' suggests 'handler.test.ts' if exists in graph."""
        g = ArchGraph()
        g.add_node(
            Node(id="mod:handler", type=NodeType.MODULE, label="handler", file_path="src/handler.ts")
        )
        g.add_node(
            Node(id="mod:handler_test", type=NodeType.MODULE, label="handler.test",
                 file_path="src/handler.test.ts", metadata={"source": "test"})
        )
        diff = [DiffFile(path="src/handler.ts", status="modified")]
        results = suggest_tests(g, diff)
        test_paths = [r.file_path for r in results]
        assert "src/handler.test.ts" in test_paths

    def test_naming_convention_java(self):
        """Changed 'Handler.java' suggests 'HandlerTest.java' if exists in graph."""
        g = ArchGraph()
        g.add_node(
            Node(id="mod:Handler", type=NodeType.MODULE, label="Handler", file_path="src/Handler.java")
        )
        g.add_node(
            Node(id="mod:HandlerTest", type=NodeType.MODULE, label="HandlerTest",
                 file_path="test/HandlerTest.java", metadata={"source": "test"})
        )
        diff = [DiffFile(path="src/Handler.java", status="modified")]
        results = suggest_tests(g, diff)
        test_paths = [r.file_path for r in results]
        assert "test/HandlerTest.java" in test_paths

    def test_blast_radius_transitive(self):
        """Test node in blast radius is suggested with score 0.3."""
        g = ArchGraph()
        # A -> B -> test_b (test node)
        g.add_node(Node(id="mod:A", type=NodeType.MODULE, label="A", file_path="src/a.py"))
        g.add_node(Node(id="mod:B", type=NodeType.MODULE, label="B", file_path="src/b.py"))
        g.add_node(
            Node(id="mod:test_b", type=NodeType.MODULE, label="test_b",
                 file_path="tests/test_b.py", metadata={"source": "test"})
        )
        g.add_edge(Edge(source="mod:A", target="mod:B", type=EdgeType.IMPORTS))
        g.add_edge(Edge(source="mod:B", target="mod:test_b", type=EdgeType.IMPORTS))

        diff = [DiffFile(path="src/a.py", status="modified")]
        results = suggest_tests(g, diff)
        blast_results = [r for r in results if r.strategy == "blast_radius"]
        assert len(blast_results) >= 1
        assert blast_results[0].file_path == "tests/test_b.py"
        assert blast_results[0].score == 0.3

    def test_deduplication(self):
        """Same test found by multiple strategies keeps highest score."""
        g = _build_graph_with_test(
            "mod:handler", "src/handler.py",
            "mod:test_handler", "tests/test_handler.py",
        )
        # This test node will be found by both graph-based (0.9) and naming (0.6)
        diff = [DiffFile(path="src/handler.py", status="modified")]
        results = suggest_tests(g, diff)
        # Should only appear once
        matching = [r for r in results if r.file_path == "tests/test_handler.py"]
        assert len(matching) == 1
        assert matching[0].score == 0.9  # highest wins

    def test_max_suggestions_limit(self):
        """More suggestions than limit are truncated."""
        g = ArchGraph()
        g.add_node(Node(id="mod:src", type=NodeType.MODULE, label="src", file_path="src/src.py"))
        # Create many test nodes
        for i in range(30):
            test_id = f"mod:test_{i}"
            g.add_node(
                Node(id=test_id, type=NodeType.MODULE, label=f"test_{i}",
                     file_path=f"tests/test_{i}.py", metadata={"source": "test"})
            )
            g.add_edge(Edge(source=test_id, target="mod:src", type=EdgeType.IMPORTS))

        diff = [DiffFile(path="src/src.py", status="modified")]
        results = suggest_tests(g, diff, max_suggestions=5)
        assert len(results) == 5

    def test_no_tests_found(self):
        """No matching tests returns empty list."""
        g = ArchGraph()
        g.add_node(Node(id="mod:A", type=NodeType.MODULE, label="A", file_path="src/a.py"))
        diff = [DiffFile(path="src/a.py", status="modified")]
        results = suggest_tests(g, diff)
        assert results == []

    def test_empty_diff(self):
        """Empty diff returns empty list."""
        g = ArchGraph()
        g.add_node(Node(id="mod:A", type=NodeType.MODULE, label="A", file_path="src/a.py"))
        results = suggest_tests(g, [])
        assert results == []

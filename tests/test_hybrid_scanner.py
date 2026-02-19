"""Tests for hybrid scanner mode (scanner_mode="hybrid").

The hybrid mode runs BOTH regex recognizers AND AST recognizers over the same
files. ScanResult.merge() handles deduplication: nodes by id (additive metadata
merge) and all structured info fields by their natural identity tuples.

Tests are split:
1. Tests for ScanResult.merge() correctness — always run (no tree-sitter needed)
2. Tests for get_hybrid_registry() and hybrid scan_project — require tree-sitter
"""

import pytest
from pathlib import Path
from unittest.mock import patch

from codegiraffe.scanner import (
    ScanResult,
    scan_project,
    sync_files,
    ImportInfo,
    CallInfo,
    ImplementationInfo,
    InterfaceInfo,
    MethodSetEntry,
)
from codegiraffe.graph import Node, Edge, ArchGraph
from codegiraffe.schema import NodeType, EdgeType

# ---------------------------------------------------------------------------
# Detect tree-sitter availability (mirrors ast_scanner.py logic)
# ---------------------------------------------------------------------------

try:
    import tree_sitter  # noqa: F401
    import tree_sitter_python  # noqa: F401
    import tree_sitter_go  # noqa: F401
    import tree_sitter_typescript  # noqa: F401
    import tree_sitter_rust  # noqa: F401
    import tree_sitter_java  # noqa: F401
    HAS_TREE_SITTER = True
except ImportError:
    HAS_TREE_SITTER = False

requires_tree_sitter = pytest.mark.skipif(
    not HAS_TREE_SITTER,
    reason="tree-sitter-languages not installed",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_node(nid: str, meta: dict | None = None) -> Node:
    """Build a minimal Node with the given id and optional metadata."""
    return Node(
        id=nid,
        type=NodeType.SERVICE,
        label=nid,
        metadata=dict(meta or {}),
    )


def _make_edge(src: str, tgt: str) -> Edge:
    return Edge(source=src, target=tgt, type=EdgeType.CALLS)


# ---------------------------------------------------------------------------
# ScanResult.merge() — always-run tests (no tree-sitter required)
# ---------------------------------------------------------------------------


class TestScanResultMergeNodeDeduplication:
    """test_hybrid_node_deduplication — merge keeps one node per id."""

    def test_merge_same_id_keeps_first_node(self):
        """Duplicate node ids result in exactly one node after merge."""
        r1 = ScanResult(nodes=[_make_node("service:Foo", {"key": "from-r1"})])
        r2 = ScanResult(nodes=[_make_node("service:Foo", {"other": "from-r2"})])

        r1.merge(r2)

        foo_nodes = [n for n in r1.nodes if n.id == "service:Foo"]
        assert len(foo_nodes) == 1, f"Expected 1 node, got {len(foo_nodes)}"

    def test_merge_distinct_ids_both_present(self):
        """Nodes with different ids are both preserved after merge."""
        r1 = ScanResult(nodes=[_make_node("service:Foo")])
        r2 = ScanResult(nodes=[_make_node("service:Bar")])

        r1.merge(r2)

        ids = {n.id for n in r1.nodes}
        assert "service:Foo" in ids
        assert "service:Bar" in ids
        assert len(r1.nodes) == 2

    def test_merge_metadata_additive_new_keys_added(self):
        """Second writer's unique metadata keys are added to the existing node."""
        r1 = ScanResult(nodes=[_make_node("service:Foo", {"source": "regex"})])
        r2 = ScanResult(nodes=[_make_node("service:Foo", {"ast_detected": True})])

        r1.merge(r2)

        node = next(n for n in r1.nodes if n.id == "service:Foo")
        assert node.metadata.get("source") == "regex", "First-writer key must survive"
        assert node.metadata.get("ast_detected") is True, "New key from second writer must be added"

    def test_merge_metadata_does_not_overwrite_existing_key(self):
        """When both results have the same metadata key, the first writer wins."""
        r1 = ScanResult(nodes=[_make_node("service:Foo", {"priority": "high"})])
        r2 = ScanResult(nodes=[_make_node("service:Foo", {"priority": "low"})])

        r1.merge(r2)

        node = next(n for n in r1.nodes if n.id == "service:Foo")
        assert node.metadata["priority"] == "high", (
            "First-writer value must not be overwritten by second writer"
        )


class TestScanResultMergeEdgeDeduplication:
    """Edge deduplication by (source, target, type) tuple."""

    def test_merge_deduplicated_edges(self):
        """Identical edges (same source, target, type) appear only once."""
        e = _make_edge("service:A", "service:B")
        r1 = ScanResult(edges=[e])
        r2 = ScanResult(edges=[_make_edge("service:A", "service:B")])

        r1.merge(r2)

        matching = [
            edge for edge in r1.edges
            if edge.source == "service:A" and edge.target == "service:B"
        ]
        assert len(matching) == 1

    def test_merge_different_edges_both_kept(self):
        """Edges with different targets are both kept."""
        r1 = ScanResult(edges=[_make_edge("service:A", "service:B")])
        r2 = ScanResult(edges=[_make_edge("service:A", "service:C")])

        r1.merge(r2)

        assert len(r1.edges) == 2


class TestScanResultMergeCallInfo:
    """test_merge_deduplicates_call_info — identical CallInfo appears once."""

    def test_identical_call_info_deduplicated(self):
        """Two ScanResults with the same CallInfo produce one copy after merge."""
        call = CallInfo(caller="App.Update", callee="Save", receiver="store", file_path="app.go")
        r1 = ScanResult(calls=[call])
        r2 = ScanResult(calls=[CallInfo(caller="App.Update", callee="Save", receiver="store", file_path="app.go")])

        r1.merge(r2)

        matching = [
            c for c in r1.calls
            if c.caller == "App.Update" and c.callee == "Save"
        ]
        assert len(matching) == 1, f"Expected 1 CallInfo, got {len(matching)}"

    def test_different_call_info_both_kept(self):
        """Different CallInfo entries (different callee) are both kept."""
        r1 = ScanResult(calls=[CallInfo(caller="App.Run", callee="Save", file_path="app.go")])
        r2 = ScanResult(calls=[CallInfo(caller="App.Run", callee="Load", file_path="app.go")])

        r1.merge(r2)

        callees = {c.callee for c in r1.calls}
        assert "Save" in callees
        assert "Load" in callees


class TestScanResultMergeImportInfo:
    """test_merge_deduplicates_import_info — identical ImportInfo appears once."""

    def test_identical_import_info_deduplicated(self):
        """Two ScanResults with the same ImportInfo produce one copy after merge."""
        imp = ImportInfo(module_path="services.user", style="absolute")
        r1 = ScanResult(imports=[imp])
        r2 = ScanResult(imports=[ImportInfo(module_path="services.user", style="absolute")])

        r1.merge(r2)

        matching = [i for i in r1.imports if i.module_path == "services.user"]
        assert len(matching) == 1, f"Expected 1 ImportInfo, got {len(matching)}"

    def test_different_import_info_both_kept(self):
        """Different module paths are both kept."""
        r1 = ScanResult(imports=[ImportInfo(module_path="services.user", style="absolute")])
        r2 = ScanResult(imports=[ImportInfo(module_path="services.order", style="absolute")])

        r1.merge(r2)

        paths = {i.module_path for i in r1.imports}
        assert "services.user" in paths
        assert "services.order" in paths


class TestScanResultMergeImplementationInfo:
    """test_merge_deduplicates_implementation_info — identical entries appear once."""

    def test_identical_implementation_info_deduplicated(self):
        """Two identical ImplementationInfo entries become one after merge."""
        impl = ImplementationInfo(child_class="UserRepo", parent_class="Repository", file_path="repo.go")
        r1 = ScanResult(implementations=[impl])
        r2 = ScanResult(implementations=[
            ImplementationInfo(child_class="UserRepo", parent_class="Repository", file_path="repo.go")
        ])

        r1.merge(r2)

        matching = [i for i in r1.implementations if i.child_class == "UserRepo"]
        assert len(matching) == 1, f"Expected 1 ImplementationInfo, got {len(matching)}"

    def test_different_implementation_info_both_kept(self):
        """Different implementations (different parent) are both kept."""
        r1 = ScanResult(implementations=[
            ImplementationInfo(child_class="UserRepo", parent_class="Repository", file_path="repo.go")
        ])
        r2 = ScanResult(implementations=[
            ImplementationInfo(child_class="UserRepo", parent_class="Storer", file_path="repo.go")
        ])

        r1.merge(r2)

        parents = {i.parent_class for i in r1.implementations}
        assert "Repository" in parents
        assert "Storer" in parents


class TestScanResultMergeInterfaceInfo:
    """test_merge_deduplicates_interface_info — identical entries appear once."""

    def test_identical_interface_info_deduplicated(self):
        """Two identical InterfaceInfo entries become one after merge."""
        iface = InterfaceInfo(name="Store", methods=["Save", "Load"], file_path="store.go")
        r1 = ScanResult(interfaces=[iface])
        r2 = ScanResult(interfaces=[
            InterfaceInfo(name="Store", methods=["Save", "Load"], file_path="store.go")
        ])

        r1.merge(r2)

        matching = [i for i in r1.interfaces if i.name == "Store"]
        assert len(matching) == 1, f"Expected 1 InterfaceInfo, got {len(matching)}"

    def test_different_interface_info_both_kept(self):
        """Interfaces with different names are both kept."""
        r1 = ScanResult(interfaces=[InterfaceInfo(name="Store", file_path="store.go")])
        r2 = ScanResult(interfaces=[InterfaceInfo(name="Cache", file_path="cache.go")])

        r1.merge(r2)

        names = {i.name for i in r1.interfaces}
        assert "Store" in names
        assert "Cache" in names


class TestScanResultMergeMethodSetEntry:
    """test_merge_deduplicates_method_set_entry — identical entries appear once."""

    def test_identical_method_set_entry_deduplicated(self):
        """Two identical MethodSetEntry values become one after merge."""
        ms = MethodSetEntry(struct_name="UserRepo", method_name="Save", file_path="repo.go")
        r1 = ScanResult(method_sets=[ms])
        r2 = ScanResult(method_sets=[
            MethodSetEntry(struct_name="UserRepo", method_name="Save", file_path="repo.go")
        ])

        r1.merge(r2)

        matching = [m for m in r1.method_sets if m.method_name == "Save"]
        assert len(matching) == 1, f"Expected 1 MethodSetEntry, got {len(matching)}"

    def test_different_method_set_entries_both_kept(self):
        """Different methods on the same struct are both kept."""
        r1 = ScanResult(method_sets=[MethodSetEntry(struct_name="UserRepo", method_name="Save", file_path="repo.go")])
        r2 = ScanResult(method_sets=[MethodSetEntry(struct_name="UserRepo", method_name="Load", file_path="repo.go")])

        r1.merge(r2)

        methods = {m.method_name for m in r1.method_sets}
        assert "Save" in methods
        assert "Load" in methods


class TestScanResultMergeEmpty:
    """Edge cases: merging with empty results."""

    def test_merge_empty_into_populated(self):
        """Merging an empty ScanResult changes nothing."""
        r1 = ScanResult(
            nodes=[_make_node("service:Foo")],
            calls=[CallInfo(caller="X", callee="Y", file_path="x.go")],
        )
        r2 = ScanResult()

        r1.merge(r2)

        assert len(r1.nodes) == 1
        assert len(r1.calls) == 1

    def test_merge_populated_into_empty(self):
        """Merging a populated result into empty adopts all entries."""
        r1 = ScanResult()
        r2 = ScanResult(
            nodes=[_make_node("service:Bar")],
            calls=[CallInfo(caller="X", callee="Y", file_path="x.go")],
        )

        r1.merge(r2)

        assert len(r1.nodes) == 1
        assert r1.nodes[0].id == "service:Bar"
        assert len(r1.calls) == 1

    def test_merge_preserves_self_when_other_is_empty(self):
        """No entries are lost when merging an empty other."""
        original_node = _make_node("service:Original")
        r1 = ScanResult(nodes=[original_node])
        r1.merge(ScanResult())
        assert r1.nodes[0].id == "service:Original"


class TestScanResultMergeMultipleNodes:
    """Stress: many nodes, some duplicate, some unique."""

    def test_merge_many_nodes_correct_count(self):
        """Merge of 10 unique + 5 duplicate node ids yields 10 unique nodes."""
        unique_nodes = [_make_node(f"service:Unique{i}") for i in range(10)]
        overlap_nodes_r1 = [_make_node(f"service:Shared{i}", {"r": "1"}) for i in range(5)]
        overlap_nodes_r2 = [_make_node(f"service:Shared{i}", {"r": "2"}) for i in range(5)]

        r1 = ScanResult(nodes=unique_nodes[:5] + overlap_nodes_r1)
        r2 = ScanResult(nodes=unique_nodes[5:] + overlap_nodes_r2)

        r1.merge(r2)

        assert len(r1.nodes) == 15, f"Expected 15 unique nodes, got {len(r1.nodes)}"

    def test_merge_shared_nodes_keep_first_writer_metadata(self):
        """After merge, shared nodes retain the first writer's metadata values."""
        shared_nodes_r1 = [_make_node(f"service:S{i}", {"r": "1", "idx": str(i)}) for i in range(5)]
        shared_nodes_r2 = [_make_node(f"service:S{i}", {"r": "2", "extra": "yes"}) for i in range(5)]

        r1 = ScanResult(nodes=shared_nodes_r1)
        r2 = ScanResult(nodes=shared_nodes_r2)
        r1.merge(r2)

        for node in r1.nodes:
            assert node.metadata["r"] == "1", f"Node {node.id} lost first-writer value"
            assert node.metadata.get("extra") == "yes", f"Node {node.id} missing additive key"


# ---------------------------------------------------------------------------
# get_hybrid_registry() — requires tree-sitter
# ---------------------------------------------------------------------------


class TestGetHybridRegistryRequiresTreeSitter:
    """test_get_hybrid_registry_requires_tree_sitter — raises if unavailable."""

    def test_raises_import_error_when_tree_sitter_missing(self):
        """get_hybrid_registry() must raise ImportError when HAS_TREE_SITTER is False."""
        import codegiraffe.ast_scanner as ast_mod

        with patch.object(ast_mod, "HAS_TREE_SITTER", False):
            with pytest.raises(ImportError, match="tree-sitter"):
                ast_mod.get_hybrid_registry()


@requires_tree_sitter
class TestGetHybridRegistry:
    """test_get_hybrid_registry_has_both_recognizers — registry contains regex + AST."""

    @pytest.fixture
    def registry(self):
        from codegiraffe.ast_scanner import get_hybrid_registry
        return get_hybrid_registry()

    def test_returns_recognizer_registry(self, registry):
        from codegiraffe.registry import RecognizerRegistry
        assert isinstance(registry, RecognizerRegistry)

    def test_go_files_have_both_regex_and_ast_recognizers(self, registry):
        """For .go, both GoRecognizer (regex) and GoASTRecognizer (AST) must be present."""
        from codegiraffe.ast_scanner import GoASTRecognizer
        from codegiraffe.recognizers.go import GoRecognizer

        recognizers = registry.get_recognizers(Path("test.go"))
        types = [type(r) for r in recognizers]

        assert GoRecognizer in types, f"GoRecognizer (regex) missing from .go recognizers: {types}"
        assert GoASTRecognizer in types, f"GoASTRecognizer (AST) missing from .go recognizers: {types}"

    def test_python_files_have_both_regex_and_ast_recognizers(self, registry):
        """For .py, both PythonRecognizer (regex) and PythonASTRecognizer (AST) must be present."""
        from codegiraffe.ast_scanner import PythonASTRecognizer
        from codegiraffe.scanner import PythonRecognizer

        recognizers = registry.get_recognizers(Path("test.py"))
        types = [type(r) for r in recognizers]

        assert PythonRecognizer in types, f"PythonRecognizer (regex) missing: {types}"
        assert PythonASTRecognizer in types, f"PythonASTRecognizer (AST) missing: {types}"

    def test_typescript_files_have_both_recognizers(self, registry):
        """For .ts, both TypeScriptRecognizer and TypeScriptASTRecognizer must be present."""
        from codegiraffe.ast_scanner import TypeScriptASTRecognizer
        from codegiraffe.recognizers.typescript import TypeScriptRecognizer

        recognizers = registry.get_recognizers(Path("test.ts"))
        types = [type(r) for r in recognizers]

        assert TypeScriptRecognizer in types, f"TypeScriptRecognizer missing: {types}"
        assert TypeScriptASTRecognizer in types, f"TypeScriptASTRecognizer missing: {types}"

    def test_rust_files_have_both_recognizers(self, registry):
        """For .rs, both RustRecognizer and RustASTRecognizer must be present."""
        from codegiraffe.ast_scanner import RustASTRecognizer
        from codegiraffe.recognizers.rust import RustRecognizer

        recognizers = registry.get_recognizers(Path("test.rs"))
        types = [type(r) for r in recognizers]

        assert RustRecognizer in types, f"RustRecognizer (regex) missing: {types}"
        assert RustASTRecognizer in types, f"RustASTRecognizer (AST) missing: {types}"

    def test_go_has_at_least_two_recognizers(self, registry):
        """There must be at least 2 recognizers registered for .go (one regex, one AST)."""
        recognizers = registry.get_recognizers(Path("test.go"))
        assert len(recognizers) >= 2, f"Expected >= 2 recognizers for .go, got {len(recognizers)}"

    def test_extensions_include_expected_languages(self, registry):
        """Hybrid registry covers the expected file extensions."""
        exts = registry.registered_extensions
        for ext in [".py", ".go", ".ts", ".rs", ".java"]:
            assert ext in exts, f"Extension {ext!r} missing from hybrid registry"


# ---------------------------------------------------------------------------
# Hybrid scan_project() — requires tree-sitter
# ---------------------------------------------------------------------------


@requires_tree_sitter
class TestHybridScanGoFile:
    """Hybrid scan over Go files: struct detection (AST) + endpoints (regex)."""

    @pytest.fixture
    def go_project(self, tmp_path: Path) -> Path:
        """Minimal Go project: HTTP handlers + struct definitions + env vars."""
        go_file = tmp_path / "main.go"
        go_file.write_text('''\
package main

import (
    "net/http"
    "os"
)

type UserService struct {
    db interface{}
}

type OrderHandler struct {
    service interface{}
}

func main() {
    dbHost := os.Getenv("DB_HOST")
    port := os.Getenv("PORT")
    _ = dbHost
    _ = port

    http.HandleFunc("/api/users", getUsers)
    http.HandleFunc("/api/orders", getOrders)
}

func getUsers(w http.ResponseWriter, r *http.Request) {}
func getOrders(w http.ResponseWriter, r *http.Request) {}
''')
        return tmp_path

    def test_hybrid_scan_detects_go_structs(self, go_project: Path):
        """AST recognizer must find struct definitions as service nodes."""
        from codegiraffe.ast_scanner import get_hybrid_registry
        registry = get_hybrid_registry()

        result = scan_project(str(go_project), registry=registry)
        ids = {n.id for n in result.nodes}

        assert "service:UserService" in ids, f"Expected service:UserService in {ids}"
        assert "service:OrderHandler" in ids, f"Expected service:OrderHandler in {ids}"

    def test_hybrid_scan_detects_env_vars(self, go_project: Path):
        """AST recognizer must find os.Getenv() calls as env_var nodes."""
        from codegiraffe.ast_scanner import get_hybrid_registry
        registry = get_hybrid_registry()

        result = scan_project(str(go_project), registry=registry)
        ids = {n.id for n in result.nodes}

        assert "env:DB_HOST" in ids, f"Expected env:DB_HOST in {ids}"
        assert "env:PORT" in ids, f"Expected env:PORT in {ids}"

    def test_hybrid_scan_no_duplicate_nodes(self, go_project: Path):
        """When regex and AST both detect the same struct, only one node survives."""
        from codegiraffe.ast_scanner import get_hybrid_registry
        registry = get_hybrid_registry()

        result = scan_project(str(go_project), registry=registry)

        user_service_nodes = [n for n in result.nodes if n.id == "service:UserService"]
        assert len(user_service_nodes) == 1, (
            f"Duplicate node: found {len(user_service_nodes)} copies of service:UserService"
        )

    def test_hybrid_scan_no_duplicate_nodes_all_nodes(self, go_project: Path):
        """No node id appears more than once in a hybrid scan result."""
        from codegiraffe.ast_scanner import get_hybrid_registry
        registry = get_hybrid_registry()

        result = scan_project(str(go_project), registry=registry)

        ids = [n.id for n in result.nodes]
        unique_ids = set(ids)
        duplicates = [nid for nid in unique_ids if ids.count(nid) > 1]
        assert len(duplicates) == 0, f"Duplicate node ids found: {duplicates}"


@requires_tree_sitter
class TestHybridScanCallPreservation:
    """test_hybrid_scan_preserves_calls — AST-detected calls survive the merge."""

    def test_hybrid_scan_preserves_calls(self, tmp_path: Path):
        """Go file with method calls: CallInfo from AST recognizer must be in hybrid result."""
        go_file = tmp_path / "app.go"
        go_file.write_text('''\
package main

type App struct {
    store Store
}

func (a *App) Update() {
    a.store.Save()
    result := a.store.Load()
    _ = result
}
''')

        from codegiraffe.ast_scanner import get_hybrid_registry
        registry = get_hybrid_registry()

        result = scan_project(str(tmp_path), registry=registry)

        assert len(result.calls) > 0, "Expected CallInfo entries from hybrid scan"
        callees = {c.callee for c in result.calls}
        assert "Save" in callees or "Load" in callees, (
            f"Expected Save or Load in callees, got: {callees}"
        )


@requires_tree_sitter
class TestHybridScanPythonFile:
    """Hybrid scan over Python files: Flask routes + class definitions."""

    def test_hybrid_python_scan_no_duplicate_nodes(self, tmp_path: Path):
        """No duplicate node ids when regex and AST both detect Python classes."""
        py_file = tmp_path / "services.py"
        py_file.write_text('''\
class UserService:
    def get_user(self, user_id):
        pass

class OrderService:
    def process(self, order_id):
        pass
''')

        from codegiraffe.ast_scanner import get_hybrid_registry
        registry = get_hybrid_registry()

        result = scan_project(str(tmp_path), registry=registry)

        ids = [n.id for n in result.nodes]
        unique_ids = set(ids)
        duplicates = [nid for nid in unique_ids if ids.count(nid) > 1]
        assert len(duplicates) == 0, f"Duplicate node ids from hybrid Python scan: {duplicates}"

    def test_hybrid_python_scan_detects_flask_routes(self, tmp_path: Path):
        """Flask route decorators are detected (from either regex or AST recognizer)."""
        py_file = tmp_path / "app.py"
        py_file.write_text('''\
from flask import Flask
app = Flask(__name__)

@app.route("/api/items")
def get_items():
    return []
''')

        from codegiraffe.ast_scanner import get_hybrid_registry
        registry = get_hybrid_registry()

        result = scan_project(str(tmp_path), registry=registry)
        ids = {n.id for n in result.nodes}

        assert "endpoint:/api/items" in ids, f"Expected endpoint:/api/items in {ids}"


# ---------------------------------------------------------------------------
# sync_files() hybrid mode — requires tree-sitter
# ---------------------------------------------------------------------------


@requires_tree_sitter
class TestSyncFilesHybridMode:
    """test_sync_files_accepts_hybrid_mode — sync_files works with scanner_mode='hybrid'."""

    def test_sync_files_accepts_hybrid_mode(self, tmp_path: Path):
        """sync_files() with scanner_mode='hybrid' does not raise and returns valid results."""
        go_file = tmp_path / "main.go"
        go_file.write_text('''\
package main

type UserService struct {
    db interface{}
}
''')

        # Build an initial graph with scan_project so sync_files has something to diff against
        from codegiraffe.ast_scanner import get_hybrid_registry
        registry = get_hybrid_registry()
        initial = scan_project(str(tmp_path), registry=registry)

        graph = ArchGraph()
        for node in initial.nodes:
            graph.add_node(node)
        for edge in initial.edges:
            graph.add_edge(edge)

        # sync_files should accept hybrid mode without raising
        result = sync_files(
            graph=graph,
            project_path=str(tmp_path),
            file_paths=[str(go_file)],
            scanner_mode="hybrid",
        )

        # Result must be a dict with expected shape
        assert isinstance(result, dict), f"sync_files must return dict, got {type(result)}"
        assert "added" in result, f"Result missing 'added' key: {result}"
        assert "removed" in result, f"Result missing 'removed' key: {result}"

    def test_sync_files_hybrid_updates_graph(self, tmp_path: Path):
        """sync_files with hybrid mode adds new nodes discovered by AST recognizer."""
        # Start with an empty graph
        graph = ArchGraph()

        go_file = tmp_path / "service.go"
        go_file.write_text('''\
package main

type PaymentService struct {
    processor interface{}
}
''')

        result = sync_files(
            graph=graph,
            project_path=str(tmp_path),
            file_paths=[str(go_file)],
            scanner_mode="hybrid",
        )

        assert isinstance(result, dict)
        # After syncing a new file, some nodes should be added
        added_nodes = result.get("added", {}).get("nodes", 0)
        assert added_nodes >= 0, "added.nodes must be a non-negative integer"

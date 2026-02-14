"""Tests for call-graph edge inference pipeline (v0.9.0 Phase 3)."""

import pytest
from pathlib import Path

from codegiraffe.scanner import (
    CallInfo, InterfaceInfo, MethodSetEntry, ScanResult,
    _infer_call_edges, _infer_interface_satisfaction, _find_node_id_for_name,
)
from codegiraffe.graph import Edge, Node
from codegiraffe.schema import EdgeType, NodeType


class TestFindNodeIdForName:
    """Test _find_node_id_for_name helper."""

    def test_find_by_label(self):
        result = ScanResult(nodes=[
            Node(id="service:Foo", type="service", label="Foo"),
        ])
        assert _find_node_id_for_name(result, "Foo") == "service:Foo"

    def test_find_by_struct_name(self):
        result = ScanResult(nodes=[
            Node(id="service:MyStruct", type="service", label="MyStruct",
                 metadata={"struct_name": "MyStruct"}),
        ])
        assert _find_node_id_for_name(result, "MyStruct") == "service:MyStruct"

    def test_find_by_class_name(self):
        result = ScanResult(nodes=[
            Node(id="service:MyClass", type="service", label="MyClass",
                 metadata={"class_name": "MyClass"}),
        ])
        assert _find_node_id_for_name(result, "MyClass") == "service:MyClass"

    def test_not_found(self):
        result = ScanResult(nodes=[
            Node(id="service:Foo", type="service", label="Foo"),
        ])
        assert _find_node_id_for_name(result, "Bar") is None


class TestInferInterfaceSatisfaction:
    """Test Go duck-type interface satisfaction inference."""

    def test_struct_satisfies_interface(self):
        result = ScanResult(
            nodes=[
                Node(id="service:Store", type="service", label="Store",
                     metadata={"struct_name": "Store"}),
                Node(id="service:SQLiteStore", type="service", label="SQLiteStore",
                     metadata={"struct_name": "SQLiteStore"}),
            ],
            interfaces=[
                InterfaceInfo(name="Store", methods=["Get", "Put"], file_path="store/store.go"),
            ],
            method_sets=[
                MethodSetEntry(struct_name="SQLiteStore", method_name="Get", file_path="store/sqlite.go"),
                MethodSetEntry(struct_name="SQLiteStore", method_name="Put", file_path="store/sqlite.go"),
                MethodSetEntry(struct_name="SQLiteStore", method_name="Close", file_path="store/sqlite.go"),
            ],
        )
        _infer_interface_satisfaction(result)
        impl_edges = [e for e in result.edges if e.type == EdgeType.IMPLEMENTS.value
                      and e.source == "service:SQLiteStore" and e.target == "service:Store"]
        assert len(impl_edges) == 1
        assert impl_edges[0].metadata["mechanism"] == "duck_type"
        assert sorted(impl_edges[0].metadata["matched_methods"]) == ["Get", "Put"]

    def test_struct_missing_method_no_match(self):
        result = ScanResult(
            nodes=[
                Node(id="service:Store", type="service", label="Store"),
                Node(id="service:PartialStore", type="service", label="PartialStore"),
            ],
            interfaces=[
                InterfaceInfo(name="Store", methods=["Get", "Put", "Delete"]),
            ],
            method_sets=[
                MethodSetEntry(struct_name="PartialStore", method_name="Get"),
                MethodSetEntry(struct_name="PartialStore", method_name="Put"),
                # Missing Delete
            ],
        )
        _infer_interface_satisfaction(result)
        impl_edges = [e for e in result.edges if e.type == EdgeType.IMPLEMENTS.value]
        assert len(impl_edges) == 0

    def test_no_interfaces_is_noop(self):
        result = ScanResult(
            nodes=[Node(id="service:Foo", type="service", label="Foo")],
            method_sets=[MethodSetEntry(struct_name="Foo", method_name="Bar")],
        )
        _infer_interface_satisfaction(result)
        assert len(result.edges) == 0

    def test_no_method_sets_is_noop(self):
        result = ScanResult(
            nodes=[Node(id="service:Store", type="service", label="Store")],
            interfaces=[InterfaceInfo(name="Store", methods=["Get"])],
        )
        _infer_interface_satisfaction(result)
        assert len(result.edges) == 0

    def test_dedup_existing_implements_edge(self):
        """If an implements edge already exists, don't duplicate it."""
        result = ScanResult(
            nodes=[
                Node(id="service:Store", type="service", label="Store"),
                Node(id="service:SQLiteStore", type="service", label="SQLiteStore"),
            ],
            edges=[
                Edge(source="service:SQLiteStore", target="service:Store",
                     type=EdgeType.IMPLEMENTS.value),
            ],
            interfaces=[
                InterfaceInfo(name="Store", methods=["Get"]),
            ],
            method_sets=[
                MethodSetEntry(struct_name="SQLiteStore", method_name="Get"),
            ],
        )
        _infer_interface_satisfaction(result)
        impl_edges = [e for e in result.edges if e.type == EdgeType.IMPLEMENTS.value]
        assert len(impl_edges) == 1  # No duplicate

    def test_empty_interface_methods_skipped(self):
        """An interface with no methods should not match any struct."""
        result = ScanResult(
            nodes=[
                Node(id="service:Empty", type="service", label="Empty"),
                Node(id="service:Foo", type="service", label="Foo"),
            ],
            interfaces=[
                InterfaceInfo(name="Empty", methods=[]),
            ],
            method_sets=[
                MethodSetEntry(struct_name="Foo", method_name="Bar"),
            ],
        )
        _infer_interface_satisfaction(result)
        impl_edges = [e for e in result.edges if e.type == EdgeType.IMPLEMENTS.value]
        assert len(impl_edges) == 0

    def test_multiple_structs_satisfy_same_interface(self):
        """Multiple structs can satisfy the same interface."""
        result = ScanResult(
            nodes=[
                Node(id="service:Reader", type="service", label="Reader"),
                Node(id="service:FileReader", type="service", label="FileReader"),
                Node(id="service:NetReader", type="service", label="NetReader"),
            ],
            interfaces=[
                InterfaceInfo(name="Reader", methods=["Read"]),
            ],
            method_sets=[
                MethodSetEntry(struct_name="FileReader", method_name="Read"),
                MethodSetEntry(struct_name="FileReader", method_name="Close"),
                MethodSetEntry(struct_name="NetReader", method_name="Read"),
            ],
        )
        _infer_interface_satisfaction(result)
        impl_edges = [e for e in result.edges if e.type == EdgeType.IMPLEMENTS.value]
        assert len(impl_edges) == 2
        sources = {e.source for e in impl_edges}
        assert sources == {"service:FileReader", "service:NetReader"}


class TestInferCallEdges:
    """Test call-graph edge inference from CallInfo records."""

    def test_method_call_creates_edge(self):
        result = ScanResult(
            nodes=[
                Node(id="service:App", type="service", label="App",
                     metadata={"struct_name": "App"}),
                Node(id="service:Store", type="service", label="Store",
                     metadata={"struct_name": "Store"}),
            ],
            calls=[
                CallInfo(caller="App.Update", callee="Save", receiver="Store",
                         file_path="app/app.go", style="method"),
            ],
        )
        _infer_call_edges(result)
        call_edges = [e for e in result.edges if e.type == EdgeType.CALLS.value]
        assert len(call_edges) == 1
        assert call_edges[0].source == "service:App"
        assert call_edges[0].target == "service:Store"
        assert call_edges[0].metadata["inferred"] is True
        assert call_edges[0].metadata["style"] == "method"

    def test_unresolvable_callee_skipped(self):
        result = ScanResult(
            nodes=[
                Node(id="service:App", type="service", label="App"),
            ],
            calls=[
                CallInfo(caller="App.Update", callee="Save", receiver="UnknownType"),
            ],
        )
        _infer_call_edges(result)
        assert len(result.edges) == 0

    def test_self_call_skipped(self):
        result = ScanResult(
            nodes=[
                Node(id="service:App", type="service", label="App",
                     metadata={"struct_name": "App"}),
            ],
            calls=[
                CallInfo(caller="App.Update", callee="Render", receiver="App"),
            ],
        )
        _infer_call_edges(result)
        assert len(result.edges) == 0

    def test_module_as_receiver(self):
        """When receiver matches a module/package label, resolve to module node."""
        result = ScanResult(
            nodes=[
                Node(id="mod:app.main", type="module", label="main",
                     file_path="app/main.go", metadata={"package": "app"}),
                Node(id="mod:store.store", type="module", label="store",
                     file_path="store/store.go", metadata={"package": "store"}),
            ],
            calls=[
                CallInfo(caller="main", callee="Open", receiver="store",
                         file_path="app/main.go"),
            ],
        )
        _infer_call_edges(result)
        call_edges = [e for e in result.edges if e.type == EdgeType.CALLS.value]
        assert len(call_edges) == 1
        assert call_edges[0].target == "mod:store.store"

    def test_caller_resolved_from_file_path(self):
        """When caller can't be resolved by name, fall back to file's module node."""
        result = ScanResult(
            nodes=[
                Node(id="mod:app.main", type="module", label="main",
                     file_path="app/main.go"),
                Node(id="service:Config", type="service", label="Config",
                     metadata={"struct_name": "Config"}),
            ],
            calls=[
                CallInfo(caller="unknownFunc", callee="Load", receiver="Config",
                         file_path="app/main.go"),
            ],
        )
        _infer_call_edges(result)
        call_edges = [e for e in result.edges if e.type == EdgeType.CALLS.value]
        assert len(call_edges) == 1
        assert call_edges[0].source == "mod:app.main"

    def test_no_calls_is_noop(self):
        result = ScanResult(
            nodes=[Node(id="service:Foo", type="service", label="Foo")],
        )
        _infer_call_edges(result)
        assert len(result.edges) == 0

    def test_dedup_call_edges(self):
        """Multiple calls between same pair produce only one edge."""
        result = ScanResult(
            nodes=[
                Node(id="service:App", type="service", label="App",
                     metadata={"struct_name": "App"}),
                Node(id="service:Store", type="service", label="Store",
                     metadata={"struct_name": "Store"}),
            ],
            calls=[
                CallInfo(caller="App.Update", callee="Get", receiver="Store"),
                CallInfo(caller="App.Update", callee="Put", receiver="Store"),
                CallInfo(caller="App.Init", callee="Open", receiver="Store"),
            ],
        )
        _infer_call_edges(result)
        call_edges = [e for e in result.edges if e.type == EdgeType.CALLS.value]
        assert len(call_edges) == 1  # All resolve to same (App -> Store) pair

    def test_direct_call_without_receiver(self):
        """Direct function call (no receiver) resolved via symbol registry."""
        result = ScanResult(
            nodes=[
                Node(id="mod:main", type="module", label="main",
                     file_path="main.go"),
                Node(id="service:Helper", type="service", label="Helper",
                     metadata={"struct_name": "Helper"}),
            ],
            calls=[
                CallInfo(caller="main", callee="Helper",
                         file_path="main.go", style="function"),
            ],
        )
        _infer_call_edges(result)
        call_edges = [e for e in result.edges if e.type == EdgeType.CALLS.value]
        assert len(call_edges) == 1
        assert call_edges[0].source == "mod:main"
        assert call_edges[0].target == "service:Helper"

    def test_caller_no_file_path_unresolvable(self):
        """If caller can't be resolved by name and no file_path, skip."""
        result = ScanResult(
            nodes=[
                Node(id="service:Target", type="service", label="Target",
                     metadata={"struct_name": "Target"}),
            ],
            calls=[
                CallInfo(caller="unknown", callee="Do", receiver="Target"),
            ],
        )
        _infer_call_edges(result)
        assert len(result.edges) == 0

    def test_package_metadata_used_for_module_lookup(self):
        """Module registry should index by package metadata too."""
        result = ScanResult(
            nodes=[
                Node(id="mod:myapp.handlers", type="module", label="handlers",
                     file_path="myapp/handlers.go",
                     metadata={"package": "myapp"}),
                Node(id="service:DB", type="service", label="DB",
                     metadata={"struct_name": "DB"}),
            ],
            calls=[
                CallInfo(caller="handlers.HandleRequest", callee="Query",
                         receiver="DB", file_path="myapp/handlers.go"),
            ],
        )
        _infer_call_edges(result)
        call_edges = [e for e in result.edges if e.type == EdgeType.CALLS.value]
        assert len(call_edges) == 1
        assert call_edges[0].source == "mod:myapp.handlers"
        assert call_edges[0].target == "service:DB"

"""Tests for performance guards added to query.py, scanner.py, and graph.py.

Covers:
1. TestDetectDriftSimilarityGuard  -- _SIMILARITY_MATCH_LIMIT guard in detect_drift
2. TestNameLookupDict              -- _build_name_lookup in scanner.py
3. TestToDataCaching               -- _cached_data dirty-flag in ArchGraph.to_data
5. TestDriftResponseCap            -- _MAX_DRIFT_RECORDS cap in detect_drift

Class 4 (dashboard pagination) is intentionally skipped; it is covered in test_dashboard.py.
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from codegiraffe.graph import Node, Edge, GraphData, ArchGraph
from codegiraffe.schema import NodeType, EdgeType
from codegiraffe.query import (
    detect_drift,
    _SIMILARITY_MATCH_LIMIT,
    _MAX_DRIFT_RECORDS,
)
from codegiraffe.scanner import (
    ScanResult,
    _build_name_lookup,
    _find_node_id_for_name,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_node(node_id: str, label: str | None = None, **metadata) -> Node:
    """Create a minimal Node for testing."""
    return Node(
        id=node_id,
        type=NodeType.SERVICE,
        label=label if label is not None else node_id,
        metadata=metadata,
    )


def _make_scan_result(nodes: list[Node], edges: list[Edge] | None = None) -> ScanResult:
    """Wrap a node list into a ScanResult."""
    return ScanResult(nodes=nodes, edges=edges or [])


def _make_graph_with_nodes(nodes: list[Node]) -> ArchGraph:
    """Build an ArchGraph containing the given nodes."""
    graph = ArchGraph()
    for node in nodes:
        graph.add_node(node)
    return graph


def _mock_scan_result(scan_result: ScanResult):
    """Return a context manager that patches scan_project to return *scan_result*.

    detect_drift lazily imports scan_project from codegiraffe.scanner inside
    the function body, so we must patch it at the source module, not at the
    query module's namespace.
    """
    return patch(
        "codegiraffe.scanner.scan_project",
        return_value=scan_result,
    )


def _mock_no_git_renames():
    """Patch _detect_git_renames to always return no renames (keeps tests isolated)."""
    return patch(
        "codegiraffe.query._detect_git_renames",
        return_value={},
    )


# ---------------------------------------------------------------------------
# 1. TestDetectDriftSimilarityGuard
# ---------------------------------------------------------------------------


class TestDetectDriftSimilarityGuard:
    """Verify that the O(n^2) similarity loop is skipped when either side
    of the diff exceeds _SIMILARITY_MATCH_LIMIT nodes."""

    def test_small_drift_performs_similarity_matching(self, tmp_path):
        """Well under the limit: similarity matching runs and finds potential renames."""
        # Build a graph with an old-style node
        old_node = _make_node("service:OldName", label="Old Name")
        graph = _make_graph_with_nodes([old_node])

        # Scan returns a new-style node with a similar ID (likely a rename)
        new_node = _make_node("service:NewName", label="New Name")
        scan_result = _make_scan_result([new_node])

        with _mock_no_git_renames(), _mock_scan_result(scan_result):
            drifts = detect_drift(graph, str(tmp_path))

        types = [d["type"] for d in drifts]
        # The guard must NOT have fired
        assert "similarity_skipped" not in types

    def test_large_drift_skips_similarity_and_emits_record(self, tmp_path):
        """When missing_in_code exceeds the limit, similarity matching is skipped."""
        # Build a graph with limit+1 auto nodes (none in the scan)
        n = _SIMILARITY_MATCH_LIMIT + 1
        graph_nodes = [_make_node(f"service:OldNode{i}") for i in range(n)]
        graph = _make_graph_with_nodes(graph_nodes)

        # Scan returns an entirely different set of nodes
        scan_nodes = [_make_node(f"service:NewNode{i}") for i in range(n)]
        scan_result = _make_scan_result(scan_nodes)

        with _mock_no_git_renames(), _mock_scan_result(scan_result):
            drifts = detect_drift(graph, str(tmp_path))

        types = [d["type"] for d in drifts]
        assert "similarity_skipped" in types, (
            f"Expected similarity_skipped record; got types: {types}"
        )

    def test_large_drift_on_missing_in_graph_side(self, tmp_path):
        """When missing_in_graph exceeds the limit, similarity matching is skipped."""
        # Graph is empty; scan returns limit+1 nodes
        graph = ArchGraph()

        n = _SIMILARITY_MATCH_LIMIT + 1
        scan_nodes = [_make_node(f"service:NewNode{i}") for i in range(n)]
        scan_result = _make_scan_result(scan_nodes)

        with _mock_no_git_renames(), _mock_scan_result(scan_result):
            drifts = detect_drift(graph, str(tmp_path))

        types = [d["type"] for d in drifts]
        assert "similarity_skipped" in types

    def test_boundary_exactly_500_does_not_trigger_guard(self, tmp_path):
        """Exactly _SIMILARITY_MATCH_LIMIT nodes should NOT trigger the guard.

        The guard uses a strict > comparison, so the boundary value must be
        allowed through.
        """
        n = _SIMILARITY_MATCH_LIMIT  # exactly 500
        graph_nodes = [_make_node(f"service:OldNode{i}") for i in range(n)]
        graph = _make_graph_with_nodes(graph_nodes)

        # Scan returns a completely disjoint set of the same size
        scan_nodes = [_make_node(f"service:NewNode{i}") for i in range(n)]
        scan_result = _make_scan_result(scan_nodes)

        with _mock_no_git_renames(), _mock_scan_result(scan_result):
            drifts = detect_drift(graph, str(tmp_path))

        types = [d["type"] for d in drifts]
        assert "similarity_skipped" not in types, (
            f"Guard fired at exactly {n} nodes — expected > check, not >= check"
        )

    def test_similarity_skipped_record_has_type_field(self, tmp_path):
        """The similarity_skipped record must have type='similarity_skipped'."""
        n = _SIMILARITY_MATCH_LIMIT + 1
        graph = _make_graph_with_nodes([_make_node(f"service:Old{i}") for i in range(n)])
        scan_result = _make_scan_result([_make_node(f"service:New{i}") for i in range(n)])

        with _mock_no_git_renames(), _mock_scan_result(scan_result):
            drifts = detect_drift(graph, str(tmp_path))

        skipped = [d for d in drifts if d.get("type") == "similarity_skipped"]
        assert len(skipped) >= 1
        record = skipped[0]
        assert record["type"] == "similarity_skipped"

    def test_similarity_skipped_record_has_descriptive_detail(self, tmp_path):
        """The similarity_skipped record must have a non-empty 'details' string
        that mentions the node counts and the limit."""
        n = _SIMILARITY_MATCH_LIMIT + 1
        graph = _make_graph_with_nodes([_make_node(f"service:Old{i}") for i in range(n)])
        scan_result = _make_scan_result([_make_node(f"service:New{i}") for i in range(n)])

        with _mock_no_git_renames(), _mock_scan_result(scan_result):
            drifts = detect_drift(graph, str(tmp_path))

        skipped = [d for d in drifts if d.get("type") == "similarity_skipped"]
        assert skipped, "Expected a similarity_skipped record"
        detail = skipped[0].get("details", "")
        assert isinstance(detail, str)
        assert len(detail) > 10, "details should be a descriptive string"
        # The detail should mention the limit constant
        assert str(_SIMILARITY_MATCH_LIMIT) in detail

    def test_manual_nodes_excluded_from_similarity_count(self, tmp_path):
        """Manual nodes in the graph are not counted toward drift, so they must
        not cause the guard to fire when only auto-nodes are under the limit."""
        # One manual node (should be excluded) + a few auto nodes
        auto_nodes = [_make_node(f"service:Auto{i}") for i in range(5)]
        manual_node = Node(
            id="service:ManualNode",
            type=NodeType.SERVICE,
            label="Manual",
            manual=True,
        )
        graph = _make_graph_with_nodes(auto_nodes + [manual_node])

        # Scan returns a completely different small set
        scan_result = _make_scan_result([_make_node(f"service:New{i}") for i in range(5)])

        with _mock_no_git_renames(), _mock_scan_result(scan_result):
            drifts = detect_drift(graph, str(tmp_path))

        types = [d["type"] for d in drifts]
        assert "similarity_skipped" not in types


# ---------------------------------------------------------------------------
# 2. TestNameLookupDict
# ---------------------------------------------------------------------------


class TestNameLookupDict:
    """Verify that _build_name_lookup produces a correct name -> node_id dict."""

    def test_lookup_by_label(self):
        """A node's label should be a key in the lookup."""
        node = _make_node("service:MyService", label="MyService")
        result = _make_scan_result([node])
        lookup = _build_name_lookup(result)
        assert lookup.get("MyService") == "service:MyService"

    def test_lookup_by_struct_name(self):
        """A node with struct_name metadata should be findable by that name."""
        node = Node(
            id="service:MyStruct",
            type=NodeType.SERVICE,
            label="some_label",
            metadata={"struct_name": "MyStruct"},
        )
        result = _make_scan_result([node])
        lookup = _build_name_lookup(result)
        assert lookup.get("MyStruct") == "service:MyStruct"

    def test_lookup_by_class_name(self):
        """A node with class_name metadata should be findable by that name."""
        node = Node(
            id="table:MyModel",
            type=NodeType.DATABASE_TABLE,
            label="some_label",
            metadata={"class_name": "MyModel"},
        )
        result = _make_scan_result([node])
        lookup = _build_name_lookup(result)
        assert lookup.get("MyModel") == "table:MyModel"

    def test_label_wins_over_struct_name(self):
        """When two different nodes have the same string as label and struct_name
        respectively, the label node's id should be returned (label has priority)."""
        # node_a: label = "SharedName"
        node_a = Node(
            id="service:NodeA",
            type=NodeType.SERVICE,
            label="SharedName",
        )
        # node_b: struct_name = "SharedName" (but a different node)
        node_b = Node(
            id="service:NodeB",
            type=NodeType.SERVICE,
            label="different_label",
            metadata={"struct_name": "SharedName"},
        )
        result = _make_scan_result([node_a, node_b])
        lookup = _build_name_lookup(result)

        # label always wins
        assert lookup.get("SharedName") == "service:NodeA", (
            "label should have priority over struct_name for the same key"
        )

    def test_class_name_wins_over_nothing(self):
        """class_name is used when neither label nor struct_name match."""
        node = Node(
            id="table:Orders",
            type=NodeType.DATABASE_TABLE,
            label="orders_table",
            metadata={"class_name": "Order"},
        )
        result = _make_scan_result([node])
        lookup = _build_name_lookup(result)
        assert lookup.get("Order") == "table:Orders"

    def test_missing_name_returns_none(self):
        """Lookup for an absent name should return None."""
        node = _make_node("service:Foo", label="Foo")
        result = _make_scan_result([node])
        lookup = _build_name_lookup(result)
        assert lookup.get("DoesNotExist") is None

    def test_empty_scan_result_returns_empty_dict(self):
        result = _make_scan_result([])
        lookup = _build_name_lookup(result)
        assert lookup == {}

    def test_behavioral_equivalence_with_find_node_id_for_name(self):
        """For all names tried, _build_name_lookup.get(name) should return
        the same value as _find_node_id_for_name(result, name)."""
        nodes = [
            Node(
                id="service:Alpha",
                type=NodeType.SERVICE,
                label="Alpha",
            ),
            Node(
                id="service:Beta",
                type=NodeType.SERVICE,
                label="some_label",
                metadata={"struct_name": "BetaStruct"},
            ),
            Node(
                id="table:Gamma",
                type=NodeType.DATABASE_TABLE,
                label="gamma_tbl",
                metadata={"class_name": "GammaModel"},
            ),
        ]
        result = _make_scan_result(nodes)
        lookup = _build_name_lookup(result)

        names_to_try = [
            "Alpha",         # found via label
            "BetaStruct",    # found via struct_name
            "GammaModel",    # found via class_name
            "some_label",    # found via label (node_b's actual label)
            "gamma_tbl",     # found via label (node_c's actual label)
            "NotHere",       # absent
        ]
        for name in names_to_try:
            expected = _find_node_id_for_name(result, name)
            actual = lookup.get(name)
            assert actual == expected, (
                f"Mismatch for name={name!r}: "
                f"_build_name_lookup returned {actual!r}, "
                f"_find_node_id_for_name returned {expected!r}"
            )

    def test_no_struct_name_does_not_add_none_key(self):
        """Nodes without struct_name or class_name metadata should not pollute
        the lookup dict with a None key."""
        node = _make_node("service:Plain", label="Plain")
        result = _make_scan_result([node])
        lookup = _build_name_lookup(result)
        assert None not in lookup


# ---------------------------------------------------------------------------
# 3. TestToDataCaching
# ---------------------------------------------------------------------------


class TestToDataCaching:
    """Verify that ArchGraph.to_data() caches its result and that every
    mutation method invalidates the cache."""

    def test_two_calls_return_same_object(self):
        """Calling to_data() twice without any mutation must return the SAME
        GraphData instance (identity check)."""
        graph = ArchGraph()
        graph.add_node(_make_node("service:A"))

        first = graph.to_data()
        second = graph.to_data()

        assert first is second, "Expected cache hit: both calls should return the same object"

    def test_add_node_invalidates_cache(self):
        """After add_node, to_data() must return a NEW object."""
        graph = ArchGraph()
        graph.add_node(_make_node("service:A"))

        before = graph.to_data()
        graph.add_node(_make_node("service:B"))
        after = graph.to_data()

        assert before is not after, "add_node should invalidate the to_data cache"

    def test_add_node_content_is_correct_after_mutation(self):
        """The new GraphData after add_node should contain the newly added node."""
        graph = ArchGraph()
        graph.add_node(_make_node("service:A"))
        _ = graph.to_data()  # prime the cache

        graph.add_node(_make_node("service:B"))
        data = graph.to_data()

        assert "service:B" in data.nodes, (
            "Freshly added node must appear in to_data() after cache invalidation"
        )

    def test_add_edge_invalidates_cache(self):
        """After add_edge, to_data() must return a NEW object."""
        node_a = _make_node("service:A")
        node_b = _make_node("service:B")
        graph = ArchGraph()
        graph.add_node(node_a)
        graph.add_node(node_b)

        before = graph.to_data()
        graph.add_edge(Edge(source="service:A", target="service:B", type=EdgeType.CALLS))
        after = graph.to_data()

        assert before is not after, "add_edge should invalidate the to_data cache"

    def test_add_edge_content_is_correct_after_mutation(self):
        """The new GraphData after add_edge must include the new edge."""
        graph = ArchGraph()
        graph.add_node(_make_node("service:A"))
        graph.add_node(_make_node("service:B"))
        _ = graph.to_data()  # prime the cache

        new_edge = Edge(source="service:A", target="service:B", type=EdgeType.CALLS)
        graph.add_edge(new_edge)
        data = graph.to_data()

        edge_tuples = [(e.source, e.target, e.type) for e in data.edges]
        assert ("service:A", "service:B", EdgeType.CALLS) in edge_tuples

    def test_remove_node_invalidates_cache(self):
        """After remove_node, to_data() must return a NEW object."""
        graph = ArchGraph()
        graph.add_node(_make_node("service:A"))
        graph.add_node(_make_node("service:B"))

        before = graph.to_data()
        graph.remove_node("service:A")
        after = graph.to_data()

        assert before is not after, "remove_node should invalidate the to_data cache"

    def test_remove_node_content_is_correct_after_mutation(self):
        """The removed node must not appear in to_data() after remove_node."""
        graph = ArchGraph()
        graph.add_node(_make_node("service:A"))
        graph.add_node(_make_node("service:B"))
        _ = graph.to_data()  # prime the cache

        graph.remove_node("service:A")
        data = graph.to_data()

        assert "service:A" not in data.nodes

    def test_merge_manual_annotations_invalidates_cache(self):
        """After merge_manual_annotations, to_data() must return a NEW object."""
        # Build a graph and prime the cache
        graph = ArchGraph()
        graph.add_node(_make_node("service:A"))
        before = graph.to_data()

        # Build old_data with a manual node not yet in the graph
        manual_node = Node(
            id="service:Manual",
            type=NodeType.SERVICE,
            label="Manual",
            manual=True,
        )
        old_data = GraphData(nodes={"service:Manual": manual_node})

        graph.merge_manual_annotations(old_data)
        after = graph.to_data()

        assert before is not after, (
            "merge_manual_annotations should invalidate the to_data cache"
        )

    def test_merge_manual_annotations_content_is_correct_after_mutation(self):
        """The merged manual node must appear in to_data() after merge."""
        graph = ArchGraph()
        graph.add_node(_make_node("service:A"))
        _ = graph.to_data()  # prime the cache

        manual_node = Node(
            id="service:Manual",
            type=NodeType.SERVICE,
            label="Manual",
            manual=True,
        )
        old_data = GraphData(nodes={"service:Manual": manual_node})
        graph.merge_manual_annotations(old_data)

        data = graph.to_data()
        assert "service:Manual" in data.nodes

    def test_cache_is_primed_on_first_call_and_reused(self):
        """A fresh graph primes the cache on the first to_data() call."""
        graph = ArchGraph()
        graph.add_node(_make_node("service:A"))

        # No previous cache
        assert graph._cached_data is None
        first = graph.to_data()
        # Cache is now populated
        assert graph._cached_data is not None
        second = graph.to_data()
        assert first is second


# ---------------------------------------------------------------------------
# 5. TestDriftResponseCap
# ---------------------------------------------------------------------------


class TestDriftResponseCap:
    """Verify that detect_drift caps its output at _MAX_DRIFT_RECORDS + 1
    (the extra item being the truncated summary record)."""

    def test_small_result_is_not_truncated(self, tmp_path):
        """A drift result with <= _MAX_DRIFT_RECORDS records must NOT be truncated."""
        # Put 10 nodes in graph, none in scan
        graph_nodes = [_make_node(f"service:Old{i}") for i in range(10)]
        graph = _make_graph_with_nodes(graph_nodes)
        scan_result = _make_scan_result([])

        with _mock_no_git_renames(), _mock_scan_result(scan_result):
            drifts = detect_drift(graph, str(tmp_path))

        types = [d["type"] for d in drifts]
        assert "truncated" not in types
        assert len(drifts) == 10

    def test_large_result_is_capped_at_max_plus_one(self, tmp_path):
        """A drift result with > _MAX_DRIFT_RECORDS records must be capped at
        exactly _MAX_DRIFT_RECORDS + 1 items (the last being the truncated record)."""
        # Put MAX+50 nodes in graph, none in scan, to produce MAX+50 drift records
        n = _MAX_DRIFT_RECORDS + 50
        graph_nodes = [_make_node(f"service:Old{i}") for i in range(n)]
        graph = _make_graph_with_nodes(graph_nodes)
        scan_result = _make_scan_result([])

        with _mock_no_git_renames(), _mock_scan_result(scan_result):
            drifts = detect_drift(graph, str(tmp_path))

        assert len(drifts) == _MAX_DRIFT_RECORDS + 1, (
            f"Expected {_MAX_DRIFT_RECORDS + 1} records, got {len(drifts)}"
        )

    def test_last_record_is_truncated_type(self, tmp_path):
        """The final record in a capped result must have type='truncated'."""
        n = _MAX_DRIFT_RECORDS + 10
        graph = _make_graph_with_nodes([_make_node(f"service:Old{i}") for i in range(n)])
        scan_result = _make_scan_result([])

        with _mock_no_git_renames(), _mock_scan_result(scan_result):
            drifts = detect_drift(graph, str(tmp_path))

        last = drifts[-1]
        assert last["type"] == "truncated"

    def test_truncated_record_has_total_field(self, tmp_path):
        """The truncated record must carry a 'total' field (as a string)."""
        n = _MAX_DRIFT_RECORDS + 10
        graph = _make_graph_with_nodes([_make_node(f"service:Old{i}") for i in range(n)])
        scan_result = _make_scan_result([])

        with _mock_no_git_renames(), _mock_scan_result(scan_result):
            drifts = detect_drift(graph, str(tmp_path))

        last = drifts[-1]
        assert "total" in last, "truncated record must have a 'total' field"
        assert isinstance(last["total"], str), "'total' must be a string"
        # The total should reflect the actual uncapped count
        assert int(last["total"]) == n

    def test_truncated_record_has_detail_with_per_type_counts(self, tmp_path):
        """The truncated record's 'detail' field should include per-type counts."""
        n = _MAX_DRIFT_RECORDS + 10
        graph = _make_graph_with_nodes([_make_node(f"service:Old{i}") for i in range(n)])
        scan_result = _make_scan_result([])

        with _mock_no_git_renames(), _mock_scan_result(scan_result):
            drifts = detect_drift(graph, str(tmp_path))

        last = drifts[-1]
        assert "detail" in last, "truncated record must have a 'detail' field"
        detail = last["detail"]
        assert isinstance(detail, str)
        # The detail should mention the missing_in_code type since all nodes are missing
        assert "missing_in_code" in detail, (
            f"Expected 'missing_in_code' in detail breakdown; got: {detail!r}"
        )

    def test_first_max_records_are_preserved(self, tmp_path):
        """After truncation, the first _MAX_DRIFT_RECORDS items must not be
        the truncated summary — only the last appended item is the summary."""
        n = _MAX_DRIFT_RECORDS + 10
        graph = _make_graph_with_nodes([_make_node(f"service:Old{i}") for i in range(n)])
        scan_result = _make_scan_result([])

        with _mock_no_git_renames(), _mock_scan_result(scan_result):
            drifts = detect_drift(graph, str(tmp_path))

        # All records before the last should NOT be 'truncated'
        for record in drifts[:-1]:
            assert record["type"] != "truncated", (
                "Only the last record should have type='truncated'"
            )

    def test_exactly_max_records_is_not_truncated(self, tmp_path):
        """Exactly _MAX_DRIFT_RECORDS records must NOT trigger truncation.

        The guard is a strict > check.
        """
        n = _MAX_DRIFT_RECORDS  # exactly 200
        graph = _make_graph_with_nodes([_make_node(f"service:Old{i}") for i in range(n)])
        scan_result = _make_scan_result([])

        with _mock_no_git_renames(), _mock_scan_result(scan_result):
            drifts = detect_drift(graph, str(tmp_path))

        types = [d["type"] for d in drifts]
        assert "truncated" not in types, (
            f"Truncation fired at exactly {n} records — expected > check, not >= check"
        )
        assert len(drifts) == n


# ---------------------------------------------------------------------------
# 4. TestBetweennessCentralityCache (US1)
# ---------------------------------------------------------------------------


def _make_graph_with_edges() -> ArchGraph:
    """Create an ArchGraph with 5 nodes and 4 edges for centrality testing."""
    graph = ArchGraph()
    for i in range(5):
        graph.add_node(_make_node(f"service:N{i}", label=f"N{i}"))
    # Create a chain: N0 -> N1 -> N2 -> N3 -> N4
    for i in range(4):
        graph.add_edge(Edge(
            source=f"service:N{i}",
            target=f"service:N{i+1}",
            type=EdgeType.CALLS,
        ))
    return graph


class TestBetweennessCentralityCache:
    """T005-T009: Betweenness centrality must be cached and invalidated on mutations."""

    def test_betweenness_cache_hit(self):
        """T005: Two calls without mutation return the identical dict object (cache hit)."""
        graph = _make_graph_with_edges()
        first = graph.get_betweenness_centrality()
        second = graph.get_betweenness_centrality()
        assert first is second, (
            "Expected cache hit: get_betweenness_centrality() must return the same dict "
            "object on repeated calls without intervening mutations"
        )

    def test_betweenness_cache_invalidated_on_add_node(self):
        """T006: add_node() must invalidate the betweenness cache."""
        graph = _make_graph_with_edges()
        first = graph.get_betweenness_centrality()
        graph.add_node(_make_node("service:NewNode"))
        second = graph.get_betweenness_centrality()
        assert first is not second, (
            "add_node() must invalidate the betweenness cache; "
            "got the same dict object before and after mutation"
        )

    def test_betweenness_cache_invalidated_on_add_edge(self):
        """T007: add_edge() must invalidate the betweenness cache."""
        graph = _make_graph_with_edges()
        first = graph.get_betweenness_centrality()
        graph.add_edge(Edge(source="service:N0", target="service:N4", type=EdgeType.CALLS))
        second = graph.get_betweenness_centrality()
        assert first is not second, (
            "add_edge() must invalidate the betweenness cache; "
            "got the same dict object before and after mutation"
        )

    def test_betweenness_cache_invalidated_on_remove_node(self):
        """T008: remove_node() must invalidate the betweenness cache."""
        graph = _make_graph_with_edges()
        first = graph.get_betweenness_centrality()
        graph.remove_node("service:N2")
        second = graph.get_betweenness_centrality()
        assert first is not second, (
            "remove_node() must invalidate the betweenness cache; "
            "got the same dict object before and after mutation"
        )

    def test_betweenness_cache_invalidated_by_sync_files_direct_mutation(self, tmp_path):
        """T009: sync_files direct graph mutations must also reset _betweenness_cache."""
        from codegiraffe.scanner import sync_files

        # Create a 2-file project
        (tmp_path / "a.py").write_text("class Alpha:\n    pass\n")
        (tmp_path / "b.py").write_text("class Beta:\n    pass\n")

        # Build a graph with these files
        from codegiraffe.scanner import scan_project
        from codegiraffe.storage import JSONStorage
        scan_result = scan_project(str(tmp_path))

        graph = ArchGraph()
        for node in scan_result.nodes:
            graph.add_node(node)
        for edge in scan_result.edges:
            graph.add_edge(edge)

        # Prime the betweenness cache
        _ = graph.get_betweenness_centrality()
        assert graph._betweenness_cache is not None, "Cache should be populated"

        # Modify a.py and call sync_files — this uses direct graph mutations
        (tmp_path / "a.py").write_text("class AlphaModified:\n    pass\n")
        sync_files(graph, str(tmp_path), [str(tmp_path / "a.py")])

        # The cache must have been cleared by sync_files
        assert graph._betweenness_cache is None, (
            "sync_files() must reset _betweenness_cache after direct graph mutations"
        )


# ---------------------------------------------------------------------------
# 6. TestInferCallEdgesNoLinearScan (Phase 6 / FR-010)
# ---------------------------------------------------------------------------


class TestInferCallEdgesNoLinearScan:
    """T032: _infer_call_edges must complete under 1 second on 1000 nodes."""

    def test_infer_call_edges_no_linear_scan(self):
        """_infer_call_edges with 1000 nodes and 100 calls must finish in < 1 second."""
        import time
        from codegiraffe.scanner import _infer_call_edges
        from codegiraffe.scanner import ScanResult, CallInfo
        from codegiraffe.graph import Node, Edge

        # Build a ScanResult with 1000 module nodes
        nodes = [
            Node(
                id=f"mod:module_{i}",
                type="module",
                label=f"module_{i}",
                file_path=f"module_{i}.py",
            )
            for i in range(1000)
        ]

        # Add some service nodes as callee targets
        for i in range(0, 100, 10):
            nodes.append(Node(
                id=f"service:Svc{i}",
                type="service",
                label=f"Svc{i}",
                file_path=f"module_{i}.py",
                metadata={"struct_name": f"Svc{i}"},
            ))

        # Build 100 CallInfo records (each referencing a service node)
        calls = [
            CallInfo(
                caller=f"module_{i * 10}",
                callee=f"Svc{i * 10}",
                receiver=f"Svc{i * 10}",
                file_path=f"module_{i * 10}.py",
            )
            for i in range(10)
        ]

        result = ScanResult(nodes=nodes, calls=calls)

        start = time.monotonic()
        _infer_call_edges(result)
        elapsed = time.monotonic() - start

        assert elapsed < 1.0, (
            f"_infer_call_edges took {elapsed:.3f}s on 1000 nodes — must be under 1.0s"
        )

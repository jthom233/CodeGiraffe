"""Tests for the graph data model (codegiraffe.graph)."""

import pytest
from codegiraffe.graph import Node, Edge, GraphData, ArchGraph
from codegiraffe.schema import NodeType, EdgeType


class TestNodeCreation:
    """test_node_creation -- create a Node, verify fields."""

    def test_node_creation(self):
        node = Node(
            id="endpoint:/api/health",
            type=NodeType.ENDPOINT,
            label="GET /api/health",
            metadata={"method": "GET"},
            file_path="app.py",
        )
        assert node.id == "endpoint:/api/health"
        assert node.type == NodeType.ENDPOINT
        assert node.label == "GET /api/health"
        assert node.metadata == {"method": "GET"}
        assert node.file_path == "app.py"
        assert node.manual is False

    def test_node_defaults(self):
        node = Node(id="table:orders", type=NodeType.DATABASE_TABLE, label="orders")
        assert node.metadata == {}
        assert node.file_path is None
        assert node.manual is False

    def test_node_manual_flag(self):
        node = Node(
            id="service:legacy",
            type=NodeType.SERVICE,
            label="Legacy Service",
            manual=True,
        )
        assert node.manual is True


class TestEdgeCreation:
    """test_edge_creation -- create an Edge, verify fields."""

    def test_edge_creation(self):
        edge = Edge(
            source="endpoint:/api/users",
            target="table:users",
            type=EdgeType.READS,
            metadata={"inferred": True},
        )
        assert edge.source == "endpoint:/api/users"
        assert edge.target == "table:users"
        assert edge.type == EdgeType.READS
        assert edge.metadata == {"inferred": True}
        assert edge.manual is False

    def test_edge_defaults(self):
        edge = Edge(
            source="worker:send_email",
            target="queue:notifications",
            type=EdgeType.PUBLISHES,
        )
        assert edge.metadata == {}
        assert edge.manual is False

    def test_edge_manual_flag(self):
        edge = Edge(
            source="service:A",
            target="service:B",
            type=EdgeType.CALLS,
            manual=True,
        )
        assert edge.manual is True


class TestArchGraphAddNode:
    """test_add_node -- add to ArchGraph, verify it's in to_data()."""

    def test_add_node(self):
        graph = ArchGraph()
        node = Node(id="table:orders", type=NodeType.DATABASE_TABLE, label="orders")
        graph.add_node(node)

        data = graph.to_data()
        assert "table:orders" in data.nodes
        assert data.nodes["table:orders"].label == "orders"
        assert data.nodes["table:orders"].type == NodeType.DATABASE_TABLE

    def test_add_node_replaces_existing(self):
        graph = ArchGraph()
        node_v1 = Node(id="table:orders", type=NodeType.DATABASE_TABLE, label="orders v1")
        node_v2 = Node(id="table:orders", type=NodeType.DATABASE_TABLE, label="orders v2")

        graph.add_node(node_v1)
        graph.add_node(node_v2)

        data = graph.to_data()
        assert len(data.nodes) == 1
        assert data.nodes["table:orders"].label == "orders v2"

    def test_add_multiple_nodes(self, sample_nodes):
        graph = ArchGraph()
        for node in sample_nodes:
            graph.add_node(node)

        data = graph.to_data()
        assert len(data.nodes) == len(sample_nodes)
        for node in sample_nodes:
            assert node.id in data.nodes


class TestArchGraphAddEdge:
    """test_add_edge -- add edge, verify in to_data()."""

    def test_add_edge(self, sample_nodes):
        graph = ArchGraph()
        for node in sample_nodes:
            graph.add_node(node)

        edge = Edge(
            source="endpoint:/api/users",
            target="table:users",
            type=EdgeType.READS,
        )
        graph.add_edge(edge)

        data = graph.to_data()
        assert len(data.edges) == 1
        assert data.edges[0].source == "endpoint:/api/users"
        assert data.edges[0].target == "table:users"
        assert data.edges[0].type == EdgeType.READS

    def test_add_edge_creates_missing_endpoints(self):
        """Adding an edge whose source/target don't exist yet should not crash."""
        graph = ArchGraph()
        edge = Edge(source="a", target="b", type=EdgeType.CALLS)
        graph.add_edge(edge)

        data = graph.to_data()
        assert len(data.edges) == 1
        # The bare endpoint nodes exist in networkx but not as Node objects
        assert "a" in graph.graph
        assert "b" in graph.graph


class TestArchGraphAddEdgeUpdatesExisting:
    """test_add_edge_updates_existing -- add same source+target+type twice,
    verify only one edge with updated metadata."""

    def test_add_edge_updates_existing(self):
        graph = ArchGraph()
        node_a = Node(id="service:A", type=NodeType.SERVICE, label="A")
        node_b = Node(id="service:B", type=NodeType.SERVICE, label="B")
        graph.add_node(node_a)
        graph.add_node(node_b)

        edge_v1 = Edge(
            source="service:A",
            target="service:B",
            type=EdgeType.CALLS,
            metadata={"version": 1},
        )
        edge_v2 = Edge(
            source="service:A",
            target="service:B",
            type=EdgeType.CALLS,
            metadata={"version": 2},
        )

        graph.add_edge(edge_v1)
        graph.add_edge(edge_v2)

        data = graph.to_data()
        assert len(data.edges) == 1
        assert data.edges[0].metadata == {"version": 2}


class TestArchGraphMultipleEdgesPreserved:
    """MultiDiGraph correctness: multiple edge types between the same node pair
    must all be preserved (the original DiGraph silently dropped all but the last)."""

    def test_parallel_edges_different_types_both_preserved(self):
        """Adding two edges with different types between the same pair keeps both."""
        graph = ArchGraph()
        node_a = Node(id="mod:app", type="module", label="app")
        node_b = Node(id="service:Svc", type="service", label="Svc")
        graph.add_node(node_a)
        graph.add_node(node_b)

        edge_contains = Edge(source="mod:app", target="service:Svc", type=EdgeType.CONTAINS)
        edge_calls = Edge(source="mod:app", target="service:Svc", type=EdgeType.CALLS)
        graph.add_edge(edge_contains)
        graph.add_edge(edge_calls)

        data = graph.to_data()
        edge_types = {e.type for e in data.edges}
        assert EdgeType.CONTAINS in edge_types, "contains edge was dropped"
        assert EdgeType.CALLS in edge_types, "calls edge was dropped"
        assert len(data.edges) == 2

    def test_parallel_edges_roundtrip(self):
        """Parallel edges survive a to_data() -> ArchGraph(data) roundtrip."""
        graph = ArchGraph()
        graph.add_node(Node(id="A", type="service", label="A"))
        graph.add_node(Node(id="B", type="service", label="B"))
        graph.add_edge(Edge(source="A", target="B", type=EdgeType.CALLS))
        graph.add_edge(Edge(source="A", target="B", type=EdgeType.IMPORTS))

        data = graph.to_data()
        restored = ArchGraph(data)
        restored_data = restored.to_data()

        edge_types = {e.type for e in restored_data.edges}
        assert EdgeType.CALLS in edge_types
        assert EdgeType.IMPORTS in edge_types
        assert len(restored_data.edges) == 2

    def test_same_type_same_pair_updates_not_duplicates(self):
        """Adding the same (source, target, type) twice updates, does not duplicate."""
        graph = ArchGraph()
        graph.add_node(Node(id="A", type="service", label="A"))
        graph.add_node(Node(id="B", type="service", label="B"))
        graph.add_edge(Edge(source="A", target="B", type=EdgeType.CALLS, metadata={"v": 1}))
        graph.add_edge(Edge(source="A", target="B", type=EdgeType.CALLS, metadata={"v": 2}))

        data = graph.to_data()
        calls_edges = [e for e in data.edges if e.type == EdgeType.CALLS]
        assert len(calls_edges) == 1
        assert calls_edges[0].metadata == {"v": 2}


class TestArchGraphRemoveNode:
    """test_remove_node -- remove a node, verify its edges are also removed."""

    def test_remove_node(self, sample_graph):
        # endpoint:/api/users has edges to table:users and service:AuthService
        sample_graph.remove_node("endpoint:/api/users")

        data = sample_graph.to_data()
        assert "endpoint:/api/users" not in data.nodes

        # All edges involving the removed node should be gone
        for edge in data.edges:
            assert edge.source != "endpoint:/api/users"
            assert edge.target != "endpoint:/api/users"

    def test_remove_nonexistent_node(self, sample_graph):
        """Removing a node that doesn't exist should be a no-op."""
        original_data = sample_graph.to_data()
        sample_graph.remove_node("nonexistent:node")
        new_data = sample_graph.to_data()

        assert len(new_data.nodes) == len(original_data.nodes)
        assert len(new_data.edges) == len(original_data.edges)


class TestGetSubgraph:
    """test_get_subgraph -- get subgraph with depth=1, verify only neighbors returned."""

    def test_get_subgraph_depth_1(self, sample_graph):
        subgraph = sample_graph.get_subgraph("endpoint:/api/users", depth=1)

        # endpoint:/api/users connects to table:users and service:AuthService
        assert "endpoint:/api/users" in subgraph.nodes
        assert "table:users" in subgraph.nodes
        assert "service:AuthService" in subgraph.nodes

        # Nodes NOT directly connected should be absent
        assert "endpoint:/api/payments" not in subgraph.nodes
        assert "worker:send_email" not in subgraph.nodes
        assert "queue:notifications" not in subgraph.nodes

    def test_get_subgraph_nonexistent_node(self, sample_graph):
        """Querying a nonexistent node returns an empty GraphData."""
        subgraph = sample_graph.get_subgraph("nonexistent:node", depth=1)
        assert len(subgraph.nodes) == 0
        assert len(subgraph.edges) == 0


class TestGetSubgraphDepth2:
    """test_get_subgraph_depth_2 -- get subgraph with depth=2,
    verify 2-hop neighbors."""

    def test_get_subgraph_depth_2(self, sample_graph):
        subgraph = sample_graph.get_subgraph("endpoint:/api/users", depth=2)

        # Depth 0: endpoint:/api/users
        assert "endpoint:/api/users" in subgraph.nodes

        # Depth 1: table:users, service:AuthService
        assert "table:users" in subgraph.nodes
        assert "service:AuthService" in subgraph.nodes

        # Depth 2: env:DATABASE_URL (via service:AuthService -> env:DATABASE_URL)
        assert "env:DATABASE_URL" in subgraph.nodes

    def test_subgraph_includes_edges_between_visited_nodes(self, sample_graph):
        subgraph = sample_graph.get_subgraph("endpoint:/api/users", depth=2)

        edge_keys = {(e.source, e.target, e.type) for e in subgraph.edges}
        # These edges should be included
        assert ("endpoint:/api/users", "table:users", EdgeType.READS) in edge_keys
        assert ("endpoint:/api/users", "service:AuthService", EdgeType.CALLS) in edge_keys
        assert ("service:AuthService", "env:DATABASE_URL", EdgeType.DEPENDS_ON) in edge_keys


class TestGetNodesByType:
    """test_get_nodes_by_type -- filter by type, verify correct nodes returned."""

    def test_get_nodes_by_type_endpoints(self, sample_graph):
        endpoints = sample_graph.get_nodes_by_type(NodeType.ENDPOINT)
        assert len(endpoints) == 2
        endpoint_ids = {n.id for n in endpoints}
        assert "endpoint:/api/users" in endpoint_ids
        assert "endpoint:/api/payments" in endpoint_ids

    def test_get_nodes_by_type_tables(self, sample_graph):
        tables = sample_graph.get_nodes_by_type(NodeType.DATABASE_TABLE)
        assert len(tables) == 2
        table_ids = {n.id for n in tables}
        assert "table:users" in table_ids
        assert "table:payments" in table_ids

    def test_get_nodes_by_type_no_match(self, sample_graph):
        configs = sample_graph.get_nodes_by_type(NodeType.CONFIG)
        assert len(configs) == 0

    def test_get_nodes_by_type_single_match(self, sample_graph):
        workers = sample_graph.get_nodes_by_type(NodeType.WORKER)
        assert len(workers) == 1
        assert workers[0].id == "worker:send_email"


class TestGetHotspots:
    """test_get_hotspots -- verify most-connected nodes ranked first."""

    def test_get_hotspots(self, sample_graph):
        hotspots = sample_graph.get_hotspots(top_n=3)

        assert len(hotspots) > 0
        # Each item should be a (Node, score) tuple
        for node, score in hotspots:
            assert isinstance(node, Node)
            assert isinstance(score, float)

        # Scores should be in descending order
        scores = [s for _, s in hotspots]
        assert scores == sorted(scores, reverse=True)

    def test_get_hotspots_most_connected_first(self, sample_graph):
        hotspots = sample_graph.get_hotspots(top_n=10)
        # endpoint:/api/users has 2 outgoing edges (table:users, service:AuthService)
        # endpoint:/api/payments has 2 outgoing edges (table:payments, worker:send_email)
        # These should rank among the top
        top_ids = [node.id for node, _ in hotspots[:4]]
        assert "endpoint:/api/users" in top_ids
        assert "endpoint:/api/payments" in top_ids

    def test_get_hotspots_top_n_limit(self, sample_graph):
        hotspots = sample_graph.get_hotspots(top_n=2)
        assert len(hotspots) <= 2


class TestMergeManualAnnotations:
    """test_merge_manual_annotations -- add manual nodes/edges, rescan,
    verify they survive merge."""

    def test_merge_manual_annotations(self):
        # Simulate a scanned graph (non-manual)
        scanned_graph = ArchGraph()
        scanned_graph.add_node(
            Node(id="endpoint:/api/users", type=NodeType.ENDPOINT, label="/api/users")
        )

        # Old graph had a manual annotation
        old_data = GraphData(
            nodes={
                "service:ManualService": Node(
                    id="service:ManualService",
                    type=NodeType.SERVICE,
                    label="Manual Service",
                    manual=True,
                ),
                "endpoint:/api/users": Node(
                    id="endpoint:/api/users",
                    type=NodeType.ENDPOINT,
                    label="/api/users",
                ),
            },
            edges=[
                Edge(
                    source="endpoint:/api/users",
                    target="service:ManualService",
                    type=EdgeType.CALLS,
                    manual=True,
                ),
            ],
        )

        scanned_graph.merge_manual_annotations(old_data)
        data = scanned_graph.to_data()

        # The manual node should be preserved
        assert "service:ManualService" in data.nodes
        assert data.nodes["service:ManualService"].manual is True

        # The manual edge should be preserved
        manual_edges = [e for e in data.edges if e.manual]
        assert len(manual_edges) == 1
        assert manual_edges[0].source == "endpoint:/api/users"
        assert manual_edges[0].target == "service:ManualService"

    def test_merge_preserves_only_manual(self):
        """Non-manual nodes from old data should NOT be re-added."""
        scanned_graph = ArchGraph()

        old_data = GraphData(
            nodes={
                "endpoint:/api/old": Node(
                    id="endpoint:/api/old",
                    type=NodeType.ENDPOINT,
                    label="old endpoint",
                    manual=False,
                ),
                "service:ManualSvc": Node(
                    id="service:ManualSvc",
                    type=NodeType.SERVICE,
                    label="Manual",
                    manual=True,
                ),
            },
            edges=[],
        )

        scanned_graph.merge_manual_annotations(old_data)
        data = scanned_graph.to_data()

        assert "service:ManualSvc" in data.nodes
        assert "endpoint:/api/old" not in data.nodes


class TestToDataRoundtrip:
    """test_to_data_roundtrip -- to_data then back to ArchGraph, verify equivalent."""

    def test_to_data_roundtrip(self, sample_graph):
        data = sample_graph.to_data()
        restored = ArchGraph(data)
        restored_data = restored.to_data()

        # Same nodes
        assert set(data.nodes.keys()) == set(restored_data.nodes.keys())
        for nid in data.nodes:
            assert data.nodes[nid].id == restored_data.nodes[nid].id
            assert data.nodes[nid].type == restored_data.nodes[nid].type
            assert data.nodes[nid].label == restored_data.nodes[nid].label

        # Same edges (compare as sets of tuples for order-independence)
        original_edge_keys = {(e.source, e.target, e.type) for e in data.edges}
        restored_edge_keys = {(e.source, e.target, e.type) for e in restored_data.edges}
        assert original_edge_keys == restored_edge_keys

    def test_roundtrip_empty_graph(self):
        graph = ArchGraph()
        data = graph.to_data()
        restored = ArchGraph(data)
        restored_data = restored.to_data()

        assert len(restored_data.nodes) == 0
        assert len(restored_data.edges) == 0

    def test_roundtrip_preserves_metadata(self):
        graph = ArchGraph()
        node = Node(
            id="service:X",
            type=NodeType.SERVICE,
            label="X",
            metadata={"version": "2.0", "team": "platform"},
            file_path="services/x.py",
        )
        graph.add_node(node)

        data = graph.to_data()
        restored = ArchGraph(data)
        restored_data = restored.to_data()

        assert restored_data.nodes["service:X"].metadata == {"version": "2.0", "team": "platform"}
        assert restored_data.nodes["service:X"].file_path == "services/x.py"


class TestGetAllDescendants:
    """Tests for ArchGraph.get_all_descendants()."""

    def test_happy_path(self):
        g = ArchGraph()
        g.add_node(Node(id="A", type=NodeType.SERVICE, label="A"))
        g.add_node(Node(id="B", type=NodeType.SERVICE, label="B"))
        g.add_node(Node(id="C", type=NodeType.SERVICE, label="C"))
        g.add_node(Node(id="D", type=NodeType.SERVICE, label="D"))
        g.add_edge(Edge(source="A", target="B", type=EdgeType.CALLS))
        g.add_edge(Edge(source="B", target="C", type=EdgeType.CALLS))
        g.add_edge(Edge(source="C", target="D", type=EdgeType.CALLS))
        assert g.get_all_descendants("A") == {"B", "C", "D"}

    def test_missing_node(self):
        g = ArchGraph()
        assert g.get_all_descendants("nonexistent") == set()

    def test_no_descendants(self):
        g = ArchGraph()
        g.add_node(Node(id="A", type=NodeType.SERVICE, label="A"))
        g.add_node(Node(id="B", type=NodeType.SERVICE, label="B"))
        g.add_edge(Edge(source="A", target="B", type=EdgeType.CALLS))
        assert g.get_all_descendants("B") == set()

    def test_cyclic_graph(self):
        g = ArchGraph()
        g.add_node(Node(id="A", type=NodeType.SERVICE, label="A"))
        g.add_node(Node(id="B", type=NodeType.SERVICE, label="B"))
        g.add_node(Node(id="C", type=NodeType.SERVICE, label="C"))
        g.add_edge(Edge(source="A", target="B", type=EdgeType.CALLS))
        g.add_edge(Edge(source="B", target="C", type=EdgeType.CALLS))
        g.add_edge(Edge(source="C", target="A", type=EdgeType.CALLS))
        assert g.get_all_descendants("A") == {"B", "C"}


class TestGetAllAncestors:
    """Tests for ArchGraph.get_all_ancestors()."""

    def test_happy_path(self):
        g = ArchGraph()
        g.add_node(Node(id="A", type=NodeType.SERVICE, label="A"))
        g.add_node(Node(id="B", type=NodeType.SERVICE, label="B"))
        g.add_node(Node(id="C", type=NodeType.SERVICE, label="C"))
        g.add_node(Node(id="D", type=NodeType.SERVICE, label="D"))
        g.add_edge(Edge(source="A", target="B", type=EdgeType.CALLS))
        g.add_edge(Edge(source="B", target="C", type=EdgeType.CALLS))
        g.add_edge(Edge(source="C", target="D", type=EdgeType.CALLS))
        assert g.get_all_ancestors("D") == {"A", "B", "C"}

    def test_missing_node(self):
        g = ArchGraph()
        assert g.get_all_ancestors("nonexistent") == set()

    def test_no_ancestors(self):
        g = ArchGraph()
        g.add_node(Node(id="A", type=NodeType.SERVICE, label="A"))
        g.add_node(Node(id="B", type=NodeType.SERVICE, label="B"))
        g.add_edge(Edge(source="A", target="B", type=EdgeType.CALLS))
        assert g.get_all_ancestors("A") == set()

    def test_cyclic_graph(self):
        g = ArchGraph()
        g.add_node(Node(id="A", type=NodeType.SERVICE, label="A"))
        g.add_node(Node(id="B", type=NodeType.SERVICE, label="B"))
        g.add_node(Node(id="C", type=NodeType.SERVICE, label="C"))
        g.add_edge(Edge(source="A", target="B", type=EdgeType.CALLS))
        g.add_edge(Edge(source="B", target="C", type=EdgeType.CALLS))
        g.add_edge(Edge(source="C", target="A", type=EdgeType.CALLS))
        assert g.get_all_ancestors("A") == {"B", "C"}


class TestFindPaths:
    """Tests for ArchGraph.find_paths()."""

    def test_single_path(self):
        g = ArchGraph()
        g.add_node(Node(id="A", type=NodeType.SERVICE, label="A"))
        g.add_node(Node(id="B", type=NodeType.SERVICE, label="B"))
        g.add_node(Node(id="C", type=NodeType.SERVICE, label="C"))
        g.add_edge(Edge(source="A", target="B", type=EdgeType.CALLS))
        g.add_edge(Edge(source="B", target="C", type=EdgeType.CALLS))
        paths = g.find_paths("A", "C")
        assert paths == [["A", "B", "C"]]

    def test_multiple_paths(self):
        g = ArchGraph()
        g.add_node(Node(id="A", type=NodeType.SERVICE, label="A"))
        g.add_node(Node(id="B", type=NodeType.SERVICE, label="B"))
        g.add_node(Node(id="C", type=NodeType.SERVICE, label="C"))
        g.add_node(Node(id="D", type=NodeType.SERVICE, label="D"))
        g.add_edge(Edge(source="A", target="B", type=EdgeType.CALLS))
        g.add_edge(Edge(source="A", target="C", type=EdgeType.CALLS))
        g.add_edge(Edge(source="B", target="D", type=EdgeType.CALLS))
        g.add_edge(Edge(source="C", target="D", type=EdgeType.CALLS))
        paths = g.find_paths("A", "D")
        assert len(paths) == 2
        assert ["A", "B", "D"] in paths
        assert ["A", "C", "D"] in paths

    def test_no_path(self):
        g = ArchGraph()
        g.add_node(Node(id="A", type=NodeType.SERVICE, label="A"))
        g.add_node(Node(id="B", type=NodeType.SERVICE, label="B"))
        # No edges -- disconnected
        assert g.find_paths("A", "B") == []

    def test_missing_node(self):
        g = ArchGraph()
        g.add_node(Node(id="A", type=NodeType.SERVICE, label="A"))
        assert g.find_paths("A", "nonexistent") == []

    def test_max_depth(self):
        g = ArchGraph()
        g.add_node(Node(id="A", type=NodeType.SERVICE, label="A"))
        g.add_node(Node(id="B", type=NodeType.SERVICE, label="B"))
        g.add_node(Node(id="C", type=NodeType.SERVICE, label="C"))
        g.add_edge(Edge(source="A", target="B", type=EdgeType.CALLS))
        g.add_edge(Edge(source="B", target="C", type=EdgeType.CALLS))
        # Path A->B->C is 2 hops; max_depth=1 should miss it
        assert g.find_paths("A", "C", max_depth=1) == []


class TestDetectCycles:
    """Tests for ArchGraph.detect_cycles()."""

    def test_no_cycles(self):
        g = ArchGraph()
        g.add_node(Node(id="A", type=NodeType.SERVICE, label="A"))
        g.add_node(Node(id="B", type=NodeType.SERVICE, label="B"))
        g.add_node(Node(id="C", type=NodeType.SERVICE, label="C"))
        g.add_edge(Edge(source="A", target="B", type=EdgeType.CALLS))
        g.add_edge(Edge(source="B", target="C", type=EdgeType.CALLS))
        assert g.detect_cycles() == []

    def test_simple_cycle(self):
        g = ArchGraph()
        g.add_node(Node(id="A", type=NodeType.SERVICE, label="A"))
        g.add_node(Node(id="B", type=NodeType.SERVICE, label="B"))
        g.add_node(Node(id="C", type=NodeType.SERVICE, label="C"))
        g.add_edge(Edge(source="A", target="B", type=EdgeType.CALLS))
        g.add_edge(Edge(source="B", target="C", type=EdgeType.CALLS))
        g.add_edge(Edge(source="C", target="A", type=EdgeType.CALLS))
        cycles = g.detect_cycles()
        assert len(cycles) == 1
        # The cycle contains exactly {A, B, C} regardless of rotation
        assert set(cycles[0]) == {"A", "B", "C"}

    def test_multiple_cycles(self):
        g = ArchGraph()
        # Cycle 1: A -> B -> A
        g.add_node(Node(id="A", type=NodeType.SERVICE, label="A"))
        g.add_node(Node(id="B", type=NodeType.SERVICE, label="B"))
        g.add_edge(Edge(source="A", target="B", type=EdgeType.CALLS))
        g.add_edge(Edge(source="B", target="A", type=EdgeType.CALLS))
        # Cycle 2: C -> D -> E -> C
        g.add_node(Node(id="C", type=NodeType.SERVICE, label="C"))
        g.add_node(Node(id="D", type=NodeType.SERVICE, label="D"))
        g.add_node(Node(id="E", type=NodeType.SERVICE, label="E"))
        g.add_edge(Edge(source="C", target="D", type=EdgeType.CALLS))
        g.add_edge(Edge(source="D", target="E", type=EdgeType.CALLS))
        g.add_edge(Edge(source="E", target="C", type=EdgeType.CALLS))
        cycles = g.detect_cycles()
        assert len(cycles) == 2
        # Sorted by length: 2-node cycle first, 3-node cycle second
        assert len(cycles[0]) == 2
        assert len(cycles[1]) == 3

    def test_max_cycles_cap(self):
        g = ArchGraph()
        # Build a complete graph on 5 nodes -- many cycles
        ids = ["N0", "N1", "N2", "N3", "N4"]
        for nid in ids:
            g.add_node(Node(id=nid, type=NodeType.SERVICE, label=nid))
        for i, src in enumerate(ids):
            for j, tgt in enumerate(ids):
                if i != j:
                    g.add_edge(Edge(source=src, target=tgt, type=EdgeType.CALLS))
        cycles = g.detect_cycles(max_cycles=3)
        assert len(cycles) == 3


class TestGetBetweennessCentrality:
    """Tests for ArchGraph.get_betweenness_centrality()."""

    def test_happy_path(self):
        g = ArchGraph()
        g.add_node(Node(id="A", type=NodeType.SERVICE, label="A"))
        g.add_node(Node(id="B", type=NodeType.SERVICE, label="B"))
        g.add_node(Node(id="C", type=NodeType.SERVICE, label="C"))
        g.add_edge(Edge(source="A", target="B", type=EdgeType.CALLS))
        g.add_edge(Edge(source="B", target="C", type=EdgeType.CALLS))
        result = g.get_betweenness_centrality()
        assert isinstance(result, dict)
        assert set(result.keys()) == {"A", "B", "C"}
        for v in result.values():
            assert isinstance(v, float)

    def test_empty_graph(self):
        g = ArchGraph()
        assert g.get_betweenness_centrality() == {}

    def test_bottleneck(self):
        # Diamond: A -> B -> D, A -> C -> D
        # B and C sit on shortest paths, should have higher centrality than A or D
        g = ArchGraph()
        g.add_node(Node(id="A", type=NodeType.SERVICE, label="A"))
        g.add_node(Node(id="B", type=NodeType.SERVICE, label="B"))
        g.add_node(Node(id="C", type=NodeType.SERVICE, label="C"))
        g.add_node(Node(id="D", type=NodeType.SERVICE, label="D"))
        g.add_edge(Edge(source="A", target="B", type=EdgeType.CALLS))
        g.add_edge(Edge(source="A", target="C", type=EdgeType.CALLS))
        g.add_edge(Edge(source="B", target="D", type=EdgeType.CALLS))
        g.add_edge(Edge(source="C", target="D", type=EdgeType.CALLS))
        result = g.get_betweenness_centrality()
        # In a diamond, the middle nodes (B, C) should have centrality >= edge nodes (A, D)
        assert result["B"] >= result["A"]
        assert result["C"] >= result["A"]
        assert result["B"] >= result["D"]
        assert result["C"] >= result["D"]


class TestGraphDataLayoutField:
    """Tests for the GraphData.layout field (TDD RED phase — field does not exist yet)."""

    def test_layout_defaults_to_empty_dict(self):
        """GraphData constructed with minimal args should expose layout == {}."""
        data = GraphData(nodes={}, edges=[], project_path="test")
        assert data.layout == {}

    def test_layout_round_trips_through_json_serialization(self):
        """layout values survive model_dump / model_validate round-trip."""
        original = GraphData(
            nodes={},
            edges=[],
            project_path="test",
            layout={"node1": [0.5, -0.3]},
        )
        raw = original.model_dump()
        restored = GraphData.model_validate(raw)
        assert restored.layout == {"node1": [0.5, -0.3]}

    def test_layout_backward_compat_missing_key_loads_as_empty_dict(self):
        """Existing stored JSON without a 'layout' key loads without error
        and yields layout == {} (backward compatibility)."""
        stored = {
            "nodes": {},
            "edges": [],
            "project_path": "legacy_project",
        }
        data = GraphData.model_validate(stored)
        assert data.layout == {}


class TestMultiDiGraphMigration:
    """Tests for MultiDiGraph migration — multiple edge types between same node pair."""

    # T003
    def test_multi_edge_types_preserved(self):
        """Two edges between same (source, target) with different types must both exist."""
        graph = ArchGraph()
        graph.add_node(Node(id="module:A", type=NodeType.MODULE, label="A"))
        graph.add_node(Node(id="module:B", type=NodeType.MODULE, label="B"))

        edge_contains = Edge(source="module:A", target="module:B", type=EdgeType.CONTAINS)
        edge_imports = Edge(source="module:A", target="module:B", type=EdgeType.IMPORTS)

        graph.add_edge(edge_contains)
        graph.add_edge(edge_imports)

        data = graph.to_data()
        assert len(data.edges) == 2
        edge_types = {e.type for e in data.edges}
        assert EdgeType.CONTAINS in edge_types
        assert EdgeType.IMPORTS in edge_types

    # T004
    def test_add_edge_same_type_is_idempotent(self):
        """Adding the same edge type between same pair twice updates, does not duplicate."""
        graph = ArchGraph()
        graph.add_node(Node(id="module:A", type=NodeType.MODULE, label="A"))
        graph.add_node(Node(id="module:B", type=NodeType.MODULE, label="B"))

        edge_v1 = Edge(
            source="module:A",
            target="module:B",
            type=EdgeType.IMPORTS,
            metadata={"version": 1},
        )
        edge_v2 = Edge(
            source="module:A",
            target="module:B",
            type=EdgeType.IMPORTS,
            metadata={"version": 2},
        )

        graph.add_edge(edge_v1)
        graph.add_edge(edge_v2)

        data = graph.to_data()
        assert len(data.edges) == 1
        assert data.edges[0].metadata == {"version": 2}

    # T005
    def test_to_data_returns_all_multi_edges(self):
        """to_data() must return exact count when multiple edge types exist."""
        graph = ArchGraph()
        graph.add_node(Node(id="A", type=NodeType.SERVICE, label="A"))
        graph.add_node(Node(id="B", type=NodeType.SERVICE, label="B"))
        graph.add_node(Node(id="C", type=NodeType.SERVICE, label="C"))

        # A->B: two types
        graph.add_edge(Edge(source="A", target="B", type=EdgeType.CALLS))
        graph.add_edge(Edge(source="A", target="B", type=EdgeType.IMPORTS))
        # B->C: one type
        graph.add_edge(Edge(source="B", target="C", type=EdgeType.CALLS))
        # A->C: one type
        graph.add_edge(Edge(source="A", target="C", type=EdgeType.DEPENDS_ON))

        data = graph.to_data()
        assert len(data.edges) == 4

    # T006
    def test_get_subgraph_includes_all_edge_types(self):
        """get_subgraph() must return all edge types within the subgraph."""
        graph = ArchGraph()
        graph.add_node(Node(id="module:A", type=NodeType.MODULE, label="A"))
        graph.add_node(Node(id="module:B", type=NodeType.MODULE, label="B"))
        graph.add_node(Node(id="module:C", type=NodeType.MODULE, label="C"))

        graph.add_edge(Edge(source="module:A", target="module:B", type=EdgeType.CONTAINS))
        graph.add_edge(Edge(source="module:A", target="module:B", type=EdgeType.IMPORTS))
        graph.add_edge(Edge(source="module:B", target="module:C", type=EdgeType.CALLS))

        subgraph = graph.get_subgraph("module:A", depth=2)

        edge_keys = {(e.source, e.target, e.type) for e in subgraph.edges}
        assert ("module:A", "module:B", EdgeType.CONTAINS) in edge_keys
        assert ("module:A", "module:B", EdgeType.IMPORTS) in edge_keys
        assert ("module:B", "module:C", EdgeType.CALLS) in edge_keys

    # T007
    def test_get_edge_between_returns_any_edge(self):
        """get_edge_between returns an Edge when edges exist, None when they don't."""
        graph = ArchGraph()
        graph.add_node(Node(id="A", type=NodeType.SERVICE, label="A"))
        graph.add_node(Node(id="B", type=NodeType.SERVICE, label="B"))
        graph.add_node(Node(id="C", type=NodeType.SERVICE, label="C"))

        graph.add_edge(Edge(source="A", target="B", type=EdgeType.CALLS))

        result = graph.get_edge_between("A", "B")
        assert result is not None
        assert isinstance(result, Edge)
        assert result.source == "A"
        assert result.target == "B"

        # Non-existent pair
        assert graph.get_edge_between("A", "C") is None
        # Non-existent node
        assert graph.get_edge_between("A", "nonexistent") is None

    # T008
    def test_get_typed_edge_returns_specific_type(self):
        """get_typed_edge returns the correct typed edge, None for non-existent type."""
        graph = ArchGraph()
        graph.add_node(Node(id="A", type=NodeType.MODULE, label="A"))
        graph.add_node(Node(id="B", type=NodeType.MODULE, label="B"))

        graph.add_edge(Edge(source="A", target="B", type=EdgeType.CONTAINS))
        graph.add_edge(Edge(source="A", target="B", type=EdgeType.IMPORTS))

        contains_edge = graph.get_typed_edge("A", "B", EdgeType.CONTAINS)
        assert contains_edge is not None
        assert contains_edge.type == EdgeType.CONTAINS

        imports_edge = graph.get_typed_edge("A", "B", EdgeType.IMPORTS)
        assert imports_edge is not None
        assert imports_edge.type == EdgeType.IMPORTS

        # Type that doesn't exist between this pair
        assert graph.get_typed_edge("A", "B", EdgeType.CALLS) is None
        # Non-existent node
        assert graph.get_typed_edge("A", "nonexistent", EdgeType.CALLS) is None

    # T009
    def test_get_all_edges_between(self):
        """get_all_edges_between returns all edges for a pair, empty list for no edges."""
        graph = ArchGraph()
        graph.add_node(Node(id="A", type=NodeType.MODULE, label="A"))
        graph.add_node(Node(id="B", type=NodeType.MODULE, label="B"))
        graph.add_node(Node(id="C", type=NodeType.MODULE, label="C"))

        graph.add_edge(Edge(source="A", target="B", type=EdgeType.CONTAINS))
        graph.add_edge(Edge(source="A", target="B", type=EdgeType.IMPORTS))
        graph.add_edge(Edge(source="B", target="C", type=EdgeType.CALLS))

        edges_ab = graph.get_all_edges_between("A", "B")
        assert len(edges_ab) == 2
        types_ab = {e.type for e in edges_ab}
        assert EdgeType.CONTAINS in types_ab
        assert EdgeType.IMPORTS in types_ab

        # Only one edge between B and C
        edges_bc = graph.get_all_edges_between("B", "C")
        assert len(edges_bc) == 1

        # No edge between A and C
        edges_ac = graph.get_all_edges_between("A", "C")
        assert edges_ac == []

        # Non-existent node
        assert graph.get_all_edges_between("A", "nonexistent") == []

    # T010
    def test_iter_edges_yields_all(self):
        """iter_edges() yields every Edge in the graph."""
        graph = ArchGraph()
        graph.add_node(Node(id="A", type=NodeType.SERVICE, label="A"))
        graph.add_node(Node(id="B", type=NodeType.SERVICE, label="B"))
        graph.add_node(Node(id="C", type=NodeType.SERVICE, label="C"))

        graph.add_edge(Edge(source="A", target="B", type=EdgeType.CALLS))
        graph.add_edge(Edge(source="A", target="B", type=EdgeType.IMPORTS))
        graph.add_edge(Edge(source="B", target="C", type=EdgeType.CALLS))

        all_edges = list(graph.iter_edges())
        assert len(all_edges) == 3
        for e in all_edges:
            assert isinstance(e, Edge)

    # T011
    def test_merge_manual_annotations_preserves_multi_edges(self):
        """merge_manual_annotations keeps both manual and scanned edges between same pair."""
        # New graph has a scanned "contains" edge A->B
        new_graph = ArchGraph()
        new_graph.add_node(Node(id="module:A", type=NodeType.MODULE, label="A"))
        new_graph.add_node(Node(id="module:B", type=NodeType.MODULE, label="B"))
        new_graph.add_edge(
            Edge(source="module:A", target="module:B", type=EdgeType.CONTAINS, manual=False)
        )

        # Old data had a manual "custom" edge A->B
        old_data = GraphData(
            nodes={
                "module:A": Node(id="module:A", type=NodeType.MODULE, label="A"),
                "module:B": Node(id="module:B", type=NodeType.MODULE, label="B"),
            },
            edges=[
                Edge(
                    source="module:A",
                    target="module:B",
                    type=EdgeType.CALLS,
                    manual=True,
                ),
            ],
        )

        new_graph.merge_manual_annotations(old_data)
        data = new_graph.to_data()

        # Both edges must exist: the scanned "contains" and the manual "calls"
        assert len(data.edges) == 2
        edge_types = {e.type for e in data.edges}
        assert EdgeType.CONTAINS in edge_types
        assert EdgeType.CALLS in edge_types

        # The manual edge must be flagged
        manual_edges = [e for e in data.edges if e.manual]
        assert len(manual_edges) == 1
        assert manual_edges[0].type == EdgeType.CALLS

    # T012
    def test_legacy_single_edge_format_loads(self):
        """GraphData with single edges per pair (old format) loads correctly."""
        legacy_data = GraphData(
            nodes={
                "module:X": Node(id="module:X", type=NodeType.MODULE, label="X"),
                "module:Y": Node(id="module:Y", type=NodeType.MODULE, label="Y"),
            },
            edges=[
                Edge(source="module:X", target="module:Y", type=EdgeType.IMPORTS),
            ],
        )

        graph = ArchGraph(legacy_data)
        data = graph.to_data()

        assert len(data.edges) == 1
        assert data.edges[0].source == "module:X"
        assert data.edges[0].target == "module:Y"
        assert data.edges[0].type == EdgeType.IMPORTS

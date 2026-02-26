"""Graph data model for Code Giraffe architecture knowledge graph.

Provides Pydantic models for serialization and an ArchGraph class
that wraps a NetworkX MultiDiGraph for querying and manipulation.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Iterator

import networkx as nx
from pydantic import BaseModel, ConfigDict, Field


class Node(BaseModel):
    """A node in the architecture graph representing an architectural component."""

    id: str
    type: str
    label: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    file_path: str | None = None
    manual: bool = False


class Edge(BaseModel):
    """A directed edge in the architecture graph representing a relationship."""

    source: str
    target: str
    type: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    manual: bool = False
    confidence: float = 1.0


class GraphData(BaseModel):
    """Serializable representation of the full architecture graph."""

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    nodes: dict[str, Node] = Field(default_factory=dict)
    edges: list[Edge] = Field(default_factory=list)
    project_path: str = ""
    last_scan: str | None = None
    schema_version: str = "1.0"
    token_estimate: int = Field(default=0, alias="_token_estimate")
    retrieval_strategy: str = Field(default="", alias="_retrieval_strategy")
    layout: dict[str, list[float]] = Field(default_factory=dict)


class ArchGraph:
    """Architecture knowledge graph backed by a NetworkX MultiDiGraph.

    Wraps a NetworkX MultiDiGraph and provides domain-specific methods for
    querying and manipulating the architecture graph. Using MultiDiGraph
    allows multiple edge types between the same (source, target) pair to
    coexist without overwriting each other.
    """

    def __init__(self, data: GraphData | None = None) -> None:
        self._graph = nx.MultiDiGraph()
        self._data = data or GraphData()
        self._cached_data: GraphData | None = None

        if data:
            for node in data.nodes.values():
                self._graph.add_node(node.id, node=node)
            for edge in data.edges:
                self._graph.add_edge(
                    edge.source,
                    edge.target,
                    key=edge.type,
                    edge=edge,
                )

    @property
    def graph(self) -> nx.MultiDiGraph:
        """Access the underlying NetworkX MultiDiGraph."""
        return self._graph

    def add_node(self, node: Node) -> None:
        """Add a node to the graph, replacing any existing node with the same id."""
        self._graph.add_node(node.id, node=node)
        self._cached_data = None

    def add_edge(self, edge: Edge) -> None:
        """Add an edge to the graph.

        If an edge with the same source, target, and type already exists,
        it is updated with the new edge data. Different edge types between
        the same pair are stored as separate edges (MultiDiGraph semantics).
        """
        # In MultiDiGraph, get_edge_data(u, v, key) returns the specific
        # edge data dict for that key, or None if it doesn't exist.
        existing = self._graph.get_edge_data(edge.source, edge.target, key=edge.type)
        if existing is not None:
            self._graph[edge.source][edge.target][edge.type]["edge"] = edge
        else:
            # Ensure both endpoints exist as graph nodes (even if bare)
            if edge.source not in self._graph:
                self._graph.add_node(edge.source)
            if edge.target not in self._graph:
                self._graph.add_node(edge.target)
            self._graph.add_edge(
                edge.source,
                edge.target,
                key=edge.type,
                edge=edge,
            )
        self._cached_data = None

    def remove_node(self, node_id: str) -> None:
        """Remove a node and all its incident edges from the graph."""
        if node_id in self._graph:
            self._graph.remove_node(node_id)
        self._cached_data = None

    def get_subgraph(self, node_id: str, depth: int = 2) -> GraphData:
        """Extract a subgraph via BFS from node_id up to the given depth.

        Traverses both outgoing and incoming edges to capture the full
        neighborhood of the starting node.
        """
        if node_id not in self._graph:
            return GraphData()

        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque([(node_id, 0)])
        visited.add(node_id)

        while queue:
            current, current_depth = queue.popleft()
            if current_depth >= depth:
                continue
            for neighbor in set(self._graph.successors(current)) | set(
                self._graph.predecessors(current)
            ):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, current_depth + 1))

        nodes: dict[str, Node] = {}
        for nid in visited:
            node_data = self._graph.nodes[nid].get("node")
            if node_data is not None:
                nodes[nid] = node_data

        edges: list[Edge] = []
        for u, v, edge_data in self._graph.edges(data=True, keys=False):
            if u in visited and v in visited:
                edge_obj = edge_data.get("edge")
                if edge_obj is not None:
                    edges.append(edge_obj)

        return GraphData(
            nodes=nodes,
            edges=edges,
            project_path=self._data.project_path,
            last_scan=self._data.last_scan,
            schema_version=self._data.schema_version,
        )

    def get_nodes_by_type(self, node_type: str) -> list[Node]:
        """Return all nodes matching the given type."""
        result: list[Node] = []
        for _, attrs in self._graph.nodes(data=True):
            node: Node | None = attrs.get("node")
            if node is not None and node.type == node_type:
                result.append(node)
        return result

    def get_hotspots(self, top_n: int = 10) -> list[tuple[Node, float]]:
        """Return the top N nodes ranked by degree centrality.

        Degree centrality measures how connected a node is relative to the
        rest of the graph -- highly connected nodes are architectural hotspots.
        """
        centrality = nx.degree_centrality(self._graph)

        ranked: list[tuple[str, float]] = sorted(
            centrality.items(), key=lambda item: item[1], reverse=True
        )

        result: list[tuple[Node, float]] = []
        for nid, score in ranked[:top_n]:
            node_data = self._graph.nodes[nid].get("node")
            if node_data is not None:
                result.append((node_data, score))
        return result

    def get_all_descendants(self, node_id: str) -> set[str]:
        """Return all nodes transitively reachable from *node_id* via outgoing edges."""
        if node_id not in self._graph:
            return set()
        return nx.descendants(self._graph, node_id)

    def get_all_ancestors(self, node_id: str) -> set[str]:
        """Return all nodes that can transitively reach *node_id* via outgoing edges."""
        if node_id not in self._graph:
            return set()
        return nx.ancestors(self._graph, node_id)

    def find_paths(self, source: str, target: str, max_depth: int = 10) -> list[list[str]]:
        """Return all simple paths from *source* to *target* up to *max_depth* hops."""
        if source not in self._graph or target not in self._graph:
            return []
        return list(nx.all_simple_paths(self._graph, source, target, cutoff=max_depth))

    def detect_cycles(self, max_cycles: int = 100) -> list[list[str]]:
        """Return up to *max_cycles* simple cycles (circular dependencies).

        Cycles are sorted by length (shortest first) since shorter cycles
        are typically more severe architectural issues.
        """
        cycles: list[list[str]] = []
        for cycle in nx.simple_cycles(self._graph):
            cycles.append(cycle)
            if len(cycles) >= max_cycles:
                break
        cycles.sort(key=len)
        return cycles

    def get_betweenness_centrality(self) -> dict[str, float]:
        """Return betweenness centrality for all nodes.

        Betweenness centrality measures how often a node appears on shortest
        paths between other nodes -- high values indicate architectural bottlenecks.
        """
        if len(self._graph) == 0:
            return {}
        return nx.betweenness_centrality(self._graph)

    def to_data(self) -> GraphData:
        """Serialize the current graph state back to a GraphData model."""
        if self._cached_data is not None:
            return self._cached_data

        nodes: dict[str, Node] = {}
        for nid, attrs in self._graph.nodes(data=True):
            node: Node | None = attrs.get("node")
            if node is not None:
                nodes[nid] = node

        edges: list[Edge] = []
        for _, _, edge_data in self._graph.edges(data=True, keys=False):
            edge_obj: Edge | None = edge_data.get("edge")
            if edge_obj is not None:
                edges.append(edge_obj)

        self._cached_data = GraphData(
            nodes=nodes,
            edges=edges,
            project_path=self._data.project_path,
            last_scan=self._data.last_scan,
            schema_version=self._data.schema_version,
        )
        return self._cached_data

    def merge_manual_annotations(self, old_data: GraphData) -> None:
        """Preserve manually annotated nodes and edges from previous graph data.

        Any node or edge with manual=True in old_data that is not already
        present in the current graph will be added back, ensuring that
        hand-curated architectural knowledge survives automated re-scans.
        """
        for node in old_data.nodes.values():
            if node.manual and node.id not in self._graph:
                self.add_node(node)

        for edge in old_data.edges:
            if not edge.manual:
                continue
            # Check whether this exact manual edge (same source, target, type) already exists.
            # In MultiDiGraph, get_edge_data with key= returns None if that specific
            # typed edge is absent.
            existing = self._graph.get_edge_data(edge.source, edge.target, key=edge.type)
            if existing is None:
                self.add_edge(edge)
        self._cached_data = None

    def get_edge_between(self, source: str, target: str) -> Edge | None:
        """Return any Edge between source and target, or None if no edges exist.

        When multiple edge types exist between the pair, the first found is returned.
        Use get_typed_edge() or get_all_edges_between() for precise access.
        """
        if source not in self._graph or target not in self._graph:
            return None
        edge_map = self._graph.get_edge_data(source, target)
        if not edge_map:
            return None
        for edge_data in edge_map.values():
            edge_obj: Edge | None = edge_data.get("edge")
            if edge_obj is not None:
                return edge_obj
        return None

    def get_typed_edge(self, source: str, target: str, edge_type: str) -> Edge | None:
        """Return the Edge of a specific type between source and target, or None.

        Performs an exact lookup by (source, target, edge_type) triple.
        """
        if source not in self._graph or target not in self._graph:
            return None
        edge_data = self._graph.get_edge_data(source, target, key=edge_type)
        if edge_data is None:
            return None
        return edge_data.get("edge")

    def get_all_edges_between(self, source: str, target: str) -> list[Edge]:
        """Return all edges between source and target across all edge types.

        Returns an empty list if no edges exist or if either node is absent.
        """
        if source not in self._graph or target not in self._graph:
            return []
        edge_map = self._graph.get_edge_data(source, target)
        if not edge_map:
            return []
        result: list[Edge] = []
        for edge_data in edge_map.values():
            edge_obj: Edge | None = edge_data.get("edge")
            if edge_obj is not None:
                result.append(edge_obj)
        return result

    def iter_edges(self) -> Iterator[Edge]:
        """Yield every Edge in the graph, across all node pairs and edge types."""
        for _, _, edge_data in self._graph.edges(data=True, keys=False):
            edge_obj: Edge | None = edge_data.get("edge")
            if edge_obj is not None:
                yield edge_obj

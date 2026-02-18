"""Graph data model for Code Giraffe architecture knowledge graph.

Provides Pydantic models for serialization and an ArchGraph class
that wraps a NetworkX DiGraph for querying and manipulation.
"""

from __future__ import annotations

from collections import deque
from typing import Any

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


class ArchGraph:
    """Architecture knowledge graph backed by a NetworkX DiGraph.

    Wraps a NetworkX DiGraph and provides domain-specific methods for
    querying and manipulating the architecture graph.
    """

    def __init__(self, data: GraphData | None = None) -> None:
        self._graph = nx.DiGraph()
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
    def graph(self) -> nx.DiGraph:
        """Access the underlying NetworkX DiGraph."""
        return self._graph

    def add_node(self, node: Node) -> None:
        """Add a node to the graph, replacing any existing node with the same id."""
        self._graph.add_node(node.id, node=node)
        self._cached_data = None

    def add_edge(self, edge: Edge) -> None:
        """Add an edge to the graph.

        If an edge with the same source, target, and type already exists,
        it is updated with the new edge data.
        """
        existing_edges = self._graph.get_edge_data(edge.source, edge.target)
        if existing_edges and existing_edges.get("key") == edge.type:
            self._graph[edge.source][edge.target]["edge"] = edge
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
        for u, v, edge_data in self._graph.edges(data=True):
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
        for _, _, edge_data in self._graph.edges(data=True):
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
            # Check whether this exact manual edge already exists
            existing = self._graph.get_edge_data(edge.source, edge.target)
            if existing is None or existing.get("key") != edge.type:
                self.add_edge(edge)
        self._cached_data = None

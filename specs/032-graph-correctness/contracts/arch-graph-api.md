# Contract: ArchGraph API

**Feature**: 032-graph-correctness

## Existing Methods (Modified Behavior)

### `ArchGraph.__init__(data: GraphData)`
- **Before**: Loads edges into `nx.DiGraph`; duplicate `(source, target)` pairs silently overwrite
- **After**: Loads edges into `nx.MultiDiGraph` with `key=edge.type`; all edges preserved
- **Backward compatible**: Yes — old data with one edge per pair loads identically

### `ArchGraph.add_edge(edge: Edge) -> None`
- **Before**: Overwrites any existing edge for the same `(source, target)` pair
- **After**: Updates if same `(source, target, type)` exists; creates new if different type
- **Idempotent**: Yes — same input produces same graph state

### `ArchGraph.to_data() -> GraphData`
- **Before**: Returns at most one edge per `(source, target)` pair
- **After**: Returns all edges, including multiple per pair
- **Cache**: Invalidated on any mutation (unchanged behavior)

### `ArchGraph.get_subgraph(node_id, depth) -> GraphData`
- **Before**: Returns at most one edge per pair in the subgraph
- **After**: Returns all edges within the subgraph

### `ArchGraph.graph -> nx.MultiDiGraph`
- **Before**: Returns `nx.DiGraph`
- **After**: Returns `nx.MultiDiGraph`
- **Breaking for callers**: Only if they rely on DiGraph-specific behavior

## New Methods

### `ArchGraph.get_edge_between(source: str, target: str) -> Edge | None`
- Returns any single edge between source and target (first found)
- Returns `None` if no edge exists
- Use when you need to check "is there any relationship?" without caring about type

### `ArchGraph.get_typed_edge(source: str, target: str, edge_type: str) -> Edge | None`
- Returns the edge with the specified type, or `None`
- Use when you need a specific relationship type

### `ArchGraph.get_all_edges_between(source: str, target: str) -> list[Edge]`
- Returns all edges between source and target
- Returns empty list if no edges exist
- Use when you need to enumerate all relationships

### `ArchGraph.iter_edges() -> Iterator[Edge]`
- Yields all Edge objects in the graph
- Use instead of `for u, v, data in graph.graph.edges(data=True)` when you only need Edge objects

## Cypher Query Contract

### `Neo4jStorage.run_cypher(query: str, project_path: str | None) -> list[dict]`
- **Pre-condition**: Query must be read-only (no write keywords)
- **Rejection**: Queries containing `CREATE`, `MERGE`, `DELETE`, `SET`, `REMOVE`, `DROP`, `DETACH`, `CALL` are rejected with `ValueError`
- **Post-condition**: Returns query results as list of dicts
- **Error**: `ValueError` for write queries; `RuntimeError` for Neo4j connection/execution errors

## Concurrency Contract

### `_graph_lock: threading.RLock` (module-level in server.py)
- **Scope**: Protects `_graph` and `_storage` globals
- **Acquire before**: Any read or write to `_graph` or `_storage`
- **Release after**: Operation complete (including save for write tools)
- **Reentrant**: Yes — nested calls to `_ensure_graph` do not deadlock

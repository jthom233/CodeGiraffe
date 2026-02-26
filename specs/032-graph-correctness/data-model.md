# Data Model: Graph Correctness

**Feature**: 032-graph-correctness
**Date**: 2026-02-25

## Entity Changes

### Edge (unchanged Pydantic model)

The `Edge` Pydantic model in `graph.py` does **not** change. Its fields remain:

```
Edge:
  source: str           # Node ID of the edge source
  target: str           # Node ID of the edge target
  type: str             # Edge type (e.g., "imports", "calls", "contains")
  metadata: dict        # Arbitrary key-value metadata
  manual: bool          # True = survives automated rescans
  confidence: float     # 0.0–1.0 confidence score (default 1.0)
```

**Edge identity**: `(source, target, type)` — this 3-tuple uniquely identifies an edge. This is unchanged from the current logical model but is now **enforced** by the in-memory graph (MultiDiGraph uses `type` as the edge key).

### ArchGraph (modified)

The `ArchGraph` class wraps the NetworkX graph. Changes:

```
ArchGraph:
  _graph: nx.MultiDiGraph      # CHANGED from nx.DiGraph
  _cached_data: GraphData | None
  _lock: threading.RLock        # NEW — protects all mutations

  # Existing methods (modified):
  add_edge(edge: Edge) -> None
  to_data() -> GraphData
  get_subgraph(node_id, depth) -> GraphData
  merge_manual_annotations(old_data) -> None
  graph -> nx.MultiDiGraph      # CHANGED return type annotation

  # New helper methods:
  get_edge_between(source, target) -> Edge | None
  get_typed_edge(source, target, edge_type) -> Edge | None
  get_all_edges_between(source, target) -> list[Edge]
  iter_edges() -> Iterator[Edge]
```

### GraphData (unchanged)

The serialization envelope does not change. `GraphData.edges` remains `list[Edge]` — a flat list of all edges. Multiple edges between the same node pair are simply multiple entries in the list with different `type` values.

**Backward compatibility**: Old graph files with at most one edge per pair are a valid subset. No migration needed.

## Relationship Changes

### Before (DiGraph)

```
(A) --[contains]--> (B)    # Only ONE edge survives between A and B
(A) --[imports]--> (B)     # OVERWRITES the contains edge silently
```

### After (MultiDiGraph)

```
(A) --[contains]--> (B)    # Both edges coexist
(A) --[imports]--> (B)     # Keyed by type, independent
```

### Edge Key Semantics

In `nx.MultiDiGraph`, each edge is identified by `(source, target, key)`. We use `edge.type` as the key:

- `graph.add_edge(source, target, key="imports", edge=edge_obj)` creates one edge
- `graph.add_edge(source, target, key="contains", edge=edge_obj)` creates a second, independent edge
- `graph.get_edge_data(source, target, key="imports")` retrieves only the imports edge
- `graph.get_edge_data(source, target)` retrieves `{"imports": {...}, "contains": {...}}`

### Deduplication Rule

Adding an edge with the same `(source, target, type)` as an existing edge **updates** the existing edge (idempotent). Adding an edge with the same `(source, target)` but different `type` **creates** a new parallel edge.

## Storage Representation

### JSON (no change)

```json
{
  "edges": [
    {"source": "mod:a", "target": "mod:b", "type": "contains", "confidence": 1.0, ...},
    {"source": "mod:a", "target": "mod:b", "type": "imports", "confidence": 0.9, ...}
  ]
}
```

Multiple edges between the same pair are simply multiple list entries. This is already valid JSON and already produced by `GraphData.model_dump()`.

### SQLite (no change)

The `UNIQUE(source, target, type)` constraint already allows multiple edges between the same pair as long as they differ in `type`. No schema migration needed.

### Neo4j (no change needed for multi-edges)

`CREATE (a)-[r:RELATES_TO]->(b)` already creates separate relationships. Multiple RELATES_TO relationships between the same nodes coexist natively.

## Concurrency Model

### Lock Scope

```
Module-level:
  _graph_lock: threading.RLock

Acquisition pattern:
  _ensure_graph:    acquire → check cache → load if miss → release
  Write tools:      acquire → mutate → save → release
  Read tools:       acquire → read → release
  Dashboard thread: acquire → read → release
```

### Thread Safety Guarantees

1. No concurrent writes: Only one thread can mutate `_graph` at a time
2. No torn reads: A reader always sees a complete, consistent graph state
3. No stale references: `_graph` replacement (during init/sync) is atomic within the lock
4. Reentrant: Tools that call `_ensure_graph` internally don't deadlock

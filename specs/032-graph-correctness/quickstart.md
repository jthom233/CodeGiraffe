# Developer Quickstart: Graph Correctness Migration

**Feature**: 032-graph-correctness
**Date**: 2026-02-25

## What Changed

### 1. `nx.DiGraph` → `nx.MultiDiGraph`

The `ArchGraph._graph` is now a `MultiDiGraph`. Multiple edges between the same node pair are keyed by `edge.type`.

### 2. New Helper Methods on ArchGraph

Instead of accessing `graph.graph.edges.get((u, v), {})` directly, use:

```python
# Get any single edge between two nodes (returns first found, or None)
edge = graph.get_edge_between(source, target)

# Get a specific typed edge
edge = graph.get_typed_edge(source, target, "imports")

# Get all edges between two nodes
edges = graph.get_all_edges_between(source, target)

# Iterate all Edge objects in the graph
for edge in graph.iter_edges():
    ...
```

### 3. Edge Iteration Pattern

When iterating edges from the NetworkX graph directly, always pass `keys=False`:

```python
# CORRECT — preserves 3-tuple unpacking
for u, v, data in graph.graph.edges(data=True, keys=False):
    edge_obj = data.get("edge")

# WRONG — MultiDiGraph yields 4-tuples by default
for u, v, data in graph.graph.edges(data=True):  # ValueError!
```

Same for `out_edges` and `in_edges` with `data=True`:

```python
# CORRECT
for src, tgt, data in graph.graph.out_edges(node, data=True, keys=False):

# Note: without data=True, out_edges/in_edges yield 2-tuples by default — no change needed
for _, target in graph.graph.out_edges(node):  # still works
```

### 4. Thread Safety

All `_graph` access in `server.py` is protected by `_graph_lock`. If you add a new tool:

```python
@mcp.tool()
def codegiraffe_new_tool(project_path: str, ...):
    with _graph_lock:
        graph = _ensure_graph(project_path)
        # ... use graph ...
        # if mutating:
        _storage.save(project_path, graph.to_data())
```

### 5. Cypher Queries

`run_cypher` now rejects write operations. Only `MATCH`, `RETURN`, `WHERE`, `ORDER BY`, `LIMIT`, `OPTIONAL MATCH`, `WITH`, `UNION`, `UNWIND`, and `CASE` are safe keywords. Any query containing `CREATE`, `MERGE`, `DELETE`, `SET`, `REMOVE`, `DROP`, `DETACH`, or `CALL` will be rejected.

## Common Patterns

### Checking if a specific edge type exists between two nodes

```python
# Before (broken on DiGraph anyway):
edge_data = graph.graph.edges.get((src, tgt), {})

# After:
edge = graph.get_typed_edge(src, tgt, "imports")
if edge is not None:
    ...
```

### Removing a specific edge

```python
# Before (DiGraph — removes the only edge):
graph.graph.remove_edge(u, v)

# After (MultiDiGraph — must specify key):
graph.graph.remove_edge(u, v, key=edge_type)
```

### Getting edge confidence

```python
edge = graph.get_typed_edge(src, tgt, "imports")
confidence = edge.confidence if edge else 1.0
```

## Running Tests

```bash
# Run all tests
python -m pytest tests/ -v

# Run just the graph model tests (core migration)
python -m pytest tests/test_graph.py -v

# Run the query tests (edge access patterns)
python -m pytest tests/test_query.py -v

# Run the concurrency tests
python -m pytest tests/test_server_integration.py -v -k "concurrent"
```

# Implementation Plan: Graph Correctness

**Branch**: `032-graph-correctness` | **Date**: 2026-02-25 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/032-graph-correctness/spec.md`

## Summary

Migrate the in-memory graph from `nx.DiGraph` to `nx.MultiDiGraph` to preserve multiple edge types between the same node pair, enforce read-only Cypher execution in the Neo4j backend, and add `threading.RLock` concurrency protection around the shared `_graph` global. This is a correctness-first change — the primary goal is eliminating silent edge loss that currently corrupts every scanned graph.

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: NetworkX >= 3.0, Pydantic v2, FastMCP (mcp[cli] >= 1.2.0)
**Storage**: JSON files (primary), SQLite (secondary), Neo4j (optional)
**Testing**: pytest >= 8.0, pytest-asyncio >= 0.23 (1538+ tests)
**Target Platform**: Any OS supporting Python and MCP clients
**Project Type**: Single Python package (`src/codegiraffe/`)
**Performance Goals**: No regression > 10% on graph construction, query, or save/load
**Constraints**: Backward compatibility with existing saved graph files; MCP tool interface must not change
**Scale/Scope**: 37 MCP tools, ~15 source files affected, ~40 edge access sites to update

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. MCP-Native | PASS | No MCP tool interface changes. All improvements are internal. |
| II. Graph-First | PASS | Core graph model improvement — directly strengthens the graph representation. |
| III. Beyond-AST | PASS | Multi-edge support enables richer relationship modeling. |
| IV. Context Efficiency | PASS | No change to query interfaces or token budgets. |
| V. Incremental & Non-Destructive | PASS | Backward-compatible loading; no data migration required for existing files. |
| VI. Test-First (NON-NEGOTIABLE) | PASS | Tests written before implementation for each migration step. |
| VII. Simplicity | PASS | MultiDiGraph is the natural NetworkX primitive for typed multi-edges. Threading.RLock is stdlib. Cypher keyword filtering is simple string matching. No new dependencies. |

## Project Structure

### Documentation (this feature)

```text
specs/032-graph-correctness/
├── plan.md              # This file
├── research.md          # Phase 0: codebase research findings
├── data-model.md        # Phase 1: edge model changes
├── quickstart.md        # Phase 1: developer guide for the migration
├── contracts/           # Phase 1: API contracts (internal)
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
src/codegiraffe/
├── graph.py              # PRIMARY: DiGraph → MultiDiGraph, add_edge, to_data, get_subgraph
├── query.py              # 13 edge access sites to update (3 mechanical patterns)
├── server.py             # Add RLock, fix 1 edge access site, fix Cypher tool
├── scanner.py            # 5 edge iteration sites in sync_files()
├── storage.py            # No changes (JSON round-trips correctly)
├── sqlite_storage.py     # UNIQUE constraint already correct (source, target, type)
├── neo4j_storage.py      # Add Cypher write-rejection in run_cypher
├── domains.py            # 2 get_edge_data sites to update
├── migration.py          # 3 out_edges/in_edges sites to update
├── export.py             # No changes (operates on GraphData.edges list)
├── federation.py         # No changes (operates on GraphData.edges list)
├── dashboard.py          # No changes (operates on GraphData.edges list)
├── versioning.py         # No changes (operates on GraphData.edges list)
└── ownership.py          # No changes (no edge access)

tests/
├── test_graph.py         # New multi-edge tests + update existing
├── test_query.py         # Update edge access assertions
├── test_scanner.py       # Update sync_files edge assertions
├── test_neo4j_storage.py # New Cypher rejection tests
├── test_server_integration.py # New concurrency tests
└── test_domains.py       # Update domain edge lookup tests
```

**Structure Decision**: Existing single-project structure. No new files or directories needed beyond the spec artifacts. All changes are modifications to existing source files.

## Migration Strategy

### Key Insight: Three Mechanical Patterns

The research identified **~40 edge access sites** across the codebase, but they reduce to just **3 mechanical patterns** plus the core graph.py changes:

**Pattern A — `edges(data=True)` 3-tuple unpacking (10 sites)**
```python
# Before (DiGraph): yields (u, v, data_dict)
for u, v, data in graph.graph.edges(data=True):

# After (MultiDiGraph): pass keys=False to preserve 3-tuple
for u, v, data in graph.graph.edges(data=True, keys=False):
```

**Pattern B — `.edges.get((u, v), {})` single-edge lookup (6 sites)**
```python
# Before (DiGraph): returns single edge attr dict
edge_data = graph.graph.edges.get((src, tgt), {})

# After (MultiDiGraph): helper method on ArchGraph
edge_data = graph.get_edge_between(src, tgt)  # returns first edge, or None
# Or for type-specific lookup:
edge_data = graph.get_typed_edge(src, tgt, edge_type)
```

**Pattern C — `out_edges`/`in_edges` unpacking (4 sites in query.py, 3 in migration.py)**
```python
# Before (DiGraph with data=True): yields (u, v, data)
for src, tgt, data in graph.graph.out_edges(node, data=True):

# After (MultiDiGraph): pass keys=False
for src, tgt, data in graph.graph.out_edges(node, data=True, keys=False):

# Before (DiGraph without data): yields (u, v)
for _, target in graph.graph.out_edges(node):
# After (MultiDiGraph without data): same — 2-tuple is default
for _, target in graph.graph.out_edges(node):  # no change needed
```

### Helper Methods on ArchGraph

To avoid scattering MultiDiGraph-specific code across the codebase, add thin helpers:

```python
def get_edge_between(self, source: str, target: str) -> Edge | None:
    """Get any edge between source and target (first found)."""

def get_typed_edge(self, source: str, target: str, edge_type: str) -> Edge | None:
    """Get a specific typed edge between source and target."""

def get_all_edges_between(self, source: str, target: str) -> list[Edge]:
    """Get all edges between source and target."""

def iter_edges(self) -> Iterator[Edge]:
    """Iterate all Edge objects in the graph."""
```

### Concurrency Model

A single `threading.RLock` at the server module level protects `_graph` and `_storage`:

- **Read tools**: Acquire the lock in `_ensure_graph`, hold through the read operation
- **Write tools**: Acquire the lock before mutation, hold through save
- **Dashboard thread**: Acquires the same lock when accessing `_graph`
- **RLock (not Lock)**: Reentrant because some tools call `_ensure_graph` then call other functions that also call `_ensure_graph`

### Cypher Write-Rejection

Conservative keyword-based filtering before query execution:

```python
_CYPHER_WRITE_KEYWORDS = {"CREATE", "MERGE", "DELETE", "SET", "REMOVE", "DROP", "DETACH", "CALL"}

def _is_read_only_cypher(query: str) -> bool:
    tokens = re.findall(r'\b\w+\b', query.upper())
    return not any(t in _CYPHER_WRITE_KEYWORDS for t in tokens)
```

This is intentionally conservative — queries with write keywords in string literals are rejected. The safety benefit outweighs the usability cost.

## Complexity Tracking

No constitution violations to justify. All changes use stdlib primitives and existing NetworkX APIs.

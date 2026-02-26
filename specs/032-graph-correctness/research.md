# Research: Graph Correctness

**Feature**: 032-graph-correctness
**Date**: 2026-02-25

## Decision Log

### D1: MultiDiGraph Migration Approach

**Decision**: Migrate `nx.DiGraph` → `nx.MultiDiGraph` using `edge.type` as the NetworkX edge key.

**Rationale**: NetworkX's `MultiDiGraph` natively supports multiple edges between the same node pair, keyed by an arbitrary hashable value. Using `edge.type` (a string like `"imports"`, `"calls"`, `"contains"`) as the key is a natural fit — it directly matches the existing edge identity model `(source, target, type)` that's already used throughout the codebase for deduplication sets.

**Alternatives considered**:
- **Integer auto-keys + type in attrs**: Let MultiDiGraph assign integer keys, store type in the data dict. Rejected because all lookup sites would need to iterate all keys to find a specific type, and the `(source, target, type)` 3-tuple identity is already the universal convention.
- **Custom adjacency dict**: Replace NetworkX entirely with a custom `dict[str, dict[str, dict[str, Edge]]]` structure. Rejected because it would lose all NetworkX algorithms (centrality, shortest paths, cycles, subgraph extraction) which are heavily used in query.py.
- **nx.MultiGraph (undirected)**: Rejected because the graph is inherently directed — `A imports B` does not imply `B imports A`.

### D2: Edge Access Pattern Migration

**Decision**: Use `keys=False` parameter on `edges()`, `out_edges()`, and `in_edges()` calls to preserve existing 3-tuple/2-tuple unpacking patterns. Add helper methods on `ArchGraph` for type-aware lookups.

**Rationale**: MultiDiGraph methods accept a `keys` parameter (default `True` for `edges()`, `False` for `out_edges`/`in_edges`). By explicitly passing `keys=False` where we don't need the key, we preserve existing unpacking patterns with minimal code changes. For the 6 sites that need type-aware single-edge lookups, helper methods on `ArchGraph` encapsulate the MultiDiGraph-specific iteration.

**Alternatives considered**:
- **Change all unpack sites to 4-tuples**: More invasive, higher risk of introducing bugs. Rejected in favor of the `keys=False` approach which is a 1-token change per site.
- **Wrap all access in an `EdgeView` abstraction**: Over-engineering for the current needs. Rejected per Constitution VII (Simplicity).

### D3: Concurrency Protection Mechanism

**Decision**: Single `threading.RLock` at the server module level, wrapping `_graph` and `_storage` access.

**Rationale**: The concurrency model is simple — one project's graph is loaded in memory, shared between MCP tools (main thread) and the dashboard (background thread). A single reentrant lock is sufficient because:
1. Write operations are infrequent (init, sync, annotate)
2. Read operations dominate (query, context_for, blast_radius)
3. The graph is small enough that holding the lock during a full read doesn't cause meaningful contention
4. RLock is reentrant, which is needed because tools call `_ensure_graph` which may be called again within the same call chain

**Alternatives considered**:
- **`threading.Lock` (non-reentrant)**: Rejected because `_ensure_graph` is called both directly and indirectly within the same tool, causing deadlock.
- **`asyncio.Lock`**: Rejected because the dashboard runs on a separate thread (not asyncio task), and MCP tool functions are synchronous.
- **Read-write lock (rwlock)**: Would allow concurrent readers. Rejected for v1 because the stdlib doesn't include one and adding a dependency violates Constitution VII. Can be revisited if contention becomes measurable.
- **Lock-free with atomic reference swaps**: Python's GIL makes reference assignment atomic, but compound operations (check-then-set in `_ensure_graph`) are not atomic. Rejected as insufficient.

### D4: Cypher Write-Rejection Strategy

**Decision**: Keyword-based token filtering before query execution. Reject queries containing `CREATE`, `MERGE`, `DELETE`, `SET`, `REMOVE`, `DROP`, `DETACH`, or `CALL` as whole words.

**Rationale**: Full Cypher parsing is complex and fragile (Cypher has no official Python parser). Keyword-based rejection is simple, conservative, and covers all dangerous operations. The false-positive risk (rejecting legitimate queries that contain these words in string literals) is acceptable because:
1. The tool is for architecture exploration, not arbitrary DB queries
2. Most read queries use only `MATCH`, `RETURN`, `WHERE`, `ORDER BY`, `LIMIT`
3. Users who need write access should use the Neo4j client directly

**Alternatives considered**:
- **Neo4j `session.execute_read()`**: Uses Neo4j's built-in read transaction mode. Rejected as primary approach because it requires a running Neo4j instance to test, and the rejection should happen before network round-trip. Could be used as a secondary defense layer.
- **Full Cypher parser**: No maintained Python library exists. Rejected per Constitution VII.
- **Regex-based comment/string stripping before keyword check**: More precise but adds complexity. Rejected for v1 — conservative rejection is stated as acceptable in the spec.

## Codebase Analysis

### Files Requiring Changes

| File | Changes | Sites | Risk |
|------|---------|-------|------|
| `graph.py` | DiGraph→MultiDiGraph, add_edge rewrite, to_data, get_subgraph, new helpers | 8 | HIGH — core model |
| `query.py` | edges.get→helper, edges(data=True)→keys=False, out_edges→keys=False | 13 | HIGH — many sites |
| `server.py` | Add RLock, wrap tools, fix 1 edge access, Cypher tool docstring | ~40 | MEDIUM — mechanical |
| `scanner.py` | edges(data=True)→keys=False, remove_edge→keyed, has_edge→check type | 6 | MEDIUM |
| `neo4j_storage.py` | Add write-rejection to run_cypher | 1 | LOW — isolated |
| `domains.py` | get_edge_data→helper | 2 | LOW — isolated |
| `migration.py` | out_edges/in_edges — no data, may need keys=False | 3 | LOW — isolated |

### Files NOT Requiring Changes (Isolated from NX)

| File | Why safe |
|------|----------|
| `storage.py` (JSONStorage) | Operates on GraphData.edges list via Pydantic |
| `sqlite_storage.py` | Operates on GraphData.edges; UNIQUE(source,target,type) already correct |
| `export.py` | Iterates GraphData.edges list |
| `federation.py` | Iterates GraphData.edges list |
| `dashboard.py` | Iterates GraphData.edges list via to_data() |
| `versioning.py` | Iterates GraphData.edges list |
| `ownership.py` | Only accesses nodes, never edges |
| `graph_diff.py` | Builds sets from GraphData.edges list |

### Edge Access Inventory (Complete)

**Pattern A — `edges(data=True)` 3-tuple → add `keys=False` (10 sites)**:
- `graph.py:146` (get_subgraph), `graph.py:242` (to_data)
- `query.py:333, 827, 984, 1065` (edge iteration for constrains/intent/context)
- `scanner.py:2397, 2539, 2573, 2621` (sync_files)

**Pattern B — `.edges.get((u,v), {})` → helper method (6 sites)**:
- `query.py:148, 1475, 2136, 2429, 2436, 2565`
- `server.py:725`

**Pattern C — `out_edges`/`in_edges` unpacking (7 sites)**:
- `query.py:670` (out_edges with data), `query.py:772` (in_edges with data)
- `query.py:717, 732` (out_edges/in_edges without data — no change needed on MultiDiGraph)
- `migration.py:194, 221, 225` (out_edges/in_edges without data — no change needed)

**Pattern D — `get_edge_data(u, v)` → helper (4 sites)**:
- `graph.py:92` (add_edge), `graph.py:271` (merge_manual_annotations)
- `domains.py:206, 244` (list_domains, get_domain_membership)

**Pattern E — Direct mutation (3 sites)**:
- `graph.py:94` (`self._graph[u][v]["edge"] = edge` — must include key)
- `scanner.py:2422-2423` (`has_edge` + `remove_edge` — must be type-aware)

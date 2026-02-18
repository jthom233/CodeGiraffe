# Research: Large-Graph Dashboard Visualization

**Branch**: `013-sigma-dashboard` | **Date**: 2026-02-18

## Decision 1: Client-Side Renderer

**Decision**: Sigma.js v3 (sigma@3.0.2) + graphology@0.26.0

**Rationale**:
- WebGL instanced rendering handles 30,000–50,000 nodes interactively
- Both libraries ship confirmed UMD bundles on jsDelivr — no build toolchain required
- Built-in grid-based label culling scales automatically at any node count
- Node-ID-based click/hover event API maps directly to the existing detail panel
- Stable v3.0.0 released Dec 2024; used in production by Gephi Lite (identical use case)
- `nodeReducer`/`edgeReducer` callbacks support per-node colors cleanly
- Pre-computed x,y positions are native: just set `x`/`y` on graphology node attributes

**CDN URLs** (confirmed UMD):
```
https://cdn.jsdelivr.net/npm/graphology@0.26.0/dist/graphology.umd.min.js
https://cdn.jsdelivr.net/npm/sigma@3.0.2/dist/sigma.min.js
```

**Alternatives considered**:
- cosmos.gl: Pure GPU, handles 500k+ nodes, but circles-only shapes, no built-in labels, index-based click events — all three are blockers for Code Giraffe's requirements
- Cytoscape.js WebGL preview: 10fps at 3,200 nodes — insufficient
- D3 + Canvas: No abstraction, interactivity breaks at 7k nodes

---

## Decision 2: Server-Side Layout Algorithm

**Decision**: ForceAtlas2 via the `fa2` Python package (optional dependency, graceful fallback)

**Rationale**:
- ForceAtlas2 with Barnes-Hut approximation is O(n log n), handles 33k nodes in under a minute
- `fa2` package uses Cython for 10–100x speedup over pure Python
- Produces organic, semantically meaningful layouts (connected nodes cluster together)
- Computed once on `codegiraffe_init` / `codegiraffe_sync`, cached in stored graph JSON
- Pattern mirrors existing optional `sentence-transformers` dependency in `embeddings.py`

**Fallback** (when `fa2` not installed): deterministic grid layout using `x = i % cols`, `y = i // cols` with fixed spacing — instant, no dependency, produces usable (if unorganized) result.

**Package**: `fa2` on PyPI. Added to `pyproject.toml` as optional `[layout]` extra.

**Alternatives considered**:
- `igraph` ForceAtlas2: Good but heavier dependency
- `graphology-layout-forceatlas2` (JS, web worker): Runs in browser but blocks for 2–5 minutes at 33k nodes — bad UX; rejected in favour of server-side pre-computation
- NetworkX spring layout (Fruchterman-Reingold): O(n²), too slow at 33k nodes
- UMAP: Excellent for large graphs but requires `umap-learn` (heavy dep, sklearn transitive)

---

## Decision 3: Coordinate Storage

**Decision**: Add `layout` dict to `GraphData` Pydantic model — `{"node_id": [x, y], ...}` — stored in existing JSON/SQLite graph files

**Rationale**:
- Non-breaking addition to existing model (Pydantic v2 with defaults)
- Survives `codegiraffe_sync` — coordinates are recomputed when graph changes
- `to_d3_json()` adds `x`, `y` to each node entry when layout is present
- Backward-compatible: existing stored graphs without layout still load correctly
- Small memory footprint: 2 floats × 33,880 nodes ≈ 500KB

**Alternative considered**: Store coordinates in node `metadata` dict — rejected because it pollutes domain metadata with rendering concerns and adds per-node dict overhead

---

## Decision 4: Node Shape Strategy

**Decision**: Use color-only differentiation for node types; map all types to `circle` (default Sigma shape)

**Rationale**:
- Sigma.js v3 built-in programs: `circle` and `square`. Custom shapes require WebGL program authoring — significant effort
- Color is sufficient to differentiate 15 node types at the scales being visualized
- Matches spec "Out of Scope" — distinct shapes explicitly excluded
- Reduces rendering complexity (single node program, better GPU batching)

---

## Decision 5: Edge Style Strategy

**Decision**: Color-only differentiation for 12 edge types; all edges solid lines

**Rationale**:
- Sigma.js v3 does not support dashed/dotted edges natively
- Color differentiation is sufficient for the primary use case (architecture exploration)
- Matches spec "Out of Scope" — dashed edge styles explicitly excluded
- Reduces implementation complexity

---

## Constitution Check Results

| Principle | Status | Notes |
|---|---|---|
| I. MCP-Native | ✅ Pass | Dashboard is secondary UI; MCP tools unchanged |
| II. Graph-First | ✅ Pass | No graph model changes; layout stored as auxiliary data |
| III. Beyond-AST | ✅ Pass | Not applicable to rendering layer |
| IV. Context Efficiency | ✅ Pass | `/api/graph` already supports max_nodes + path_prefix filtering |
| V. Incremental & Non-Destructive | ✅ Pass | Layout recomputed on sync; existing graph data unaffected |
| VI. Test-First | ✅ Required | All new Python code must have tests written first |
| VII. Simplicity | ⚠️ Justified | Sigma.js adds complexity. Justified: Cytoscape.js is broken at target scale. No simpler solution exists that meets SC-001 (5s render of 33k nodes) |

**Complexity justification (Principle VII)**: Adding Sigma.js + ForceAtlas2 increases frontend complexity over the current Cytoscape.js implementation. This is justified because: (a) the current implementation fails to meet SC-001 (hangs at 1,500+ nodes), (b) no simpler rendering approach achieves 30fps at 33k nodes, (c) the existing no-build-tool constraint is preserved (CDN only), and (d) the Python layout computation uses an optional dependency with a trivial fallback.

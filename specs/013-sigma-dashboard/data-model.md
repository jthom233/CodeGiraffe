# Data Model: 013-sigma-dashboard

**Branch**: `013-sigma-dashboard` | **Date**: 2026-02-18

## Modified Entities

### GraphData (extended)

**File**: `src/codegiraffe/graph.py`

Adds one new optional field to the existing Pydantic model:

```
GraphData
├── nodes: dict[str, Node]          (existing)
├── edges: list[Edge]               (existing)
├── project_path: str               (existing)
├── last_scan: str | None           (existing)
├── schema_version: str             (existing)
├── token_estimate: int             (existing, alias _token_estimate)
├── retrieval_strategy: str         (existing, alias _retrieval_strategy)
└── layout: dict[str, list[float]]  (NEW) — {node_id: [x, y]} normalized coordinates
```

**Constraints**:
- `layout` defaults to `{}` (empty dict) — backward compatible with all existing stored graphs
- Coordinates are floats, normalized to approximately [-1, 1] range (ForceAtlas2 output scale)
- Keys in `layout` are node IDs — MUST be a subset of `nodes` keys
- A `layout` entry is only written when ForceAtlas2 (or fallback) has run
- `layout` is recomputed on every `codegiraffe_sync` call

---

### to_d3_json Output (extended)

**File**: `src/codegiraffe/export.py`

Each node object in the `nodes` array gains two optional fields:

```json
{
  "id": "svc:auth",
  "type": "service",
  "label": "AuthService",
  "group": "service",
  "file_path": "src/auth/service.py",
  "manual": false,
  "metadata": {},
  "x": 0.412,
  "y": -0.187
}
```

- `x` and `y` are present only when `data.layout` contains an entry for this node ID
- When absent, Sigma.js falls back to browser-side layout (see fallback design below)
- This change is backward-compatible: Cytoscape.js (in tests) ignores unknown fields

---

## New Module: `src/codegiraffe/layout.py`

Encapsulates all layout computation. Keeps `scanner.py` and `server.py` clean.

```
layout.py
├── compute_layout(graph_data: GraphData) -> dict[str, list[float]]
│   Computes ForceAtlas2 layout if fa2 is available, else grid fallback.
│   Returns {node_id: [x, y]} dict.
│
├── _forceatlas2_layout(nx_graph: nx.DiGraph) -> dict[str, list[float]]
│   Calls fa2.ForceAtlas2 with Barnes-Hut, returns normalized coords.
│
└── _grid_fallback_layout(node_ids: list[str]) -> dict[str, list[float]]
    Assigns nodes to a grid — instant, deterministic, no dependencies.
```

**Optional dependency guard**:
```python
try:
    from fa2 import ForceAtlas2
    _FA2_AVAILABLE = True
except ImportError:
    _FA2_AVAILABLE = False
```

---

## API Response Changes

### `GET /api/graph` — node objects

Nodes in the response now include `x` and `y` when layout is stored:

```json
{
  "nodes": [
    { "id": "...", "type": "...", "x": 0.4, "y": -0.2, ... }
  ],
  "links": [...],
  "truncated": false,
  "unfiltered_total_nodes": 33880,
  "unfiltered_total_edges": 25170
}
```

No other API changes. The `/api/node` and `/api/subgraph` endpoints are unchanged.

---

## Frontend State Model (DASHBOARD_HTML)

The embedded JavaScript manages this state:

```
State
├── sigmaInstance       Sigma renderer instance (null until first load)
├── graphologyGraph     graphology.Graph instance (null until first load)
├── currentLayout       string — active layout name ('forceatlas2'|'grid'|'circular')
├── allNodeData         Map<nodeId, nodeAttrs> — full node metadata for detail panel
├── activeTypes         Set<string> — currently visible node types
├── projectPath         string — current project path from URL or input
├── hasPrecomputedLayout boolean — true if /api/graph returned x,y coords
```

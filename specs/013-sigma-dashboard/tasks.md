# Tasks: Sigma.js Dashboard Migration

**Input**: Design documents from `/specs/013-sigma-dashboard/`
**Branch**: `013-sigma-dashboard`
**Constitution**: Test-First is NON-NEGOTIABLE — every implementation task has a preceding test task

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel with other [P] tasks in the same phase
- **[Story]**: User story from spec.md (US1=Full Graph View, US2=Layout Persistence, US3=Interactive Exploration, US4=Export)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Verify branch, optional dependency, and test scaffolding are in place.

- [ ] T001 Verify `013-sigma-dashboard` branch is checked out and working tree is clean
- [ ] T002 Confirm `fa2` optional dependency in `pyproject.toml` under `[project.optional-dependencies]` as `layout = ["fa2"]` — add if missing
- [ ] T003 Create empty `tests/test_layout.py` and empty `src/codegiraffe/layout.py` placeholder files so imports resolve during TDD red phase

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core Python changes that ALL user stories depend on — must complete before any story work begins.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

### Tests (write first — must FAIL before implementation)

- [ ] T004 [P] Write `tests/test_layout.py` — unit tests for `compute_layout()`: (a) returns `dict[str, list[float]]` with one entry per node, (b) all values are 2-element float lists, (c) works when `fa2` is unavailable (grid fallback produces same shape), (d) empty graph returns empty dict, (e) single-node graph returns one entry
- [ ] T005 [P] Write tests in `tests/test_graph.py` (or add to existing graph tests) for `GraphData.layout` field: (a) defaults to `{}`, (b) round-trips through JSON serialization, (c) existing stored graphs without `layout` key still load without error (backward compat)

### Implementation (after T004, T005 are RED)

- [ ] T006 [P] Implement `src/codegiraffe/layout.py`: `compute_layout(graph_data: GraphData) -> dict[str, list[float]]` — tries `from fa2 import ForceAtlas2`, falls back to grid layout; normalize output to approximately [-1, 1] range; `_forceatlas2_layout()` and `_grid_fallback_layout()` internal helpers
- [ ] T007 [P] Add `layout: dict[str, list[float]] = Field(default_factory=dict)` to `GraphData` in `src/codegiraffe/graph.py` — Pydantic v2, default `{}`, alias-safe, backward compatible with stored JSON that has no `layout` key

**Checkpoint**: `python -m pytest tests/test_layout.py tests/test_graph.py -v` — all GREEN before proceeding

---

## Phase 3: User Story 2 — Layout Persists Across Sessions (Priority: P2)

**Goal**: ForceAtlas2 layout computed once during init/sync, stored in graph JSON, emitted by `/api/graph` as `x`/`y` on each node.

**Independent Test**: Run `codegiraffe_init` on any project, verify the stored JSON contains a `layout` key with node coordinates; call `/api/graph` and verify node objects include `x` and `y` fields.

### Tests (write first — must FAIL before implementation)

- [ ] T008 [P] [US2] Add tests to `tests/test_export.py`: (a) `to_d3_json()` includes `x` and `y` on each node when `data.layout` has entries, (b) `x`/`y` are absent when `data.layout` is empty `{}`, (c) nodes with no layout entry are emitted without `x`/`y` (partial layout dict)
- [ ] T009 [P] [US2] Add tests to `tests/test_server.py` (or equivalent): (a) after `codegiraffe_init`, the stored `GraphData` has non-empty `layout`, (b) after `codegiraffe_sync`, `layout` is refreshed (not stale), (c) `codegiraffe_init` succeeds when `fa2` is not installed (grid fallback)

### Implementation (after T008, T009 are RED)

- [ ] T010 [US2] Update `to_d3_json()` in `src/codegiraffe/export.py`: for each node, check `data.layout.get(node.id)` — if present, add `"x": coords[0], "y": coords[1]` to the node dict; no change when absent
- [ ] T011 [US2] Update `codegiraffe_init` in `src/codegiraffe/server.py`: after scan and before `_storage.save()`, call `from codegiraffe.layout import compute_layout` and set `graph.data.layout = compute_layout(data)` — guard with try/except to never fail init if layout computation errors
- [ ] T012 [US2] Update `codegiraffe_sync` in `src/codegiraffe/server.py`: same pattern as T011 — call `compute_layout` after rescanning, update stored graph data with fresh coordinates

**Checkpoint**: `python -m pytest tests/test_export.py tests/test_server.py -v` — all GREEN; manually verify `/api/graph` response contains `x`/`y` on nodes after init

---

## Phase 4: User Story 1 — View Full Architecture Graph (Priority: P1) 🎯 MVP

**Goal**: Dashboard renders 30,000+ node graph within 5 seconds using Sigma.js v3 WebGL renderer. Pre-computed coordinates used directly — no client-side layout needed.

**Independent Test**: Open the dashboard for a 33k-node project; graph renders in ≤5s; pan and zoom are fluid.

### Tests (write first — must FAIL before implementation)

- [ ] T013 [US1] Update `tests/test_dashboard.py` HTML assertions: (a) Sigma CDN script tag present (`cdn.jsdelivr.net/npm/sigma@3.0.2`), (b) graphology CDN script tag present (`cdn.jsdelivr.net/npm/graphology@0.26.0`), (c) Cytoscape CDN script tag ABSENT, (d) `new Sigma(` present in JS, (e) `new graphology.Graph(` present, (f) `nodeReducer` present, (g) `edgeReducer` present, (h) `clickNode` event handler present, (i) auto-load from URL params still present (`URLSearchParams`)

### Implementation (after T013 is RED)

- [ ] T014 [US1] Replace `DASHBOARD_HTML` in `src/codegiraffe/dashboard.py` — full Sigma.js v3 implementation:
  - Remove Cytoscape.js CDN tag; add graphology@0.26.0 + sigma@3.0.2 CDN tags
  - Replace `d3ToCytoscape()` with `d3ToGraphology()` — builds a `graphology.Graph`, sets `x`/`y` from API response when present
  - Replace `initCy(elements)` with `initSigma(graph)` — creates `new Sigma(graph, container, { nodeReducer, edgeReducer })`
  - `nodeReducer`: maps `TYPE_COLORS` dict to `color`, sets `size` based on degree (min 3, max 12), sets `label` to node label
  - `edgeReducer`: maps `EDGE_COLORS` dict to `color`, sets `size: 1.5`, sets opacity from `confidence`
  - `sigma.on('clickNode', ...)` → opens detail panel (same panel HTML as before)
  - `sigma.on('enterEdge', ...)` → shows edge tooltip
  - Toolbar: Fit (`sigma.getCamera().animatedReset()`), Layout cycle (triggers `graphology-layout-forceatlas2` web worker if no pre-computed coords — optional 3rd CDN tag), PNG export (`sigma.getCanvas().toDataURL()`)
  - Search: `sigma.refresh()` after filtering nodes via `graph.setNodeAttribute(id, 'hidden', true/false)`
  - Path prefix + node type filters: same server-side reload pattern as before
  - Max nodes input: same server-side reload pattern
  - Truncation banner: unchanged
  - Auto-load from URL params: unchanged (`URLSearchParams` block at bottom of IIFE)
  - Fallback: when `x`/`y` absent from API response, run ForceAtlas2 layout in a web worker (optional CDN: `graphology-layout-forceatlas2`)

**Checkpoint**: Open dashboard for a project with 500 nodes — graph renders, nodes are colored by type, clicking a node opens detail panel

---

## Phase 5: User Story 3 — Interactive Node Exploration (Priority: P3)

**Goal**: Click → detail panel, hover edge → tooltip, search, node type filters, path prefix filter all work in Sigma.js implementation.

**Independent Test**: Load any graph in the dashboard; click a node and verify detail panel shows correct data; type a search term and verify nodes are filtered; apply path prefix and verify reload.

> **Note**: Most of this functionality is implemented as part of T014 (US1 DASHBOARD_HTML). This phase validates it and adds any missing pieces.

### Tests (write first)

- [ ] T015 [P] [US3] Add `test_dashboard.py` HTML assertions for interactive features: (a) `enterEdge` event handler present (edge tooltip), (b) `id="search-box"` present, (c) `id="path-prefix-input"` present, (d) `id="detail-panel"` present, (e) `id="apply-server-filters"` present, (f) `escapeHtml` function present (XSS protection)

### Implementation (after T015 — fix any gaps from T014)

- [ ] T016 [US3] Verify detail panel in Sigma implementation shows: node ID, type, label, file_path, manual flag, metadata JSON, incoming edges list, outgoing edges list — patch `DASHBOARD_HTML` if any field is missing from T014 output
- [ ] T017 [US3] Verify search box filters graph in real-time: uses `sigma.refresh()` after setting `hidden` attribute — patch if needed
- [ ] T018 [US3] Verify double-click on node loads 2-hop subgraph via `/api/subgraph` and fits camera to subgraph nodes — patch if needed

**Checkpoint**: All interactive features verified working; `python -m pytest tests/test_dashboard.py -v` — all GREEN

---

## Phase 6: User Story 4 — Export and Share (Priority: P4)

**Goal**: PNG export button downloads a screenshot of the current Sigma.js canvas.

**Independent Test**: Click Export PNG; a PNG file downloads.

### Tests (write first)

- [ ] T019 [US4] Add `test_dashboard.py` assertion: `id="btn-export"` present and `toDataURL` or `getCanvas` referenced in JS

### Implementation (after T019)

- [ ] T020 [US4] Verify PNG export in Sigma.js implementation uses `sigmaInstance.getCanvas().toDataURL('image/png')` to generate and download PNG — patch `DASHBOARD_HTML` if missing or broken from T014

**Checkpoint**: Export button present in HTML; logic verified in test assertions

---

## Phase 7: Polish & Verification

**Purpose**: Full regression check, cleanup, and reviewer sign-off.

- [ ] T021 Run full test suite: `source .venv/bin/activate && python -m pytest tests/ -q --tb=short` — confirm 0 new failures beyond pre-existing 4 (git_utils Windows env)
- [ ] T022 [P] Update `CLAUDE.md` `## Recent Changes` entry: `v0.14.0: Sigma.js v3 dashboard — WebGL renderer, server-side ForceAtlas2 layout, 33k-node interactive visualization`
- [ ] T023 [P] Update `pyproject.toml` version to `0.14.0` and add `layout` optional extra
- [ ] T024 Dispatch reviewer agent for final sign-off — verify `codegiraffe_validate_changes`, blast radius, no regressions

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 — BLOCKS all user story phases
- **Phase 3 (US2 — Layout Persistence)**: Depends on Phase 2
- **Phase 4 (US1 — Full Graph View)**: Depends on Phase 3 (needs x,y in API response)
- **Phase 5 (US3 — Interactive)**: Depends on Phase 4 (needs Sigma implementation)
- **Phase 6 (US4 — Export)**: Depends on Phase 4 (needs Sigma implementation)
- **Phase 7 (Polish)**: Depends on Phases 3–6

### Within-Phase Parallel Opportunities

- T004 + T005: parallel (different test files)
- T006 + T007: parallel (different source files)
- T008 + T009: parallel (different test files)
- T010 + T011 + T012: T010 first, then T011 + T012 parallel
- T015 + T019: parallel (different test additions)
- T022 + T023: parallel (different files)

---

## Parallel Execution Example: Phase 2 (Foundational)

```
# Step 1 — write tests in parallel:
Agent A: T004 — tests/test_layout.py
Agent B: T005 — tests/test_graph.py (layout field)

# Step 2 — implement in parallel (after tests are RED):
Agent A: T006 — src/codegiraffe/layout.py
Agent B: T007 — src/codegiraffe/graph.py (layout field)
```

---

## Implementation Strategy

### MVP (User Story 1 — Full Graph View)

1. Phase 1: Setup (T001–T003)
2. Phase 2: Foundational (T004–T007) — layout.py + GraphData.layout
3. Phase 3: US2 server integration (T008–T012) — x,y in API response
4. Phase 4: US1 dashboard rewrite (T013–T014) — Sigma.js renderer
5. **STOP and VALIDATE**: Open dashboard with 33k-node project, confirm renders in ≤5s

### Full Delivery (All Stories)

After MVP validation:
6. Phase 5: US3 interactive features (T015–T018)
7. Phase 6: US4 export (T019–T020)
8. Phase 7: Polish + reviewer (T021–T024)

---

## Notes

- Constitution Principle VI is NON-NEGOTIABLE: every implementation task has a preceding test task in RED state
- T014 is the largest single task — the full DASHBOARD_HTML rewrite. It should be scoped to Sigma.js basics first (render + color), then interaction (click/detail/filter), then edge cases
- The `fa2` optional dependency MUST be guarded with try/except — `codegiraffe_init` must never fail because `fa2` is absent
- Both `dashboard.py` and `dashboard_server.py` share `DASHBOARD_HTML` — only `dashboard.py` needs to change
- The existing server-side filtering (`path_prefix`, `max_nodes`, `node_types`) is unchanged — T014 only changes the client-side renderer

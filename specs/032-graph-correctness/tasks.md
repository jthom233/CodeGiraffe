# Tasks: Graph Correctness

**Input**: Design documents from `/specs/032-graph-correctness/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Included — Constitution VI mandates Test-First (NON-NEGOTIABLE).

**Organization**: Tasks are grouped by user story. US1 (MultiDiGraph migration) is the foundational story that US2 and US3 build upon.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup

**Purpose**: Verify baseline and prepare for migration

- [ ] T001 Run full test suite (`python -m pytest tests/ -v`) and record baseline pass count and timing for SC-006 performance comparison
- [ ] T002 Create a git checkpoint branch `checkpoint/032-graph-correctness` from current HEAD for rollback safety

---

## Phase 2: Foundational (Core Graph Model Migration)

**Purpose**: Migrate `ArchGraph` from `nx.DiGraph` to `nx.MultiDiGraph` and add helper methods. This is the blocking prerequisite for all user stories — no downstream changes are possible until the core model supports multi-edges.

**CRITICAL**: No user story work can begin until this phase is complete.

### Tests

- [ ] T003 [P] Write RED test: adding two edges with same (source, target) but different types preserves both edges in `tests/test_graph.py`
- [ ] T004 [P] Write RED test: adding an edge with same (source, target, type) updates the existing edge (idempotent) in `tests/test_graph.py`
- [ ] T005 [P] Write RED test: `to_data()` returns all multi-edges (edge count matches) in `tests/test_graph.py`
- [ ] T006 [P] Write RED test: `get_subgraph()` includes all edge types within the subgraph in `tests/test_graph.py`
- [ ] T007 [P] Write RED test: `get_edge_between()` returns any edge between a pair, `None` if none in `tests/test_graph.py`
- [ ] T008 [P] Write RED test: `get_typed_edge()` returns the specific typed edge, `None` if absent in `tests/test_graph.py`
- [ ] T009 [P] Write RED test: `get_all_edges_between()` returns all edges for a pair in `tests/test_graph.py`
- [ ] T010 [P] Write RED test: `iter_edges()` yields every Edge object in the graph in `tests/test_graph.py`
- [ ] T011 [P] Write RED test: `merge_manual_annotations()` preserves manual edges alongside scanned edges of different types in `tests/test_graph.py`
- [ ] T012 [P] Write RED test: loading a legacy graph file (single edge per pair) into MultiDiGraph works correctly in `tests/test_graph.py`

### Implementation

- [ ] T013 Change `self._graph = nx.DiGraph()` to `self._graph = nx.MultiDiGraph()` and update the `graph` property return type annotation in `src/codegiraffe/graph.py`
- [ ] T014 Rewrite `ArchGraph.add_edge()` to use `get_edge_data(source, target, key=edge.type)` for deduplication and `self._graph.add_edge(source, target, key=edge.type, edge=edge)` for creation in `src/codegiraffe/graph.py`
- [ ] T015 Update `ArchGraph.__init__` edge loading loop to pass `key=edge.type` (already passes it — verify it works correctly with MultiDiGraph) in `src/codegiraffe/graph.py`
- [ ] T016 Update `ArchGraph.to_data()` edge iteration to use `edges(data=True, keys=False)` for 3-tuple unpacking in `src/codegiraffe/graph.py`
- [ ] T017 Update `ArchGraph.get_subgraph()` edge iteration to use `edges(data=True, keys=False)` for 3-tuple unpacking in `src/codegiraffe/graph.py`
- [ ] T018 Update `ArchGraph.merge_manual_annotations()` to use `get_edge_data(source, target, key=edge.type)` instead of `get_edge_data(source, target)` and remove the `"key"` attribute check in `src/codegiraffe/graph.py`
- [ ] T019 Add `get_edge_between(source, target) -> Edge | None` helper method in `src/codegiraffe/graph.py`
- [ ] T020 Add `get_typed_edge(source, target, edge_type) -> Edge | None` helper method in `src/codegiraffe/graph.py`
- [ ] T021 Add `get_all_edges_between(source, target) -> list[Edge]` helper method in `src/codegiraffe/graph.py`
- [ ] T022 Add `iter_edges() -> Iterator[Edge]` helper method in `src/codegiraffe/graph.py`
- [ ] T023 Run RED tests from T003–T012 and verify they all pass GREEN

**Checkpoint**: Core graph model supports multi-edges. All `graph.py` tests pass. Downstream files may still fail.

---

## Phase 3: User Story 1 — Multi-Edge Relationships Are Preserved (Priority: P1)

**Goal**: All edge access sites across the codebase correctly handle MultiDiGraph so that scanning, querying, and persisting graphs preserves every edge type.

**Independent Test**: Scan a project with known multi-edge relationships, verify all edge types present. Save/reload through each backend, verify edge count unchanged.

### Tests

- [ ] T024 [P] [US1] Write RED test: `_path_min_confidence` handles multi-edges between same pair (line 148 pattern) in `tests/test_query.py`
- [ ] T025 [P] [US1] Write RED test: `_apply_intent_strategy` edge iteration includes all multi-edges in `tests/test_query.py`
- [ ] T026 [P] [US1] Write RED test: `file_coupling` checks all edge types between node pairs in `tests/test_query.py`
- [ ] T027 [P] [US1] Write RED test: `order_tasks` finds `imports` edges even when other edge types exist between same pair in `tests/test_query.py`
- [ ] T028 [P] [US1] Write RED test: `sync_files` preserves multi-edges during incremental update in `tests/test_scanner.py`
- [ ] T029 [P] [US1] Write RED test: `list_domains` and `get_domain_membership` correctly identify `belongs_to` edges alongside other edges in `tests/test_domains.py`
- [ ] T030 [P] [US1] Write RED test: full scan → save → reload round-trip preserves all multi-edges through JSON backend in `tests/test_storage.py`
- [ ] T031 [P] [US1] Write RED test: full scan → save → reload round-trip preserves all multi-edges through SQLite backend in `tests/test_sqlite_storage.py`

### Implementation — query.py (Pattern A: edges iteration, 4 sites)

- [ ] T032 [US1] Update `_include_constraining_decisions` (line 333) to use `edges(data=True, keys=False)` in `src/codegiraffe/query.py`
- [ ] T033 [US1] Update `_apply_intent_strategy` (line 827) to use `edges(data=True, keys=False)` in `src/codegiraffe/query.py`
- [ ] T034 [US1] Update `_context_for_task_embeddings` (line 984) to use `edges(data=True, keys=False)` in `src/codegiraffe/query.py`
- [ ] T035 [US1] Update `_context_for_task_keywords` (line 1065) to use `edges(data=True, keys=False)` in `src/codegiraffe/query.py`

### Implementation — query.py (Pattern B: single-edge lookup, 6 sites)

- [ ] T036 [US1] Replace `.edges.get((src, tgt), {})` at line 148 (`_path_min_confidence`) with `graph.get_edge_between()` or iterate all edges for minimum confidence in `src/codegiraffe/query.py`
- [ ] T037 [US1] Replace `.edges.get((target_id, item["node_id"]), {})` at line 1475 (`format_blast_radius_report`) with ArchGraph helper in `src/codegiraffe/query.py`
- [ ] T038 [US1] Replace `.edges.get((changed_id, imp_id), {})` at line 2136 (`validate_changes`) with ArchGraph helper in `src/codegiraffe/query.py`
- [ ] T039 [P] [US1] Replace `.edges.get((na, nb), {})` at line 2429 and `.edges.get((nb, na), {})` at line 2436 (`file_coupling`) with ArchGraph helpers in `src/codegiraffe/query.py`
- [ ] T040 [US1] Replace `.edges.get((nj, ni), {})` at line 2565 (`order_tasks`) with `get_typed_edge(nj, ni, EdgeType.IMPORTS)` to correctly filter by imports type in `src/codegiraffe/query.py`

### Implementation — query.py (Pattern C: out_edges/in_edges, 2 sites with data)

- [ ] T041 [P] [US1] Update `out_edges(seed_id, data=True)` at line 670 to add `keys=False` in `src/codegiraffe/query.py`
- [ ] T042 [P] [US1] Update `in_edges(seed_id, data=True)` at line 772 to add `keys=False` in `src/codegiraffe/query.py`

### Implementation — server.py (1 site)

- [ ] T043 [US1] Replace `.edges.get((src, tgt), {})` at line 725 (`codegiraffe_cycles`) with ArchGraph helper in `src/codegiraffe/server.py`

### Implementation — scanner.py (Pattern A + E: sync_files, 6 sites)

- [ ] T044 [US1] Update `edges(data=True)` at lines 2397, 2539, 2573, 2621 in `sync_files` to add `keys=False` in `src/codegiraffe/scanner.py`
- [ ] T045 [US1] Update `remove_edge(u, v)` at line 2423 to `remove_edge(u, v, key=edge_type)` — extract edge type from edge_data before removal in `src/codegiraffe/scanner.py`
- [ ] T046 [US1] Review `has_edge(u, v)` at line 2422 — on MultiDiGraph this returns True if any edge exists, which is correct for the sync_files removal logic in `src/codegiraffe/scanner.py`

### Implementation — domains.py (Pattern D: get_edge_data, 2 sites)

- [ ] T047 [P] [US1] Update `list_domains` (line 206) and `get_domain_membership` (line 244) to use `get_edge_data(predecessor, nid, key=EdgeType.BELONGS_TO)` or ArchGraph helper in `src/codegiraffe/domains.py`

### Verification

- [ ] T048 [US1] Run all RED tests from T024–T031 and verify GREEN
- [ ] T049 [US1] Run full test suite (`python -m pytest tests/ -v`) and verify all 1538+ existing tests pass (SC-001)
- [ ] T050 [US1] Run a scan of the codegiraffe project itself and verify multi-edge relationships (contains + imports between same module pair) are preserved (SC-002)

**Checkpoint**: User Story 1 complete. All edge types are preserved across scan, query, save, and reload. All tests pass.

---

## Phase 4: User Story 2 — Read-Only Graph Database Queries (Priority: P2)

**Goal**: The `codegiraffe_cypher` tool rejects destructive Cypher queries before they reach Neo4j.

**Independent Test**: Submit write queries (CREATE, DELETE, etc.) and verify rejection. Submit read queries and verify success.

### Tests

- [ ] T051 [P] [US2] Write RED test: `_is_read_only_cypher` rejects queries containing each of the 8 write keywords (CREATE, MERGE, DELETE, SET, REMOVE, DROP, DETACH, CALL) in `tests/test_neo4j_storage.py`
- [ ] T052 [P] [US2] Write RED test: `_is_read_only_cypher` accepts standard read queries (MATCH...RETURN, WITH, WHERE, ORDER BY, LIMIT) in `tests/test_neo4j_storage.py`
- [ ] T053 [P] [US2] Write RED test: rejection is case-insensitive (e.g., `create`, `Create`, `CREATE` all rejected) in `tests/test_neo4j_storage.py`
- [ ] T054 [P] [US2] Write RED test: `run_cypher` raises `ValueError` with clear message when write query is submitted in `tests/test_neo4j_storage.py`

### Implementation

- [ ] T055 [US2] Add `_CYPHER_WRITE_KEYWORDS` constant and `_is_read_only_cypher(query: str) -> bool` function in `src/codegiraffe/neo4j_storage.py`
- [ ] T056 [US2] Add write-rejection guard at the top of `run_cypher()` that calls `_is_read_only_cypher` and raises `ValueError` if the query is not read-only in `src/codegiraffe/neo4j_storage.py`
- [ ] T057 [US2] Update `codegiraffe_cypher` tool docstring in `src/codegiraffe/server.py` to document that write operations are rejected and list the blocked keywords

### Verification

- [ ] T058 [US2] Run RED tests from T051–T054 and verify GREEN
- [ ] T059 [US2] Run full test suite to verify no regressions

**Checkpoint**: User Story 2 complete. All destructive Cypher queries are rejected. Read queries work normally.

---

## Phase 5: User Story 3 — Safe Concurrent Access (Priority: P3)

**Goal**: A `threading.RLock` protects the shared `_graph` and `_storage` globals, preventing data races between MCP tools and the dashboard background thread.

**Independent Test**: Issue concurrent reads and writes from multiple threads and verify no corruption.

### Tests

- [ ] T060 [P] [US3] Write RED test: concurrent reads from 10 threads all return consistent graph data without crashes in `tests/test_server_integration.py`
- [ ] T061 [P] [US3] Write RED test: concurrent write (annotate) + read (query) from 2 threads does not crash or corrupt the graph in `tests/test_server_integration.py`
- [ ] T062 [P] [US3] Write RED test: `_graph` replacement during `codegiraffe_init` is atomic — a concurrent reader sees either old or new graph, never partial in `tests/test_server_integration.py`

### Implementation

- [ ] T063 [US3] Add `_graph_lock = threading.RLock()` at module level in `src/codegiraffe/server.py` (near line 63, alongside other globals)
- [ ] T064 [US3] Wrap `_ensure_graph()` body in `with _graph_lock:` to protect cache check and assignment in `src/codegiraffe/server.py`
- [ ] T065 [US3] Wrap all write-tool bodies (`codegiraffe_init`, `codegiraffe_sync`, `codegiraffe_sync_files`, `codegiraffe_add_relation`, `codegiraffe_add_contract`, `codegiraffe_annotate`, `codegiraffe_domains` mutations, `codegiraffe_coverage`) in `with _graph_lock:` in `src/codegiraffe/server.py`
- [ ] T066 [US3] Wrap all read-tool bodies in `with _graph_lock:` — protect the section from `_ensure_graph` through the return statement in `src/codegiraffe/server.py`
- [ ] T067 [US3] Update dashboard `init_graph` handlers in `src/codegiraffe/dashboard.py` and `src/codegiraffe/dashboard_server.py` to acquire `_graph_lock` before writing to `srv._graph` and `srv._storage`
- [ ] T068 [US3] Import `_graph_lock` in dashboard modules or pass it via the server interface (e.g., as a parameter to `get_or_start_server`)

### Verification

- [ ] T069 [US3] Run RED tests from T060–T062 and verify GREEN
- [ ] T070 [US3] Run full test suite to verify no deadlocks or regressions
- [ ] T071 [US3] Manually start the dashboard (`codegiraffe_dashboard`) and run MCP tool calls concurrently to verify no hangs

**Checkpoint**: User Story 3 complete. Concurrent access is safe.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final validation, cleanup, and documentation

- [ ] T072 Run full test suite one final time and compare pass count and timing against T001 baseline (SC-001, SC-006)
- [ ] T073 Update CLAUDE.md Known Limitation section — remove the DiGraph single-edge warning and document MultiDiGraph migration
- [ ] T074 Update CLAUDE.md Key Patterns section to reference new helper methods (`get_edge_between`, `get_typed_edge`, etc.)
- [ ] T075 [P] Review all `# TODO` or `# FIXME` comments in changed files for any leftover migration artifacts
- [ ] T076 Run `python -m pytest tests/ -v --tb=short` to confirm zero warnings related to deprecated DiGraph patterns

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Phase 2 — core migration must be in place
- **US2 (Phase 4)**: Depends on Phase 2 only (not US1) — can run in parallel with US1
- **US3 (Phase 5)**: Depends on Phase 2 only (not US1 or US2) — can run in parallel
- **Polish (Phase 6)**: Depends on all user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Depends on Foundational (Phase 2). Most tasks are sequential within query.py but parallelizable across files.
- **User Story 2 (P2)**: Depends on Foundational (Phase 2) only. Fully independent of US1 — can start immediately after Phase 2.
- **User Story 3 (P3)**: Depends on Foundational (Phase 2) only. Fully independent of US1 and US2 — can start immediately after Phase 2.

### Within Each User Story

- Tests MUST be written and FAIL before implementation
- Implementation tasks within the same file are sequential
- Implementation tasks across different files are parallelizable (marked [P])
- Verification tasks run after all implementation tasks

### Parallel Opportunities

**Phase 2 (Foundational)**: All 10 test tasks (T003–T012) can run in parallel. Implementation is sequential within graph.py.

**Phase 3 (US1)**:
- All 8 test tasks (T024–T031) in parallel
- query.py Pattern A tasks (T032–T035) are sequential (same file) but can run in parallel with scanner.py tasks (T044–T046) and domains.py tasks (T047)
- server.py task (T043) can run in parallel with any non-server.py task

**Phase 4 (US2)**: All 4 test tasks (T051–T054) in parallel. Implementation is sequential (2 tasks in same file).

**Phase 5 (US3)**: All 3 test tasks (T060–T062) in parallel. Implementation is mostly sequential in server.py.

---

## Parallel Example: Phase 3 (User Story 1)

```text
# Wave 1: Launch all US1 tests in parallel
T024, T025, T026, T027, T028, T029, T030, T031

# Wave 2: Parallel implementation across files
  Agent A: query.py (T032→T033→T034→T035→T036→T037→T038→T039→T040→T041→T042)
  Agent B: scanner.py (T044→T045→T046)
  Agent C: domains.py (T047) + server.py (T043)

# Wave 3: Verification
T048, T049, T050
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001–T002)
2. Complete Phase 2: Foundational (T003–T023) — core MultiDiGraph migration
3. Complete Phase 3: User Story 1 (T024–T050) — all edge access sites updated
4. **STOP and VALIDATE**: Run full test suite, scan codegiraffe itself, verify multi-edges preserved
5. This alone delivers the primary value — correct graph data

### Incremental Delivery

1. Setup + Foundational → MultiDiGraph works in graph.py
2. Add US1 → All edge access sites updated → Full pipeline preserves multi-edges (MVP)
3. Add US2 → Cypher injection blocked → Security hardened
4. Add US3 → Concurrent access safe → Production-ready
5. Polish → Documentation updated → Feature complete

### Parallel Team Strategy

With multiple agents after Phase 2:

- Agent A: User Story 1 (query.py + scanner.py — most work)
- Agent B: User Story 2 (neo4j_storage.py — independent, small scope)
- Agent C: User Story 3 (server.py locking — independent)

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks
- [Story] label maps task to specific user story for traceability
- Constitution VI requires TDD — all test tasks write RED tests before implementation
- Line numbers reference the codebase as of 2026-02-25 (branch `032-graph-correctness`) and may shift during implementation
- The `keys=False` pattern (Decision D2 from research.md) is the lowest-risk migration approach — 1-token change per site
- Total: 76 tasks across 6 phases

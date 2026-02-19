# Tasks: Fix Documentation Audit Findings

**Input**: Design documents from `/specs/031-fix-docs-audit/`
**Prerequisites**: plan.md, spec.md

**Tests**: No new tests required. Existing test suite must pass after server.py docstring change.

**Organization**: Tasks grouped by user story. Each story can be implemented and verified independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup

**Purpose**: No setup needed — all changes are edits to existing files.

*(No tasks in this phase)*

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: No foundational work needed — each story edits independent files.

*(No tasks in this phase)*

---

## Phase 3: User Story 1 — Tool Parameter Docs Match Actual Signatures (Priority: P1)

**Goal**: Every documented tool parameter matches the actual function signature in server.py. Zero discrepancies in types, defaults, action names, schemas, and format values.

**Independent Test**: For each tool doc, diff every parameter claim against the actual `@mcp.tool()` function signature. Zero mismatches.

### Implementation for User Story 1

- [ ] T001 [P] [US1] Fix `codegiraffe_coverage` format values and default in docs/tools/change-impact.md — change `"coverage.py"` to `"coverage_py"`, add `"auto"` as default, mark `format` as optional (FR-001, FR-008)
- [ ] T002 [P] [US1] Fix `codegiraffe_pr_diff` `head_ref` to show as optional with default `"HEAD"`, add undocumented `scanner_mode` param in docs/tools/change-impact.md (FR-007)
- [ ] T003 [P] [US1] Fix `codegiraffe_order_tasks` task schema in docs/tools/planning.md — replace `id`/`description`/`dependencies` with `name`/`target_files` (FR-002)
- [ ] T004 [P] [US1] Fix `codegiraffe_domains` actions in docs/tools/planning.md — replace `"create"`/`"update"` with `"add"`/`"remove"` (FR-003)
- [ ] T005 [P] [US1] Fix `codegiraffe_domains` `node_ids` type in docs/tools/planning.md — change `list[str]` to `str` (comma-separated) (FR-004)
- [ ] T006 [P] [US1] Fix `codegiraffe_migration_plan` `target_nodes` type in docs/tools/planning.md — change `list[str]` to `str | None` (JSON array string) (FR-005)
- [ ] T007 [P] [US1] Fix `codegiraffe_sync_files` `file_paths` type in docs/tools/core.md — change `list[str]` to `str` (comma-separated or JSON array) (FR-006)
- [ ] T008 [P] [US1] Fix `_retrieval_strategy` values in docs/embeddings.md — replace `keyword/embedding/impact/change_aware/combined` with actual values `create/debug/refactor/delete/test/modify` (FR-022)
- [ ] T009 [P] [US1] Fix `_retrieval_strategy` values in docs/tools/context-and-analysis.md — same correction as T008 (FR-022)
- [ ] T010 [P] [US1] Fix `codegiraffe_blast_radius` return description in docs/tools/context-and-analysis.md — change from JSON to markdown text (FR-023)
- [ ] T011 [P] [US1] Remove `"coverage"` field from `codegiraffe_risk_assessment` example in docs/tools/context-and-analysis.md (FR-024)
- [ ] T012 [P] [US1] Fix `codegiraffe_patterns` output description in docs/tools/context-and-analysis.md — replace multi-cluster with single-cluster: `naming_pattern`, `exemplar`, `common_attributes`, `outliers` (FR-025)
- [ ] T013 [P] [US1] Add `contains=1.0` to confidence table in docs/edge-confidence.md (FR-026)

**Checkpoint**: All 37 tool parameter docs now match actual function signatures.

---

## Phase 4: User Story 2 — Dashboard Documentation Reflects Sigma.js v3 (Priority: P1)

**Goal**: All dashboard-related documentation describes the current Sigma.js v3 + Graphology implementation. Zero Cytoscape.js references anywhere.

**Independent Test**: Grep all docs and server.py for "Cytoscape" — zero results. Dashboard.md describes 7 layouts, color-only edges, circular nodes, and actual interaction patterns.

### Implementation for User Story 2

- [ ] T014 [P] [US2] Rewrite docs/dashboard.md — replace Cytoscape.js with Sigma.js v3 + Graphology, update to 7 layouts (original, force, circular, grid, concentric, breadthfirst, random), describe color-only edge differentiation, circular nodes with color coding, remove double-click subgraph focus claim, document `layout` extra for ForceAtlas2 (FR-010, FR-011, FR-012, FR-013, FR-014, FR-015)
- [ ] T015 [P] [US2] Replace "Cytoscape.js" with "Sigma.js v3" in docs/architecture.md (FR-010)
- [ ] T016 [P] [US2] Replace "Cytoscape.js" with "Sigma.js v3" in docs/tools/core.md `codegiraffe_dashboard` description (FR-010)
- [ ] T017 [P] [US2] Replace "Interactive Cytoscape.js graph visualization" with "Interactive Sigma.js v3 graph visualization" in README.md (FR-010)
- [ ] T018 [P] [US2] Fix `codegiraffe_dashboard` docstring in src/codegiraffe/server.py — replace "Cytoscape.js" with "Sigma.js v3" (FR-027)

**Checkpoint**: Zero "Cytoscape" references in docs or production code. Dashboard docs accurately describe Sigma.js v3.

---

## Phase 5: User Story 3 — Version History and Counts Are Current (Priority: P2)

**Goal**: All numeric claims and module listings are accurate. v0.14.0 is documented in the roadmap.

**Independent Test**: Compare README/CLAUDE.md/roadmap numbers against `pytest --co` output and `ls src/codegiraffe/`. All match.

### Implementation for User Story 3

- [ ] T019 [P] [US3] Update test count in README.md from "1318+" to "1452+" (FR-016)
- [ ] T020 [P] [US3] Update Core tool count in README.md from 7 to 8, update description to include `codegiraffe_dashboard` (FR-018)
- [ ] T021 [P] [US3] Update test count in CLAUDE.md from "1339+" to "1452+" (FR-017)
- [ ] T022 [P] [US3] Add `layout.py`, `dashboard_server.py`, and `assets/` to CLAUDE.md module listing (FR-020)
- [ ] T023 [P] [US3] Add `layout.py` and `dashboard_server.py` to docs/architecture.md module table (FR-020)
- [ ] T024 [US3] Add v0.14.0 entry to docs/roadmap.md documenting Sigma.js v3 migration, layout.py, dashboard_server.py, fa2 optional dep, and test count (FR-019)

**Checkpoint**: All numeric claims verified. v0.14.0 fully documented in roadmap.

---

## Phase 6: User Story 4 — CI Workflow Fix (Priority: P2)

**Goal**: `codegiraffe-pr.yml` imports the correct function name.

**Independent Test**: `python -c "from codegiraffe.query import suggest_tests"` succeeds.

### Implementation for User Story 4

- [ ] T025 [US4] Fix `suggest_tests_for_changes` import to `suggest_tests` in .github/workflows/codegiraffe-pr.yml (FR-009)

**Checkpoint**: CI workflow Python imports resolve without error.

---

## Phase 7: User Story 5 — Optional Extras Documentation (Priority: P3)

**Goal**: All pyproject.toml optional dependency groups are documented in getting-started.

**Independent Test**: Every `[project.optional-dependencies]` group in pyproject.toml has a corresponding entry in docs/getting-started.md.

### Implementation for User Story 5

- [ ] T026 [US5] Add `layout` extra (`fa2>=0.1`) to optional dependencies section in docs/getting-started.md (FR-021)

**Checkpoint**: All optional extras documented.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Final validation across all changes.

- [ ] T027 Run `grep -ri "cytoscape" docs/ README.md CLAUDE.md src/codegiraffe/server.py` to confirm zero remaining Cytoscape.js references
- [ ] T028 Run `source .venv/bin/activate && python -m pytest tests/ -x -q` to confirm all tests still pass after server.py docstring change
- [ ] T029 Verify version history range in README.md says "v0.2.0–v0.14.0" (not "v0.2.0–v0.13.0")

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: N/A
- **Foundational (Phase 2)**: N/A
- **User Stories (Phases 3–7)**: All independent — can run in any order or in parallel
- **Polish (Phase 8)**: Depends on ALL user stories being complete

### User Story Dependencies

- **US1 (P1)**: No dependencies. Edits 5 doc files independently.
- **US2 (P1)**: No dependencies. Edits 5 files independently. (T017 edits README.md — no conflict with US3's T019/T020 which edit different lines)
- **US3 (P2)**: No dependencies. Edits 4 files independently.
- **US4 (P2)**: No dependencies. Edits 1 file.
- **US5 (P3)**: No dependencies. Edits 1 file.

### Parallel Opportunities

All tasks within each story are marked [P] (except T024 and T025 which are single-file edits). All 5 user stories can run in parallel since they edit different files (with minor overlap on README.md and docs/tools/core.md, but at different sections).

**Maximum parallelism**: All 26 implementation tasks (T001–T026) can run simultaneously since they target different sections of different files.

**Practical parallelism**: Run US1 + US2 in parallel (highest priority), then US3 + US4 + US5 in parallel, then Polish.

---

## Implementation Strategy

### MVP First (US1 + US2)

1. Complete US1 (tool parameter fixes) — eliminates all runtime-error-causing docs
2. Complete US2 (Sigma.js rewrite) — eliminates all wrong-technology claims
3. **STOP and VALIDATE**: Grep for Cytoscape, spot-check tool params
4. These two stories fix all CRITICAL and HIGH severity issues

### Incremental Delivery

1. US1 + US2 → All CRITICAL + HIGH issues fixed
2. US3 → All stale numbers and listings updated
3. US4 → CI workflow fixed
4. US5 → Missing extras documented
5. Polish → Final validation pass

---

## Notes

- All tasks are [P] (parallelizable) because they edit different files or different sections
- No new files created — all edits to existing files
- Only source code change: server.py docstring (T018) — must verify tests still pass
- T014 (dashboard.md rewrite) is the largest task — the entire file needs updating for Sigma.js
- Total: 29 tasks across 5 user stories + 3 polish tasks

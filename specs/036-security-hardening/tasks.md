---

description: "Task list for Phase 5: Security Hardening"
---

# Tasks: Security Hardening

**Input**: Design documents from `/specs/036-security-hardening/`
**Prerequisites**: plan.md, spec.md

**Organization**: Tasks are grouped by user story. US1 and US2 are P1 and must ship first. US3 and US4 are P2 and can proceed in parallel after the P1 stories are complete. US5 and US6 are P3 and can proceed in parallel with each other and with US3/US4. All test tasks within a story are written before the implementation tasks.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create spec directory in worktree and ensure the test conftest foundation is ready before any story tests reference it.

- [ ] T001 [US6] Create `tests/conftest.py` canonical git helper block: add `_GIT_ENV` dict, `_git()`, `_init_repo()`, `_commit_file()`, and `_commit_files()` module-level functions to `tests/conftest.py` (they have no pytest decorator — plain functions importable by test modules)
- [ ] T002 [US6] Add canonical `reset_server_state` fixture to `tests/conftest.py`: resets `server_module._graph`, `_storage` (new `JSONStorage()`), `_version_store` (new `VersionStore()`), `_federation` (new `GraphFederation()`), and `_initialized_project_paths` (`set()`) before and after each test; fixture has `autouse=False` scope `"function"` so consuming files opt in

**Checkpoint**: `conftest.py` additions present; existing tests still pass (`python -m pytest tests/ -x -q`)

---

## Phase 2: User Story 6 — Consolidated Test Infrastructure (Priority: P3)

**Goal**: Remove all local duplicates of `reset_server_state` and git helpers; all consumers import from `conftest.py`.

**Independent Test**: `grep -rn "def reset_server_state" tests/` returns exactly one result (in `conftest.py`). `grep -rn "^_GIT_ENV\|^def _git\|^def _init_repo\|^def _commit_file" tests/` returns results only in `conftest.py`.

### Tests for User Story 6

> **Write these first — they should FAIL before the migrations happen**

- [ ] T003 [P] [US6] Write `tests/test_fixture_consolidation.py`: test that `reset_server_state` fixture is defined in `conftest.py` (importable from `tests.conftest`); test that `_git`, `_init_repo`, `_commit_file`, `_commit_files` are defined in `conftest.py`; test that none of the consuming test files define local copies (parse file with `ast.parse` and check `FunctionDef` names)

### Implementation for User Story 6

- [ ] T004 [US6] Migrate `tests/test_server.py`: remove local `reset_server_state` fixture (lines 30–37); add `pytestmark = pytest.mark.usefixtures("reset_server_state")` at module level; verify all imports still satisfied
- [ ] T005 [US6] Migrate `tests/test_server_integration.py`: remove local `reset_server_state` fixture (lines 52–60); add `pytestmark = pytest.mark.usefixtures("reset_server_state")` at module level; ensure `VersionStore` and `GraphFederation` reset is covered by canonical fixture
- [ ] T006 [US6] Migrate `tests/test_server_validate_changes.py`: remove local `reset_server_state` fixture (lines 31–36); add `pytestmark = pytest.mark.usefixtures("reset_server_state")`
- [ ] T007 [US6] Migrate `tests/test_context_for_changes.py`: remove local `reset_server_state` fixture (lines 27–32); add `pytestmark = pytest.mark.usefixtures("reset_server_state")`
- [ ] T008 [US6] Migrate `tests/test_task_ordering.py`: remove class-level `reset_server_state` method (lines 312–317) from `TestOrderTasksTool`; add `@pytest.mark.usefixtures("reset_server_state")` on the class
- [ ] T009 [US6] Migrate `tests/test_git_utils.py`: remove local `_GIT_ENV`, `_git`, `_init_repo`, `_commit_file` (lines 28–60); import from `conftest` using `from tests.conftest import _GIT_ENV, _git, _init_repo, _commit_file` or rely on pytest's conftest auto-import; verify tests still pass
- [ ] T010 [US6] Migrate `tests/test_file_coupling.py`: remove local `_GIT_ENV`, `_git`, `_init_repo`, `_commit_files` (lines 23–55); import canonical versions from `conftest`
- [ ] T011 [US6] Migrate `tests/test_graph_diff.py`: remove local `_GIT_ENV`, `_git`, `_init_repo`, `_commit_file` (lines 45–75); import canonical versions from `conftest`
- [ ] T012 [US6] Run full test suite; confirm 0 failures and no cross-test state pollution: `python -m pytest tests/ -x -q`

**Checkpoint**: User Story 6 fully migrated — fixtures live in exactly one place, suite passes

---

## Phase 3: User Story 1 — Dashboard Path Guard (Priority: P1)

**Goal**: The dashboard `/api/init` endpoint rejects paths not previously initialized via MCP tools.

**Independent Test**: `POST /api/init` with `project_path="/etc"` returns HTTP 403. A path initialized via `codegiraffe_init()` is accepted.

### Tests for User Story 1

> **Write these first — they should FAIL before implementation**

- [ ] T013 [P] [US1] Write `tests/test_dashboard_path_guard.py` — unit tests for the `init_graph` route:
  - `test_uinitialized_path_rejected`: mock `srv._initialized_project_paths = set()`, POST `/api/init` with arbitrary path → assert HTTP 403, error message contains "must be initialized"
  - `test_initialized_path_accepted`: set `srv._initialized_project_paths = {"/tmp/myproject"}`, mock `scan_project` to return empty result, POST `/api/init` with `/tmp/myproject` → assert HTTP 200
  - `test_malicious_path_rejected`: POST `/api/init` with `project_path="/etc/passwd"` when not in allowlist → assert HTTP 403
  - `test_traversal_path_rejected`: POST `/api/init` with `project_path="../../sensitive"` when not in allowlist → assert HTTP 403
  - `test_graph_routes_still_work_for_initialized_project`: after adding to allowlist and initializing, GET `/api/graph` with initialized path → not rejected
- [ ] T014 [P] [US1] Write integration test: `test_codegiraffe_init_populates_allowlist` in `tests/test_server.py` — call `codegiraffe_init()` on a `tmp_path` project, then assert `srv._initialized_project_paths` contains the path

### Implementation for User Story 1

- [ ] T015 [US1] Add `_initialized_project_paths: set[str] = set()` to `server.py` module globals (after `_graph_lock = threading.RLock()`); protect writes with `_graph_lock`
- [ ] T016 [US1] In `codegiraffe_init()` success path in `server.py`: after `_graph = graph` assignment (under `_graph_lock`), add `_initialized_project_paths.add(project_path)`
- [ ] T017 [US1] Update canonical `reset_server_state` fixture in `conftest.py` to reset `srv._initialized_project_paths = set()` (in both setup and teardown halves)
- [ ] T018 [US1] Add path guard to `init_graph()` route in `dashboard.py` (line 1254, before `scan_project()`): import `codegiraffe.server as srv`, check `project_path not in srv._initialized_project_paths` → return `JSONResponse({"error": "Project must be initialized via MCP tools (codegiraffe_init) before the dashboard can use it."}, status_code=403)`; acquire `srv._graph_lock` for the read

**Checkpoint**: US1 acceptance scenarios pass; `POST /api/init` with unknown path → 403; known path → 200

---

## Phase 4: User Story 2 — Symlink Boundary Check (Priority: P1)

**Goal**: The scanner skips symlinks pointing outside the project root and follows internal ones.

**Independent Test**: Scan a project containing an external symlink; verify the symlink target is not read and a warning is emitted.

### Tests for User Story 2

> **Write these first — they should FAIL before implementation**

- [ ] T019 [P] [US2] Write `tests/test_scanner_symlinks.py`:
  - `test_external_file_symlink_skipped`: create `tmp_path/project/` with `link.py -> /etc/passwd`; scan `project/`; assert no node with `file_path` containing "passwd" or "link.py"; assert `UserWarning` is issued
  - `test_external_dir_symlink_skipped`: create `tmp_path/project/` with `ext_dir -> /tmp` (points outside); scan; assert no nodes from the symlinked directory
  - `test_internal_symlink_followed`: create `tmp_path/project/real.py` and `tmp_path/project/alias.py -> real.py`; scan; assert both paths produce nodes (internal symlink is safe)
  - `test_no_symlinks_unchanged`: create normal project with no symlinks; scan; assert behavior identical to before (baseline regression)
  - `test_circular_symlink_skipped`: create `tmp_path/project/a -> b` and `tmp_path/project/b -> a` (circular); scan; assert no infinite loop, warning is issued

### Implementation for User Story 2

- [ ] T020 [US2] Add `_is_within_root(path: Path, root: Path) -> bool` helper function to `scanner.py` (before `scan_project()`): uses `path.resolve().relative_to(root.resolve())`; catches `ValueError` (outside root) and `OSError` (circular/broken symlinks); returns `False` in both error cases
- [ ] T021 [US2] In `scan_project()` loop (after `source_file.is_file()` check at line 2145, before `_should_skip()` call): add `if source_file.is_symlink() and not _is_within_root(source_file, root): warnings.warn(f"Skipping symlink outside project root: {source_file}", stacklevel=2); continue`; add `import warnings` at top of file if not present
- [ ] T022 [US2] Run symlink-specific tests; confirm all pass: `python -m pytest tests/test_scanner_symlinks.py -v`

**Checkpoint**: US2 acceptance scenarios 1–4 pass; no regression in existing scanner tests

---

## Phase 5: User Story 3 — Subprocess Timeouts (Priority: P2)

**Goal**: All git commands in `git_utils.py` have a 30-second timeout; `GitTimeoutError` is raised on expiry.

**Independent Test**: Mock `subprocess.run` to raise `subprocess.TimeoutExpired`; verify `GitTimeoutError` is raised with a message naming the command and timeout.

**Parallel opportunity**: US3 (T023–T027) and US4 (T028–T032) can be worked in parallel — they touch different files.

### Tests for User Story 3

> **Write these first — they should FAIL before implementation**

- [ ] T023 [P] [US3] Write `tests/test_git_utils_timeout.py`:
  - `test_is_git_repo_timeout`: patch `subprocess.run` to raise `TimeoutExpired(["git", "rev-parse"], 30)`; call `is_git_repo(tmp_path)`; assert returns `False` (timeout treated as not-a-repo, no crash) OR raises `GitTimeoutError` — confirm with spec: the error must be *recoverable*, so `is_git_repo` should catch and return `False`
  - `test_get_uncommitted_diff_timeout`: patch `subprocess.run` to raise `TimeoutExpired`; call `get_uncommitted_diff(tmp_path_git_repo)`; assert raises `GitTimeoutError`
  - `test_get_changed_files_timeout`: same pattern → `get_changed_files()` returns `[]` on timeout (consistent with current `returncode != 0` path) OR raises `GitTimeoutError`; confirm desired behavior
  - `test_get_commit_file_history_timeout`: patch raises `TimeoutExpired`; `get_commit_file_history()` → returns `[]` or raises `GitTimeoutError`
  - `test_fast_command_unaffected`: real git command on `tmp_path` git repo completes normally within timeout; assert no error
  - `test_timeout_error_message_contains_command_and_duration`: `GitTimeoutError` message must contain the git subcommand name and "30s" or "30 seconds"

### Implementation for User Story 3

- [ ] T024 [US3] Add `GitTimeoutError(GitError)` class to `git_utils.py` (after `NotAGitRepoError`): `"""Raised when a git command exceeds its timeout."""`
- [ ] T025 [US3] Add module-level constant `GIT_COMMAND_TIMEOUT: int = 30` to `git_utils.py`
- [ ] T026 [US3] Add `timeout=GIT_COMMAND_TIMEOUT` to every `subprocess.run()` call in `git_utils.py` (5 call sites: lines 27, 51, 61, 81, 110)
- [ ] T027 [US3] Add `subprocess.TimeoutExpired` handling to each function:
  - `is_git_repo()`: catch `TimeoutExpired`, return `False` (safe degradation — treat as not-a-repo)
  - `get_uncommitted_diff()`: catch `TimeoutExpired`, raise `GitTimeoutError(f"Git command timed out after {GIT_COMMAND_TIMEOUT}s: git diff HEAD")`
  - `get_changed_files()`: catch `TimeoutExpired`, return `[]` (consistent with error path)
  - `get_commit_file_history()`: catch `TimeoutExpired`, return `[]` (consistent with error path)
  - Note: the fallback `subprocess.run` in `get_uncommitted_diff` (line 61) also needs `timeout=` and `TimeoutExpired` handling

**Checkpoint**: US3 acceptance scenarios pass; fast commands unaffected; slow/hung commands terminate and return clear errors

---

## Phase 6: User Story 4 — Dashboard XSS Escaping (Priority: P2)

**Goal**: All graph-derived content in the dashboard is escaped before being set via `innerHTML`.

**Independent Test**: Load a graph with a node whose type is `<img src=x onerror=alert(1)>`; verify the dashboard HTML contains `&lt;img` not `<img`.

**Parallel opportunity**: US4 can run alongside US3.

### Tests for User Story 4

> **Write these first — they should FAIL before implementation**

- [ ] T028 [P] [US4] Write `tests/test_dashboard_xss.py` — test `get_graph_json()` response and the rendered HTML:
  - `test_type_distribution_escapes_node_type`: create a graph with a node of type `'<script>alert(1)</script>'`; call `get_graph_json()`; assert the JSON node type value survives as-is (JSON is safe); then render the type-distribution HTML string (extract from dashboard.py inline JS by mocking) and assert it would use `escapeHtml`
  - `test_special_chars_in_node_type_escaped`: node type `"service & tools"` → distribution HTML contains `service &amp; tools`, not `service & tools`
  - `test_legend_type_keys_escaped`: confirm `buildLegend()` applies `escapeHtml` to type keys
  - `test_normal_type_names_unaffected`: node type `"module"` → displays as `"module"` (no corruption)
  - Note: because these are embedded JS strings inside Python, test the Python-level rendered HTML string using `get_main_html()` or by extracting the relevant JS snippet via regex

### Implementation for User Story 4

- [ ] T029 [US4] In `dashboard.py`, locate the type distribution `innerHTML` builder (around line 783): change `html += '...' + t + '...'` to `html += '...' + escapeHtml(t) + '...'` for the `dist-label` span text — all three occurrences in that loop where `t` appears as literal HTML text
- [ ] T030 [US4] In `dashboard.py`, locate the `buildLegend()` function (around line 829): change `html += '...' + t + '...'` for the legend item text to use `escapeHtml(t)` for both the `TYPE_COLORS` loop and the `edgeStyles` loop
- [ ] T031 [US4] Verify `escapeHtml` is already in scope for both modified code sections (it is defined at line 476 in the same `<script>` block — confirm it precedes both call sites in the rendered HTML order)
- [ ] T032 [US4] Run dashboard tests to ensure no regression: `python -m pytest tests/test_dashboard.py tests/test_dashboard_xss.py -v`

**Checkpoint**: US4 acceptance scenarios pass; normal node names render identically

---

## Phase 7: User Story 5 — Bounded Resource Consumption (Priority: P3)

**Goal**: `depth` and `max_depth` parameters on MCP tools are capped at documented maximums; excessive values are silently clamped.

**Independent Test**: Call `codegiraffe_query(project_path, node_id="...", depth=999999)` → executes without error and behaves as if `depth=20` was passed.

**Parallel opportunity**: US5 (T033–T038) can run alongside US6 (T001–T012 already done in Phase 1–2) and alongside US3/US4.

### Tests for User Story 5

> **Write these first — they should FAIL before implementation**

- [ ] T033 [P] [US5] Write `tests/test_depth_bounds.py`:
  - `test_query_depth_capped`: call `codegiraffe_query(project_path, node_id="...", depth=1000000)`; mock `query_by_node` to capture `depth` arg; assert captured depth == `MAX_QUERY_DEPTH` (20)
  - `test_query_depth_within_bounds_unchanged`: call with `depth=5`; assert captured depth == 5
  - `test_blast_radius_max_depth_capped`: call `codegiraffe_blast_radius(project_path, node_id="...", max_depth=1000000)`; mock `compute_blast_radius`; assert `max_depth` arg == `MAX_BLAST_DEPTH` (20)
  - `test_blast_radius_none_uses_max`: call with `max_depth=None`; assert `max_depth` arg == `MAX_BLAST_DEPTH` (never unlimited)
  - `test_file_coupling_depth_capped`: call `codegiraffe_file_coupling(project_path, depth=999999)`; mock `file_coupling`; assert captured `depth` == `MAX_COUPLING_DEPTH` (500)
  - `test_export_depth_capped`: call `codegiraffe_export(project_path, node_id="...", depth=999999)`; mock `graph.get_subgraph`; assert depth arg == `MAX_QUERY_DEPTH`
  - `test_cross_query_depth_capped`: call `codegiraffe_cross_query("repo::node", depth=999999)`; mock `_federation.query_federated`; assert depth == `MAX_QUERY_DEPTH`
  - `test_constants_are_named`: import `MAX_QUERY_DEPTH`, `MAX_COUPLING_DEPTH`, `MAX_BLAST_DEPTH` from `codegiraffe.server`; assert all are `int` and > 0

### Implementation for User Story 5

- [ ] T034 [US5] Add named constants to `server.py` after `_graph_lock` definition:
  ```python
  MAX_QUERY_DEPTH: int = 20    # Maximum graph traversal hops
  MAX_COUPLING_DEPTH: int = 500  # Maximum git log commits to mine
  MAX_BLAST_DEPTH: int = 20    # Maximum blast-radius traversal hops
  ```
- [ ] T035 [US5] In `codegiraffe_query()`: add `depth = min(depth, MAX_QUERY_DEPTH)` before the `if node_id is not None:` branch
- [ ] T036 [US5] In `codegiraffe_blast_radius()`: add `max_depth = min(max_depth, MAX_BLAST_DEPTH) if max_depth is not None else MAX_BLAST_DEPTH` before `compute_blast_radius()` call
- [ ] T037 [US5] In `codegiraffe_file_coupling()`: add `depth = min(depth, MAX_COUPLING_DEPTH)` before `file_coupling()` call
- [ ] T038 [US5] In `codegiraffe_export()`: add `depth = min(depth, MAX_QUERY_DEPTH)` before `graph.get_subgraph()` call; in `codegiraffe_cross_query()`: add `depth = min(depth, MAX_QUERY_DEPTH)` before `_federation.query_federated()` call

**Checkpoint**: US5 acceptance scenarios pass; normal values unaffected; extreme values clamped

---

## Phase 8: Polish and Verification

**Purpose**: Final suite run, known-failing test audit, and cleanup.

- [ ] T039 [P] Audit for known-failing tests: run `python -m pytest tests/ -v --tb=no -q 2>&1 | grep FAILED`; for any legitimately broken tests that are pre-existing (not introduced by this branch), add `@pytest.mark.xfail(reason="...", strict=False)` with a descriptive reason string (FR-011)
- [ ] T040 Run complete test suite and confirm no regressions: `python -m pytest tests/ -x -q`; target is all pre-existing passing tests continue to pass
- [ ] T041 [P] Verify no local fixture duplicates remain: `grep -rn "def reset_server_state" tests/` must return exactly 1 result; `grep -rn "^_GIT_ENV\s*=" tests/` must return exactly 1 result
- [ ] T042 [P] Verify no unescaped innerHTML with graph-derived variables in dashboard.py: `grep -n "innerHTML.*+ t +" src/codegiraffe/dashboard.py` must return 0 results (all `t` uses now wrapped in `escapeHtml`)
- [ ] T043 [P] Verify all subprocess.run calls have timeout: `grep -n "subprocess.run" src/codegiraffe/git_utils.py` output must show `timeout=` on every call site

---

## Dependencies and Execution Order

### Phase Dependencies

```
Phase 1: Setup (T001–T002)
  → US6 migration (Phase 2, T003–T012)   -- foundation for all other tests
  → US1 (Phase 3, T013–T018)             -- P1, start after Phase 1
  → US2 (Phase 4, T019–T022)             -- P1, start after Phase 1; parallel with US1
  → US3 (Phase 5, T023–T027)             -- P2, start after P1 stories done
  → US4 (Phase 6, T028–T032)             -- P2, parallel with US3
  → US5 (Phase 7, T033–T038)             -- P3, parallel with US3/US4
  → Polish (Phase 8, T039–T043)          -- after all stories complete
```

### Parallel Opportunities

Within each story, the `[P]` test tasks can be dispatched simultaneously. Between stories:

```
Parallel A: US1 tests (T013) + US2 tests (T019) — both P1, different files
Parallel B: US3 tests (T023) + US4 tests (T028) + US5 tests (T033) — all in different files
Parallel C: Polish tasks T039, T041, T042, T043 — independent verification steps
```

### Within Each Story

1. Write failing tests (marked `[P]` tasks within a story can be written together)
2. Confirm tests FAIL (no implementation yet)
3. Implement in dependency order (model → service → integration)
4. Run story tests: `python -m pytest tests/test_<story>.py -v`
5. Run full suite: `python -m pytest tests/ -x -q`
6. Advance to next story

---

## Implementation Strategy

### MVP First (P1 Stories Only)

1. Complete Phase 1: Setup (T001–T002)
2. Complete Phase 2: US6 fixture migration
3. Complete Phase 3: US1 dashboard path guard
4. Complete Phase 4: US2 symlink boundary check
5. **STOP and VALIDATE**: both P1 stories independently testable, full suite green

### Incremental Delivery

1. Setup + US6 → foundation ready, no duplicate fixtures
2. US1 → dashboard path guard live
3. US2 → scanner symlink protection live
4. US3 + US4 (parallel) → subprocess timeouts + XSS escaping
5. US5 → parameter bounds
6. Polish → suite clean, known-failing tests marked

---

## Notes

- `[P]` = different files, no shared state dependency — safe to work in parallel
- `[US#]` = user story traceability from spec.md
- Tests must FAIL before each implementation phase — verify with `python -m pytest tests/test_<story>.py -v --tb=short`
- The `reset_server_state` fixture in conftest must reset `_initialized_project_paths` (US1) — Phase 1 T002 is intentionally written to include this field so US1 tests work without a second conftest edit
- Do not commit partial stories — commit atomically per story after its checkpoint passes
- Constants (`MAX_QUERY_DEPTH`, etc.) must be importable from `codegiraffe.server` for test assertions (T033)

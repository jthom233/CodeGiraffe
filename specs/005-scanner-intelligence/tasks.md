# Tasks: Scanner Intelligence Improvements (v0.4.0)

**Input**: Design documents from `/specs/005-scanner-intelligence/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md

**Tests**: Required — Constitution Principle VI (Test-First) is NON-NEGOTIABLE. TDD enforced.

**Organization**: Tasks grouped by user story. US1 and US2 are P1 (MVP). US3 and US4 are P2.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story (US1, US2, US3, US4)
- Exact file paths included in all descriptions

---

## Phase 1: Setup

**Purpose**: Verify baseline and prepare branch

- [ ] T001 Verify all 426 existing tests pass on branch `005-scanner-intelligence` by running `python -m pytest tests/ -v`
- [ ] T002 Create tests/test_schema.py with initial test structure (empty test class)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Schema extension and shared utilities that ALL user stories depend on

**CRITICAL**: No user story work can begin until this phase is complete

- [ ] T003 [P] Add `MODULE = "module"` to `NodeType` enum in src/codegiraffe/schema.py (FR-012)
- [ ] T004 [P] Add `IMPORTS = "imports"`, `IMPLEMENTS = "implements"`, `CONTAINS = "contains"` to `EdgeType` enum in src/codegiraffe/schema.py (FR-013)
- [ ] T005 [P] Write tests for new NodeType.MODULE and EdgeType.IMPORTS/IMPLEMENTS/CONTAINS enum values in tests/test_schema.py
- [ ] T006 Add `_file_to_module_path(file_path: Path, project_path: str) -> str` utility function to src/codegiraffe/scanner.py — converts absolute file path to dotted module path (e.g., `/home/user/project/src/codegiraffe/graph.py` → `codegiraffe.graph`). Must handle src-layout, flat-layout, and `__init__.py` → package name. Per research R6.
- [ ] T007 Add `_is_test_file(file_path: Path) -> bool` predicate to src/codegiraffe/scanner.py — returns True for `test_*.py`, `*_test.py`, `conftest.py` filenames. Per research R4.
- [ ] T008 Add `include_tests: bool = False` parameter to `scan_project()` signature in src/codegiraffe/scanner.py — no behavior change yet, just the parameter.
- [ ] T009 Write tests for `_file_to_module_path()` (src-layout, flat-layout, `__init__.py`, nested packages) and `_is_test_file()` (positive and negative cases) in tests/test_scanner.py

**Checkpoint**: Schema extended, utilities ready. All 426+ tests still pass.

---

## Phase 3: User Story 1 — Clean Scan Without Test Noise (Priority: P1) MVP

**Goal**: Scanner excludes test files by default and filters patterns inside strings/comments. Self-scan produces <20 test-derived nodes.

**Independent Test**: Run `codegiraffe_init` on `/home/dr4zz/projects/codegiraffe`. Count nodes with `source: test` or test class names. Must be <20 (down from 108).

### Tests for User Story 1 (TDD — write FIRST, verify they FAIL)

- [ ] T010 [P] [US1] Write test: scanner excludes files under `tests/` directory by default in tests/test_scanner.py
- [ ] T011 [P] [US1] Write test: scanner excludes `test_*.py` and `*_test.py` files outside test directories in tests/test_scanner.py
- [ ] T012 [P] [US1] Write test: scanner excludes `conftest.py` files in tests/test_scanner.py
- [ ] T013 [P] [US1] Write test: `include_tests=True` scans test files but tags nodes with `source: test` metadata in tests/test_scanner.py
- [ ] T014 [P] [US1] Write test: `_strip_strings_and_comments()` removes triple-quoted strings, single-line comments, and quoted strings in tests/test_scanner.py
- [ ] T015 [P] [US1] Write test: PythonRecognizer does NOT detect `@app.route("/fake")` inside a docstring in tests/test_scanner.py
- [ ] T016 [P] [US1] Write test: PythonRecognizer does NOT detect `class FakeService:` inside a triple-quoted string in tests/test_scanner.py
- [ ] T017 [P] [US1] Write test: PythonRecognizer does NOT detect `os.getenv("FAKE")` inside a comment in tests/test_scanner.py

### Implementation for User Story 1

- [ ] T018 [US1] Add `"tests"` and `"test"` to `_IGNORE_DIRS` frozenset in src/codegiraffe/scanner.py. Modify `_should_skip()` to consult `_is_test_file()` when `include_tests=False` (new parameter threaded through). Per plan Phase B.
- [ ] T019 [US1] Implement test file metadata tagging: when `include_tests=True` and `_is_test_file()` returns True, add `source: test` to each node's metadata dict in src/codegiraffe/scanner.py
- [ ] T020 [US1] Implement `_strip_strings_and_comments(text: str) -> str` in src/codegiraffe/scanner.py — regex-based removal of triple-quoted strings, single-line comments, and quoted strings with escape handling. Per research R5 Approach A.
- [ ] T021 [US1] Apply `_strip_strings_and_comments()` to content at the start of `PythonRecognizer.recognize()` in src/codegiraffe/scanner.py — pass cleaned content to all regex pattern matching.
- [ ] T022 [US1] Add `include_tests` parameter to `codegiraffe_init` and `codegiraffe_sync` tool definitions in src/codegiraffe/server.py, passing through to `scan_project()`.
- [ ] T023 [US1] Write integration test: `codegiraffe_init` with `include_tests=False` (default) excludes test nodes in tests/test_server_integration.py

**Checkpoint**: US1 complete. Self-scan of codegiraffe should produce <20 test-derived nodes. All tests green.

---

## Phase 4: User Story 2 — Import-Based Dependency Graph (Priority: P1) MVP

**Goal**: Scanner detects Python import statements and creates `imports` edges between project-internal modules. Self-scan produces 30+ import edges.

**Independent Test**: Run `codegiraffe_init` on codegiraffe. Query for `imports` edge type. Must find 30+ edges with symbol metadata.

**Depends on**: Phase 2 (schema + module path utility) and US4 Phase 6 (module nodes as edge targets). **Note**: Module node creation (T030–T031) must be implemented before import edge targets can resolve. If implementing sequentially, complete Phase 6 T030–T031 first.

### Tests for User Story 2 (TDD — write FIRST, verify they FAIL)

- [ ] T024 [P] [US2] Write test: `from codegiraffe.graph import ArchGraph` creates `imports` edge from source module to `mod:codegiraffe.graph` with `symbols: ["ArchGraph"]` metadata in tests/test_scanner.py
- [ ] T025 [P] [US2] Write test: `import os` does NOT create an import edge (stdlib filtering via `sys.stdlib_module_names`) in tests/test_scanner.py
- [ ] T026 [P] [US2] Write test: `import requests` does NOT create an import edge (third-party filtering) in tests/test_scanner.py
- [ ] T027 [P] [US2] Write test: `from . import graph` resolves to `mod:codegiraffe.graph` (relative import resolution) in tests/test_scanner.py
- [ ] T028 [P] [US2] Write test: multiple imports from same module produce ONE edge with combined symbols list in tests/test_scanner.py
- [ ] T029 [P] [US2] Write test: self-imports (module importing itself) are excluded in tests/test_scanner.py

### Implementation for User Story 2

- [ ] T030 [US2] Add `_IMPORT_RE` regex pattern to src/codegiraffe/scanner.py — matches `import X`, `from X import Y`, `from X import Y, Z`. Capture module path and imported symbols.
- [ ] T031 [US2] Add `_RELATIVE_IMPORT_RE` regex pattern to src/codegiraffe/scanner.py — matches `from . import X`, `from ..X import Y`. Capture dot count, module path, and symbols.
- [ ] T032 [US2] Implement `_resolve_import(import_path: str, current_file: Path, project_path: str, dot_count: int) -> str | None` in src/codegiraffe/scanner.py — resolves import to dotted module path, returns None for stdlib/third-party. Uses `sys.stdlib_module_names` per research R1.
- [ ] T033 [US2] Implement import detection in `PythonRecognizer.recognize()` in src/codegiraffe/scanner.py — collect all imports, resolve them, create `imports` edges with `{symbols: [...], style: "absolute"|"relative"}` metadata. Deduplicate: one edge per (source, target) with merged symbols. Per plan Phase D.
- [ ] T034 [US2] Implement project-internal module set building in `scan_project()` in src/codegiraffe/scanner.py — before per-file scanning, build a set of all `.py` file module paths for internal import filtering.
- [ ] T035 [P] [US2] Write tests for AST-mode import detection (tree-sitter `import_statement` and `import_from_statement` queries) in tests/test_ast_scanner.py
- [ ] T036 [US2] Add tree-sitter import queries and import edge creation to `PythonASTRecognizer` in src/codegiraffe/ast_scanner.py

**Checkpoint**: US2 complete. Self-scan produces 30+ import edges. Stdlib/third-party filtered. All tests green.

---

## Phase 5: User Story 3 — Inheritance and Protocol Relationships (Priority: P2)

**Goal**: Scanner detects class inheritance and creates `implements` edges. Self-scan shows 10+ implements edges.

**Independent Test**: Run `codegiraffe_init` on codegiraffe. Query for `implements` edges. Must find SQLiteStorage→StorageBackend, GoRecognizer→PatternRecognizer, etc.

### Tests for User Story 3 (TDD — write FIRST, verify they FAIL)

- [ ] T037 [P] [US3] Write test: `class SQLiteStorage(StorageBackend):` creates `implements` edge from `service:SQLiteStorage` to `service:StorageBackend` in tests/test_scanner.py
- [ ] T038 [P] [US3] Write test: `class MyClass(Base, Mixin):` creates two `implements` edges (one per base) in tests/test_scanner.py
- [ ] T039 [P] [US3] Write test: base class in different file resolved via cross-file class registry in tests/test_scanner.py
- [ ] T040 [P] [US3] Write test: base class NOT in project (e.g., `Pydantic BaseModel`) does NOT create `implements` edge in tests/test_scanner.py

### Implementation for User Story 3

- [ ] T041 [US3] Enhance `_CLASS_DEF_RE` regex to capture base classes in Group 2: `^class\s+(\w+)(?:\(([^)]*?)\))?\s*:` in src/codegiraffe/scanner.py. Per research R3.
- [ ] T042 [US3] Build class name → node ID registry during scan in `scan_project()` in src/codegiraffe/scanner.py — map each discovered class name to its `service:ClassName` node ID across all files.
- [ ] T043 [US3] Implement inheritance edge creation: for each class with base classes, look up each base in the registry. If found, create `implements` edge with `{inferred: true, cross_file: true/false}` metadata. Extend `_infer_cross_file_edges()` in src/codegiraffe/scanner.py. Per research R7.
- [ ] T044 [P] [US3] Write tests for AST-mode inheritance detection in tests/test_ast_scanner.py
- [ ] T045 [US3] Add tree-sitter class inheritance query (class definition with superclasses field) and `implements` edge creation to `PythonASTRecognizer` in src/codegiraffe/ast_scanner.py

**Checkpoint**: US3 complete. Self-scan shows 10+ implements edges for storage backends, recognizers, protocols. All tests green.

---

## Phase 6: User Story 4 — Module-Level Architecture View (Priority: P2)

**Goal**: Scanner creates module nodes for each source file and `contains` edges to their defined entities. Self-scan shows 15+ module nodes.

**Independent Test**: Run `codegiraffe_init` on codegiraffe. Query `node_type="module"`. Must find `mod:codegiraffe.graph`, `mod:codegiraffe.scanner`, etc. Each should have `contains` edges to classes defined within.

### Tests for User Story 4 (TDD — write FIRST, verify they FAIL)

- [ ] T046 [P] [US4] Write test: scanning a .py file creates a `module` type node with `mod:` ID prefix in tests/test_scanner.py
- [ ] T047 [P] [US4] Write test: `__init__.py` creates a package-level module node (e.g., `mod:codegiraffe`) in tests/test_scanner.py
- [ ] T048 [P] [US4] Write test: `contains` edges connect module node to class nodes defined within it in tests/test_scanner.py
- [ ] T049 [P] [US4] Write test: module node has correct `file_path` and `package` metadata in tests/test_scanner.py

### Implementation for User Story 4

- [ ] T050 [US4] Implement module node creation in `scan_project()` in src/codegiraffe/scanner.py — for each scanned file, create a `module` type node using `_file_to_module_path()` with ID `mod:<dotted.path>`, label = module name, metadata = `{package: "...", source: "production"}`.
- [ ] T051 [US4] Implement `contains` edge creation in `scan_project()` in src/codegiraffe/scanner.py — after per-file recognition, create `contains` edges from the file's module node to each entity node discovered in that file.
- [ ] T052 [P] [US4] Write tests for AST-mode module node creation and contains edges in tests/test_ast_scanner.py
- [ ] T053 [US4] Add module node creation and contains edge creation to AST scanner flow in src/codegiraffe/ast_scanner.py

**Checkpoint**: US4 complete. Self-scan shows 15+ module nodes with contains edges. All tests green.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Dashboard update, version bump, dogfood validation, documentation

- [ ] T054 [P] Add `module` to `TYPE_COLORS` (amber/orange) and `TYPE_SHAPES` (round-rectangle) in src/codegiraffe/dashboard.py
- [ ] T055 [P] Add `imports`, `implements`, `contains` edge type styling (line style, color) in src/codegiraffe/dashboard.py
- [ ] T056 [P] Bump version to `0.4.0` in pyproject.toml
- [ ] T057 Run full test suite: `python -m pytest tests/ -v` — verify all 426 existing + 60+ new tests pass (SC-006)
- [ ] T058 Self-scan dogfood validation: run `codegiraffe_init` on codegiraffe project and verify SC-001 (<20 test nodes), SC-002 (30+ import edges), SC-003 (10+ implements edges), SC-004 (15+ module nodes), SC-007 (dashboard renders connected graph)
- [ ] T059 Update README.md with v0.4.0 scanner improvements, new node/edge types, and `include_tests` parameter documentation
- [ ] T060 Update CLAUDE.md project structure section with new schema entries and scanner features

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Foundational only — can start after Phase 2
- **US4 (Phase 6)**: Depends on Foundational only — can start after Phase 2
- **US2 (Phase 4)**: Depends on Foundational AND US4 T050–T051 (module nodes must exist as import edge targets)
- **US3 (Phase 5)**: Depends on Foundational only — can start after Phase 2
- **Polish (Phase 7)**: Depends on all user stories being complete

### User Story Dependencies

- **US1 (P1)**: Independent — no cross-story dependencies
- **US4 (P2)**: Independent — module nodes are self-contained
- **US2 (P1)**: Requires US4 module node creation (T050–T051) for edge targets
- **US3 (P2)**: Independent — inheritance edges use existing service nodes

### Recommended Execution Order

1. Phase 1 → Phase 2 (Setup + Foundational)
2. US1 (Phase 3) + US4 (Phase 6) in parallel (both independent)
3. US2 (Phase 4) after US4 module nodes complete
4. US3 (Phase 5) in parallel with US2
5. Phase 7 (Polish) after all stories

### Parallel Opportunities

**Within Phase 2**: T003, T004, T005 can all run in parallel (different files/sections)
**US1 tests**: T010–T017 can all run in parallel (independent test cases)
**US2 tests**: T024–T029 can all run in parallel
**US3 tests**: T037–T040 can all run in parallel
**US4 tests**: T046–T049 can all run in parallel
**Cross-story**: US1 and US4 can run in parallel after Foundational
**Cross-story**: US2 and US3 can run in parallel after US4 T050–T051

---

## Parallel Example: US1 Tests

```bash
# Launch all US1 tests in parallel (all in different test functions, same file):
Task: "T010 Write test: scanner excludes tests/ directory"
Task: "T011 Write test: scanner excludes test_*.py files"
Task: "T012 Write test: scanner excludes conftest.py"
Task: "T013 Write test: include_tests=True tags nodes"
Task: "T014 Write test: string stripping utility"
Task: "T015 Write test: route in docstring not detected"
Task: "T016 Write test: class in string not detected"
Task: "T017 Write test: env var in comment not detected"
```

---

## Implementation Strategy

### MVP First (US1 + US4 → US2)

1. Complete Phase 1: Setup (verify baseline)
2. Complete Phase 2: Foundational (schema + utilities)
3. Complete Phase 3: US1 — Clean scan (biggest impact: removes 108 false nodes)
4. Complete Phase 6: US4 — Module nodes (creates targets for import edges)
5. Complete Phase 4: US2 — Import edges (30+ new edges connect the graph)
6. **STOP and VALIDATE**: Self-scan of codegiraffe should show a clean, connected graph
7. Deploy/demo if ready

### Full Delivery

1. Setup + Foundational → foundation ready
2. US1 (test exclusion) → clean graph, independently testable
3. US4 (module nodes) → module-level view, independently testable
4. US2 (import edges) → connected graph, independently testable
5. US3 (inheritance) → class hierarchies, independently testable
6. Polish → dashboard, version bump, documentation

---

## Notes

- [P] tasks = different files or independent test functions, no dependencies
- [Story] label maps task to specific user story for traceability
- TDD enforced per Constitution Principle VI — tests MUST fail before implementation
- US2 has a structural dependency on US4 (module nodes as edge targets)
- Commit after each completed phase or logical task group
- Stop at any checkpoint to validate the story independently

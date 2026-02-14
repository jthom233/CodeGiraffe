# Tasks: Scanner Depth (v0.9.0)

**Input**: Design documents from `/specs/009-scanner-depth/`
**Prerequisites**: plan.md, spec.md

**Tests**: Required -- Constitution Principle VI (Test-First) is NON-NEGOTIABLE. TDD enforced.

**Organization**: Tasks grouped by phase. Phases 2, 4, and 5 can run in parallel after Phase 1. Phase 3 depends on Phase 2. Phase 6 is last.

## Format: `[ID] [P?] [Phase] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Phase]**: Which implementation phase (P1-P6)
- Exact file paths included in all descriptions

---

## Phase 1: Data Model Extension (Serial -- Must Go First)

**Purpose**: New data classes (`CallInfo`, `InterfaceInfo`, `MethodSetEntry`) and `ScanResult` extension that ALL subsequent phases depend on.

**CRITICAL**: No feature work can begin until this phase is complete.

### Tests (TDD -- write FIRST, verify they FAIL)

- [ ] T001 [P] [P1] Write test: `CallInfo` has `caller`, `callee`, `receiver`, `file_path`, `style` fields with correct defaults in tests/test_scanner.py
- [ ] T002 [P] [P1] Write test: `InterfaceInfo` has `name`, `methods`, `file_path` fields with correct defaults in tests/test_scanner.py
- [ ] T003 [P] [P1] Write test: `MethodSetEntry` has `struct_name`, `method_name`, `file_path` fields in tests/test_scanner.py
- [ ] T004 [P] [P1] Write test: `ScanResult()` has empty `calls` list by default in tests/test_scanner.py
- [ ] T005 [P] [P1] Write test: `ScanResult()` has empty `interfaces` list by default in tests/test_scanner.py
- [ ] T006 [P] [P1] Write test: `ScanResult()` has empty `method_sets` list by default in tests/test_scanner.py
- [ ] T007 [P] [P1] Write test: `ScanResult.merge()` extends `calls` from other in tests/test_scanner.py
- [ ] T008 [P] [P1] Write test: `ScanResult.merge()` extends `interfaces` from other in tests/test_scanner.py
- [ ] T009 [P] [P1] Write test: `ScanResult.merge()` extends `method_sets` from other in tests/test_scanner.py

### Implementation

- [ ] T010 [P1] Add `CallInfo` dataclass after `ImplementationInfo` in src/codegiraffe/scanner.py -- fields: `caller: str`, `callee: str`, `receiver: str = ""`, `file_path: str = ""`, `style: str = "direct"`
- [ ] T011 [P1] Add `InterfaceInfo` dataclass after `CallInfo` in src/codegiraffe/scanner.py -- fields: `name: str`, `methods: list[str] = field(default_factory=list)`, `file_path: str = ""`
- [ ] T012 [P1] Add `MethodSetEntry` dataclass after `InterfaceInfo` in src/codegiraffe/scanner.py -- fields: `struct_name: str`, `method_name: str`, `file_path: str = ""`
- [ ] T013 [P1] Extend `ScanResult` with three new fields: `calls: list[CallInfo]`, `interfaces: list[InterfaceInfo]`, `method_sets: list[MethodSetEntry]` -- all with `field(default_factory=list)` defaults in src/codegiraffe/scanner.py
- [ ] T014 [P1] Extend `ScanResult.merge()` with three new `extend` calls for `calls`, `interfaces`, `method_sets` in src/codegiraffe/scanner.py
- [ ] T015 [P1] Extend per-file collection variables in `scan_project()` to include `file_calls`, `file_interfaces`, `file_method_sets` and extend the per-recognizer loop and `ScanResult` construction in src/codegiraffe/scanner.py

**Checkpoint**: 9 new tests pass. All 793 existing tests still pass. Data model ready for Phases 2-5.

---

## Phase 2: Recognizer Call Detection (Depends on Phase 1)

**Purpose**: Each recognizer extracts function/method calls and returns `CallInfo` records. Go, Python, TypeScript are priority; remaining 6 languages get basic detection.

### Tests (TDD -- write FIRST)

#### Go Call Detection -- tests/test_call_detection.py (new file)

- [ ] T016 [P] [P2] Write test: Go `s.Store.Save()` produces `CallInfo` with `receiver="Store"`, `callee="Save"`, `style="method"` in tests/test_call_detection.py
- [ ] T017 [P] [P2] Write test: Go `store.NewSQLiteStore()` produces `CallInfo` with `receiver="store"`, `callee="NewSQLiteStore"` in tests/test_call_detection.py
- [ ] T018 [P] [P2] Write test: Go `HandleKeyEvent(msg)` produces `CallInfo` with `callee="HandleKeyEvent"`, `style="direct"` in tests/test_call_detection.py
- [ ] T019 [P] [P2] Write test: Go stdlib calls (`fmt.Println()`, `log.Fatal()`) are excluded from calls list in tests/test_call_detection.py
- [ ] T020 [P] [P2] Write test: Go call inside `func (a *App) Update()` has `caller="App.Update"` in tests/test_call_detection.py
- [ ] T021 [P] [P2] Write test: Go interface with 2 methods produces `InterfaceInfo` record in tests/test_call_detection.py
- [ ] T022 [P] [P2] Write test: Go struct with method receiver produces `MethodSetEntry` records in tests/test_call_detection.py
- [ ] T023 [P] [P2] Write test: Go function with 3 calls produces 3 `CallInfo` records in tests/test_call_detection.py

#### Python Call Detection -- tests/test_call_detection.py

- [ ] T024 [P] [P2] Write test: Python `self.process()` produces `CallInfo(style="method")` in tests/test_call_detection.py
- [ ] T025 [P] [P2] Write test: Python `MyService()` produces `CallInfo(style="constructor")` in tests/test_call_detection.py
- [ ] T026 [P] [P2] Write test: Python `db.query()` produces `CallInfo` with `receiver="db"` in tests/test_call_detection.py
- [ ] T027 [P] [P2] Write test: Python builtins (`print()`, `len()`, `range()`) are excluded from calls list in tests/test_call_detection.py
- [ ] T028 [P] [P2] Write test: Python call inside `def handle_request` has `caller="handle_request"` in tests/test_call_detection.py

#### TypeScript Call Detection -- tests/test_call_detection.py

- [ ] T029 [P] [P2] Write test: TypeScript `this.render()` produces `CallInfo(style="method")` in tests/test_call_detection.py
- [ ] T030 [P] [P2] Write test: TypeScript `service.fetchData()` produces `CallInfo` with receiver in tests/test_call_detection.py
- [ ] T031 [P] [P2] Write test: TypeScript `new UserService()` produces `CallInfo(style="constructor")` in tests/test_call_detection.py
- [ ] T032 [P] [P2] Write test: TypeScript builtins (`console.log()`, `JSON.parse()`) are excluded in tests/test_call_detection.py

#### Other Languages -- tests/test_call_detection.py

- [ ] T033 [P] [P2] Write test: Java basic method call detection works in tests/test_call_detection.py
- [ ] T034 [P] [P2] Write test: Rust basic method call detection works in tests/test_call_detection.py
- [ ] T035 [P] [P2] Write test: C# basic method call detection works in tests/test_call_detection.py
- [ ] T036 [P] [P2] Write test: PHP basic method call detection works in tests/test_call_detection.py
- [ ] T037 [P] [P2] Write test: Ruby basic method call detection works in tests/test_call_detection.py
- [ ] T038 [P] [P2] Write test: C++ basic method call detection works in tests/test_call_detection.py

### Implementation

#### Go Recognizer -- src/codegiraffe/recognizers/go.py

- [ ] T039 [P2] Add regex constants for call detection: `_GO_FUNC_CALL_RE` (method calls), `_GO_PLAIN_CALL_RE` (plain exported functions), `_GO_FUNC_DEF_RE` (enclosing function context), `_GO_STDLIB_PACKAGES` frozenset in src/codegiraffe/recognizers/go.py
- [ ] T040 [P2] Add `_find_enclosing_func()` helper function (maps line numbers to enclosing function names) in src/codegiraffe/recognizers/go.py
- [ ] T041 [P2] Extend `GoRecognizer.recognize()` with call detection logic -- iterate `_GO_FUNC_CALL_RE` and `_GO_PLAIN_CALL_RE` matches, filter stdlib, determine enclosing function, produce `CallInfo` records in src/codegiraffe/recognizers/go.py
- [ ] T042 [P2] Extend `GoRecognizer.recognize()` to emit `InterfaceInfo` records from existing interface detection data in src/codegiraffe/recognizers/go.py
- [ ] T043 [P2] Extend `GoRecognizer.recognize()` to emit `MethodSetEntry` records from existing struct method detection data in src/codegiraffe/recognizers/go.py
- [ ] T044 [P2] Update `GoRecognizer.recognize()` return statement to include `calls`, `interfaces`, `method_sets` in the `ScanResult` in src/codegiraffe/recognizers/go.py

#### Python Recognizer -- src/codegiraffe/scanner.py

- [ ] T045 [P2] Add regex constants for Python call detection: `_PY_SELF_CALL_RE`, `_PY_CONSTRUCTOR_CALL_RE`, `_PY_METHOD_CALL_RE`, `_PY_FUNC_DEF_RE`, `_PY_BUILTINS` frozenset in src/codegiraffe/scanner.py
- [ ] T046 [P2] Extend `PythonRecognizer.recognize()` with call detection logic -- detect `self.method()`, `ClassName()`, `obj.method()` patterns, filter builtins, determine enclosing function, produce `CallInfo` records in src/codegiraffe/scanner.py
- [ ] T047 [P2] Update `PythonRecognizer.recognize()` return statement to include `calls` in the `ScanResult` in src/codegiraffe/scanner.py

#### TypeScript Recognizer -- src/codegiraffe/recognizers/typescript.py

- [ ] T048 [P2] Add regex constants for TypeScript call detection: `_TS_THIS_CALL_RE`, `_TS_METHOD_CALL_RE`, `_TS_CONSTRUCTOR_CALL_RE`, `_TS_FUNC_DEF_RE`, `_TS_BUILTINS` frozenset in src/codegiraffe/recognizers/typescript.py
- [ ] T049 [P2] Extend `TypeScriptRecognizer.recognize()` with call detection logic and include `calls` in the `ScanResult` in src/codegiraffe/recognizers/typescript.py

#### Remaining Recognizers (basic call detection, ~30-50 lines each)

- [ ] T050 [P] [P2] Add basic call detection to `JavaRecognizer.recognize()` -- detect `obj.method()`, `ClassName.staticMethod()`, `new ClassName()`, filter blocklist in src/codegiraffe/recognizers/java.py
- [ ] T051 [P] [P2] Add basic call detection to `RustRecognizer.recognize()` -- detect `obj.method()`, `Module::function()`, filter blocklist in src/codegiraffe/recognizers/rust.py
- [ ] T052 [P] [P2] Add basic call detection to `CSharpRecognizer.recognize()` -- detect `obj.Method()`, `ClassName.StaticMethod()`, `new ClassName()`, filter blocklist in src/codegiraffe/recognizers/csharp.py
- [ ] T053 [P] [P2] Add basic call detection to `PHPRecognizer.recognize()` -- detect `$obj->method()`, `ClassName::staticMethod()`, `new ClassName()`, filter blocklist in src/codegiraffe/recognizers/php.py
- [ ] T054 [P] [P2] Add basic call detection to `RubyRecognizer.recognize()` -- detect `obj.method()`, `ClassName.new`, filter blocklist in src/codegiraffe/recognizers/ruby.py
- [ ] T055 [P] [P2] Add basic call detection to `CppRecognizer.recognize()` -- detect `obj.method()`, `obj->method()`, `namespace::function()`, `new ClassName()`, filter blocklist in src/codegiraffe/recognizers/cpp.py

**Checkpoint**: 24 new tests pass. All recognizers emit `CallInfo` records. Total: 793 + 9 + 24 = 826+ tests.

---

## Phase 3: Inference Pipeline (Depends on Phases 1 and 2)

**Purpose**: Two new inference functions (`_infer_interface_satisfaction`, `_infer_call_edges`) that process raw `CallInfo`/`InterfaceInfo`/`MethodSetEntry` data into graph edges. Also `_resolve_call_participant` helper for symbol resolution and demand-driven method node creation.

### Tests (TDD -- write FIRST) -- tests/test_call_graph.py (new file)

#### TestInferCallEdges

- [ ] T056 [P] [P3] Write test: two nodes exist (caller, callee), `CallInfo` links them, verify `calls` edge created in tests/test_call_graph.py
- [ ] T057 [P] [P3] Write test: same call appears twice, only one edge created (deduplication) in tests/test_call_graph.py
- [ ] T058 [P] [P3] Write test: `CallInfo` references callee not in graph, no edge created (external call filtered) in tests/test_call_graph.py
- [ ] T059 [P] [P3] Write test: `CallInfo` references `Store.Save`, `Store` exists but `Save` doesn't, verify demand-driven method node `service:Store.Save` created with `kind: method` metadata in tests/test_call_graph.py
- [ ] T060 [P] [P3] Write test: demand-driven method node gets `contains` edge from its parent class node in tests/test_call_graph.py
- [ ] T061 [P] [P3] Write test: same method referenced from two callers, only one method node created (deduplication) in tests/test_call_graph.py
- [ ] T062 [P] [P3] Write test: `calls` edge has `inferred`, `caller`, `callee`, `style` metadata fields in tests/test_call_graph.py
- [ ] T063 [P] [P3] Write test: `CallInfo` where caller == callee does not create an edge (no self-loops) in tests/test_call_graph.py
- [ ] T064 [P] [P3] Write test: empty `calls` list produces no edges, no crash in tests/test_call_graph.py

#### TestInferInterfaceSatisfaction

- [ ] T065 [P] [P3] Write test: interface in file1 with methods `["Save", "Load"]`, struct in file2 with methods `{"Save", "Load", "Delete"}`, verify `ImplementationInfo` emitted in tests/test_call_graph.py
- [ ] T066 [P] [P3] Write test: struct has only 1 of 2 required methods, no match (subset required) in tests/test_call_graph.py
- [ ] T067 [P] [P3] Write test: struct has exactly the interface's methods, matches in tests/test_call_graph.py
- [ ] T068 [P] [P3] Write test: if `ImplementationInfo` already exists (same-file matching), don't add duplicate in tests/test_call_graph.py
- [ ] T069 [P] [P3] Write test: two structs both satisfy same interface, both get `ImplementationInfo` in tests/test_call_graph.py
- [ ] T070 [P] [P3] Write test: one struct satisfies two different interfaces in tests/test_call_graph.py
- [ ] T071 [P] [P3] Write test: interface with no methods does not match anything (empty set edge case) in tests/test_call_graph.py

#### TestMethodNodeCreation

- [ ] T072 [P] [P3] Write test: method node ID format is `service:{Parent}.{Method}` in tests/test_call_graph.py
- [ ] T073 [P] [P3] Write test: method node type is `NodeType.SERVICE` in tests/test_call_graph.py
- [ ] T074 [P] [P3] Write test: method node `metadata["kind"] == "method"` in tests/test_call_graph.py
- [ ] T075 [P] [P3] Write test: method node `metadata["parent"]` is set correctly in tests/test_call_graph.py
- [ ] T076 [P] [P3] Write test: method node `metadata["method_name"]` is set correctly in tests/test_call_graph.py

#### TestCallGraphIntegration

- [ ] T077 [P3] Write test: synthetic Go files with cross-file calls, run `scan_project()`, verify `calls` edges in tests/test_call_graph.py
- [ ] T078 [P3] Write test: synthetic Python files with `self.method()` calls, run `scan_project()`, verify `calls` edges in tests/test_call_graph.py
- [ ] T079 [P3] Write test: Go files with interface in one file and implementor in another, verify `implements` edge via cross-file satisfaction in tests/test_call_graph.py
- [ ] T080 [P3] Write test: scan project, get blast_radius for callee node, verify callers appear as impacted in tests/test_call_graph.py
- [ ] T081 [P3] Write test: scan project with no detectable calls, output identical to v0.8.0 (backward compat, no regression) in tests/test_call_graph.py

### Implementation

- [ ] T082 [P3] Implement `_resolve_call_participant()` helper function in src/codegiraffe/scanner.py -- resolve caller/callee name to graph node ID via symbol registry, method node registry, class fallback, and demand-driven method node creation
- [ ] T083 [P3] Implement `_infer_interface_satisfaction()` in src/codegiraffe/scanner.py -- collect `InterfaceInfo`/`MethodSetEntry` across all files, perform cross-file duck-type matching, emit `ImplementationInfo` records (mutates `result.implementations` in place). Must run BEFORE `_infer_inheritance_edges_universal`.
- [ ] T084 [P3] Implement `_infer_call_edges()` in src/codegiraffe/scanner.py -- build symbol registry from `result.nodes`, process all `CallInfo` records, resolve caller/callee to node IDs, create `calls` edges with metadata, deduplicate. Must run AFTER inheritance inference, BEFORE `_infer_contract_edges`.
- [ ] T085 [P3] Integrate `_infer_interface_satisfaction()` into `scan_project()` pipeline -- insert BEFORE `_infer_inheritance_edges_universal()` call in src/codegiraffe/scanner.py
- [ ] T086 [P3] Integrate `_infer_call_edges()` into `scan_project()` pipeline -- insert AFTER `_infer_inheritance_edges()` and BEFORE `_infer_contract_edges()` call in src/codegiraffe/scanner.py

**Checkpoint**: 26 new tests pass. Call-graph inference pipeline complete. Demand-driven method nodes working. Total: 826 + 26 = 852+ tests.

---

## Phase 4: Tree-Sitter AST Call Detection (Parallel with Phase 3 after Phase 1)

**Purpose**: Wire existing tree-sitter call expression queries (`_GO_CALL_QUERY`, `_TS_CALL_QUERY`) to produce `CallInfo` records. Add Python AST call detection.

### Tests -- tests/test_ast_scanner.py (modify existing)

- [ ] T087 [P] [P4] Write test: Go AST call detection produces `CallInfo` records in `ScanResult` (skip if no tree-sitter) in tests/test_ast_scanner.py
- [ ] T088 [P] [P4] Write test: Go AST filters stdlib calls (`fmt.Println()` not in calls) (skip if no tree-sitter) in tests/test_ast_scanner.py
- [ ] T089 [P] [P4] Write test: TypeScript AST call detection produces `CallInfo` records (skip if no tree-sitter) in tests/test_ast_scanner.py
- [ ] T090 [P] [P4] Write test: Python AST call detection produces `CallInfo` records (skip if no tree-sitter) in tests/test_ast_scanner.py
- [ ] T091 [P4] Write test: AST and regex modes produce compatible `CallInfo` results for same Go file (skip if no tree-sitter) in tests/test_ast_scanner.py

### Implementation

- [ ] T092 [P4] Add `_GO_AST_STDLIB_PACKAGES` constant to src/codegiraffe/ast_scanner.py (or import from scanner.py)
- [ ] T093 [P4] Add `GoASTRecognizer._find_calls()` method -- use `_GO_CALL_QUERY` to extract call expressions, convert to `CallInfo` records, filter stdlib in src/codegiraffe/ast_scanner.py
- [ ] T094 [P4] Add `GoASTRecognizer._find_enclosing_func_ast()` method -- walk tree-sitter parents to find enclosing `function_declaration`/`method_declaration` in src/codegiraffe/ast_scanner.py
- [ ] T095 [P4] Extend `GoASTRecognizer.recognize()` to call `_find_calls()` and include `calls` in returned `ScanResult` in src/codegiraffe/ast_scanner.py
- [ ] T096 [P4] Add `_PY_CALL_QUERY` tree-sitter query constant for Python call expressions in src/codegiraffe/ast_scanner.py
- [ ] T097 [P4] Extend `PythonASTRecognizer.recognize()` to extract call expressions via tree-sitter and produce `CallInfo` records in src/codegiraffe/ast_scanner.py
- [ ] T098 [P4] Extend `TypeScriptASTRecognizer.recognize()` to use `_TS_CALL_QUERY` and produce `CallInfo` records in src/codegiraffe/ast_scanner.py

**Checkpoint**: 5 new tests pass (all `@pytest.mark.skipif` when tree-sitter unavailable). Total: 852 + 5 = 857+ tests.

---

## Phase 5: Improved Interface/Implementation Validation (Parallel with Phases 3-4 after Phase 1)

**Purpose**: Verify and fix edge cases in existing `implements` detection across all recognizers. Primarily validation with targeted fixes.

### Tests -- tests/test_recognizers.py (modify existing)

- [ ] T099 [P] [P5] Write test: TypeScript `class Foo implements Bar, Baz` produces 2 `ImplementationInfo` records in tests/test_recognizers.py
- [ ] T100 [P] [P5] Write test: TypeScript `class Foo implements Bar<string>` produces `ImplementationInfo(parent_class="Bar")` (generic stripped) in tests/test_recognizers.py
- [ ] T101 [P] [P5] Write test: TypeScript `class Foo extends Base implements Bar` produces both extends and implements in tests/test_recognizers.py
- [ ] T102 [P] [P5] Write test: Java `class Foo implements Bar, Baz` produces 2 `ImplementationInfo` records in tests/test_recognizers.py
- [ ] T103 [P] [P5] Write test: C# `class Foo : BaseClass, IInterface` distinguishes base class from interface correctly in tests/test_recognizers.py

### Implementation

- [ ] T104 [P5] Verify and fix `_TS_CLASS_IMPLEMENTS_RE` in src/codegiraffe/recognizers/typescript.py to handle multiple interfaces, generic interfaces, and extends+implements combination
- [ ] T105 [P5] Verify and fix Java `_JAVA_CLASS_IMPLEMENTS_RE` for multi-interface `implements Foo, Bar` in src/codegiraffe/recognizers/java.py
- [ ] T106 [P5] Verify and fix Rust `_RUST_IMPL_TRAIT_RE` for `impl Trait for Struct` basic case in src/codegiraffe/recognizers/rust.py
- [ ] T107 [P5] Verify and fix C# `_CS_CLASS_INHERITANCE_RE` for interface vs base class disambiguation (I-prefix convention) in src/codegiraffe/recognizers/csharp.py
- [ ] T108 [P5] Verify PHP `_PHP_CLASS_IMPL_RE` for multi-interface and Ruby `_RB_CLASS_INHERIT_RE` for `include Module` in src/codegiraffe/recognizers/php.py and src/codegiraffe/recognizers/ruby.py
- [ ] T109 [P5] Verify C++ `_CPP_CLASS_INHERITANCE_RE` for `class Foo : public IBar` in src/codegiraffe/recognizers/cpp.py

**Checkpoint**: 5 new tests pass. Total: 857 + 5 = 862+ tests.

---

## Phase 6: Polish (Last -- Depends on All Feature Phases)

**Purpose**: Version bump, documentation updates, final verification. No new features.

- [ ] T110 [P6] Bump `version` from `"0.8.0"` to `"0.9.0"` in pyproject.toml
- [ ] T111 [P6] Update CLAUDE.md: version line to 0.9.0, test count to 862+, add `CallInfo`/`InterfaceInfo`/`MethodSetEntry` to Code Style section, add `calls` edge documentation (enum existed, now populated), update scanner description
- [ ] T112 [P6] Add Recent Changes entry for v0.9.0 in CLAUDE.md: "Scanner depth -- call-graph edges (calls), cross-file Go interface satisfaction, demand-driven method nodes; CallInfo/InterfaceInfo/MethodSetEntry data classes; _infer_call_edges() and _infer_interface_satisfaction() pipeline steps; call detection in all 9 language recognizers + AST scanner; 862+ tests"
- [ ] T113 [P6] Run full test suite: `source .venv/bin/activate && python -m pytest tests/ -v` -- verify all 793 existing tests pass unchanged AND 69+ new tests pass
- [ ] T114 [P6] Self-scan dogfood validation: run `codegiraffe_init` on codegiraffe project and verify `calls` edges appear in the graph

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Data Model)**: No dependencies -- start immediately. BLOCKS all other phases.
- **Phase 2 (Recognizer Call Detection)**: Depends on Phase 1.
- **Phase 3 (Inference Pipeline)**: Depends on Phases 1 AND 2 (needs `CallInfo` data from recognizers).
- **Phase 4 (AST Scanner)**: Depends on Phase 1 only. Can run in parallel with Phases 2/3/5.
- **Phase 5 (Interface Validation)**: Depends on Phase 1 only. Can run in parallel with Phases 2/3/4.
- **Phase 6 (Polish)**: Depends on ALL feature phases (2, 3, 4, 5).

### Dependency Graph

```
Phase 1 (Data Model)
  |
  +---> Phase 2 (Recognizer Call Detection) ---> Phase 3 (Inference Pipeline) ---+
  |                                                                               |
  +---> Phase 4 (AST Scanner) ---------------------------------------------------+
  |                                                                               |
  +---> Phase 5 (Interface Validation) ------------------------------------------+
                                                                                  |
                                                                                  v
                                                                         Phase 6 (Polish)
```

### Parallel Opportunities

**Phase 1 tests**: T001-T009 can all run in parallel (independent test cases in same file)
**Phase 2 tests**: T016-T038 can all run in parallel (independent test cases)
**Phase 2 recognizer impls**: T050-T055 can run in parallel (different recognizer files)
**Phase 3 tests**: T056-T081 can all run in parallel (independent test cases)
**Phase 4 tests**: T087-T091 can run in parallel
**Phase 5 tests**: T099-T103 can run in parallel
**Cross-phase**: Phases 4 and 5 can run in parallel with Phase 2/3 (after Phase 1)

### Recommended Execution Order

1. Phase 1 (Data Model) -- foundation, blocks everything
2. Phase 2 (Recognizer Call Detection) + Phase 4 (AST) + Phase 5 (Interface Validation) in parallel
3. Phase 3 (Inference Pipeline) after Phase 2 completes
4. Phase 6 (Polish) after all feature phases

---

## Summary

| Phase | Tests Added | Files Modified | Description |
|-------|-------------|---------------|-------------|
| 1. Data Model | 9 | scanner.py | CallInfo, InterfaceInfo, MethodSetEntry, ScanResult extension |
| 2. Recognizer Call Detection | 24 | go.py, scanner.py, typescript.py, java.py, rust.py, csharp.py, php.py, ruby.py, cpp.py | Per-language call detection |
| 3. Inference Pipeline | 26 | scanner.py | _infer_call_edges, _infer_interface_satisfaction, _resolve_call_participant, pipeline integration |
| 4. AST Scanner | 5 | ast_scanner.py | Wire tree-sitter call queries to CallInfo |
| 5. Interface Validation | 5 | typescript.py, java.py, rust.py, csharp.py, php.py, ruby.py, cpp.py | Verify/fix implements edge cases |
| 6. Polish | 0 | pyproject.toml, CLAUDE.md | Version bump, docs, verification |
| **Total** | **69** | **14 files** (12 source, 2 new test) | |

---

## Notes

- [P] tasks = different files or independent test functions, no dependencies
- [Phase] label maps task to implementation phase for traceability
- TDD enforced per Constitution Principle VI -- tests MUST fail before implementation
- Phase 3 is the highest risk phase (inference pipeline + demand-driven method nodes)
- Commit after each completed phase or logical task group
- Stop at any checkpoint to validate independently
- All 793 existing tests MUST pass at every checkpoint (backward compat is non-negotiable)

# Tasks: Data Integrity

**Input**: `specs/033-data-integrity/spec.md` + `specs/033-data-integrity/plan.md`
**Branch**: `033-data-integrity`
**TDD order**: RED (failing test) → GREEN (implementation) → VERIFY (full suite passes)

All tasks extend **existing test files** — no new test files are created.

---

## Phase 1: No shared infrastructure needed

There are no cross-cutting prerequisites.  Each user story is independent and all five can be
worked in parallel once the branch is created.

**Parallel opportunities**: US1-SQLite, US1-Neo4j, US2, US3, US4, US5 are fully independent.
Within each user story the RED test must precede the GREEN implementation.

---

## Phase 2: User Story 1 — Edge Confidence Survives Persistence (Priority: P1)

**Goal**: `Edge.confidence` round-trips through SQLite and Neo4j with zero data loss.
**Independent test**: Save a graph containing edges at confidence 0.5, 0.7, 0.9 to each backend;
reload; assert all confidence values match exactly.

### US1-A: SQLite Backend

> Write the RED test first — it must FAIL before implementation begins.

- [ ] T001 [P] [US1] Write failing tests for confidence persistence in SQLite backend
  - File: `tests/test_sqlite_storage.py`
  - Add a test class `TestSQLiteConfidencePersistence`
  - Test 1 (`test_confidence_survives_round_trip`): build a `GraphData` with three edges at
    `confidence=0.5`, `0.7`, `0.9`; save then load; assert each loaded edge has the exact
    confidence value.
  - Test 2 (`test_default_confidence_is_1_0`): save a graph with an edge that has `confidence=1.0`;
    reload; assert `confidence == 1.0` (backward compatibility).
  - Test 3 (`test_old_database_without_confidence_column`): manually create a SQLite DB with the
    old schema (no `confidence` column) using `sqlite3` directly; call `storage.load()`; assert
    loaded edges have `confidence == 1.0`.
  - Run `pytest tests/test_sqlite_storage.py -k confidence` — confirm RED.

- [ ] T002 [US1] Implement confidence persistence in `src/codegiraffe/sqlite_storage.py`
  - Depends on T001 (tests must be RED first).
  - In `_ensure_schema()`: add `confidence REAL NOT NULL DEFAULT 1.0` to the `edges` CREATE TABLE
    statement.
  - Add an `ALTER TABLE` migration guard inside `_ensure_schema()`: after `executescript`, check
    `PRAGMA table_info(edges)` for the `confidence` column; if absent, run
    `ALTER TABLE edges ADD COLUMN confidence REAL NOT NULL DEFAULT 1.0`.
  - In `save()` INSERT: add `confidence` to the column list and pass `edge.confidence` as the
    corresponding parameter value (6th positional arg).
  - In `load()` SELECT: add `confidence` to the column list; pass `confidence=row[5]` when
    constructing `Edge(...)`.
  - Run `pytest tests/test_sqlite_storage.py -k confidence` — confirm GREEN.
  - Run `pytest tests/test_sqlite_storage.py` — confirm no regressions in existing suite.

### US1-B: Neo4j Backend

> Write the RED test first — it must FAIL before implementation begins.

- [ ] T003 [P] [US1] Write failing tests for confidence persistence in Neo4j backend
  - File: `tests/test_neo4j_storage.py`
  - Add a test class `TestNeo4jConfidencePersistence`
  - Test 1 (`test_confidence_survives_round_trip`): using the existing mock/fake session pattern in
    the test file, assert that the `edge_params` passed to `tx.run` include `"confidence"` and that
    `load()` returns edges with the correct confidence values.
  - Test 2 (`test_load_missing_confidence_defaults_to_1_0`): simulate a Neo4j record with no
    `confidence` property on the relationship (e.g., `props.get("confidence")` returns `None`);
    assert the loaded `Edge.confidence` is `1.0`.
  - Run `pytest tests/test_neo4j_storage.py -k confidence` — confirm RED.

- [ ] T004 [US1] Implement confidence persistence in `src/codegiraffe/neo4j_storage.py`
  - Depends on T003 (tests must be RED first).
  - In `save()` `edge_params` list comprehension: add `"confidence": edge.confidence` to each dict.
  - In the Cypher `SET` clause: add `r.confidence = edge.confidence` after `r.manual = edge.manual`.
  - In `load()` edge construction: add `confidence=float(props.get("confidence", 1.0))` to the
    `Edge(...)` call.
  - Run `pytest tests/test_neo4j_storage.py -k confidence` — confirm GREEN.
  - Run `pytest tests/test_neo4j_storage.py` — confirm no regressions.

**Checkpoint**: US1 complete when T002 and T004 both pass. All confidence values survive all three
storage backends (JSON already persists confidence via Pydantic model_dump; no JSON change needed).

---

## Phase 3: User Story 2 — Crash-Safe Graph Persistence (Priority: P2)

**Goal**: `JSONStorage.save()` is atomic — a crash mid-write leaves the previous file intact.
**Independent test**: Monkeypatch `os.replace` to raise after the temp file is written; verify the
original file remains valid and loadable.

> Write the RED test first — it must FAIL before implementation begins.

- [ ] T005 [P] [US2] Write failing tests for atomic JSON writes
  - File: `tests/test_storage.py`
  - Add a test class `TestAtomicJSONWrite`
  - Test 1 (`test_original_file_survives_interrupted_save`): save a valid graph to `tmp_path`;
    monkeypatch `codegiraffe.storage.os.replace` to raise `OSError`; call `save()` again with
    different data; assert the original file is still present and `storage.load()` returns the
    original graph (not the new one and not `None`).
  - Test 2 (`test_normal_save_replaces_file_atomically`): save graph A, then save graph B; assert
    `storage.load()` returns graph B (the new data). Verify no `.tmp` files remain in the directory.
  - Test 3 (`test_first_save_leaves_no_corrupt_file_on_failure`): on a fresh `tmp_path` (no
    existing file), monkeypatch `os.replace` to raise; call `save()`; assert the target
    `graph.json` does NOT exist (clean failure, no corrupt partial file).
  - Run `pytest tests/test_storage.py -k atomic` — confirm RED.

- [ ] T006 [US2] Implement atomic writes in `src/codegiraffe/storage.py`
  - Depends on T005 (tests must be RED first).
  - Add `import os` and `import tempfile` at the top of the file.
  - Replace the `path.write_text(...)` call in `JSONStorage.save()` with the write-to-temp-then-
    rename pattern:
    ```python
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
        suffix=".tmp",
    ) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, path)
    ```
  - Wrap the `os.replace` call in a try/except that cleans up the temp file on failure to avoid
    leaving `.tmp` debris: `except: tmp_path.unlink(missing_ok=True); raise`.
  - Run `pytest tests/test_storage.py -k atomic` — confirm GREEN.
  - Run `pytest tests/test_storage.py` — confirm no regressions.

**Checkpoint**: US2 complete when T006 passes. JSON saves are now crash-safe.

---

## Phase 4: User Story 3 — Coverage Annotations Persist (Priority: P3)

**Goal**: `codegiraffe_coverage` MCP tool saves the annotated graph to storage.
**Independent test**: Call the tool via the server integration layer; reload the graph from storage;
assert `_test_coverage` metadata is present on the expected nodes.

> Write the RED test first — it must FAIL before implementation begins.

- [ ] T007 [P] [US3] Write failing test for coverage annotation persistence
  - File: `tests/test_server.py`
  - Add a test `test_coverage_annotations_persist_to_storage`
  - Setup: create a graph with one module node that has a `file_path` matching a coverage entry;
    initialize the server's `_graph` and `_storage` (using `JSONStorage` with `tmp_path`);
    write a minimal coverage.py JSON file to `tmp_path`.
  - Call `codegiraffe_coverage(project_path=..., coverage_path=...)`.
  - Assert the return value contains "Annotated nodes".
  - Reload the graph from `_storage.load(project_path)` directly.
  - Assert the reloaded node's `metadata["_test_coverage"]` equals the expected coverage value.
  - Run `pytest tests/test_server.py -k coverage_persist` — confirm RED.

- [ ] T008 [US3] Add `_storage.save()` call in `src/codegiraffe/server.py` `codegiraffe_coverage`
  - Depends on T007 (tests must be RED first).
  - Inside the `with _graph_lock:` block in `codegiraffe_coverage`, after the call to
    `map_coverage_to_nodes(graph, coverage_data)` and before building the report lines, add:
    ```python
    _storage.save(project_path, graph.to_data())
    ```
  - The save must occur inside the lock to prevent a concurrent rescan from clobbering the state.
  - Run `pytest tests/test_server.py -k coverage_persist` — confirm GREEN.
  - Run `pytest tests/test_server.py` — confirm no regressions.

**Checkpoint**: US3 complete when T008 passes. Coverage annotations survive server restarts.

---

## Phase 5: User Story 4 — Accurate Database Model Detection (Priority: P2)

**Goal**: Each SQLAlchemy model class in a multi-model file gets its own `__tablename__`.
**Independent test**: Scan a Python source string with two model classes having distinct table names;
assert each model node references the correct table name.

> Write the RED test first — it must FAIL before implementation begins.

- [ ] T009 [P] [US4] Write failing test for per-model tablename detection
  - File: `tests/test_scanner.py`
  - Add a test class `TestTableNamePerModelClass`
  - Test 1 (`test_two_models_get_distinct_table_names`): define a Python source string:
    ```python
    SOURCE = """
    class User(Base):
        __tablename__ = 'users'
        id = Column(Integer, primary_key=True)

    class Order(Base):
        __tablename__ = 'orders'
        id = Column(Integer, primary_key=True)
    """
    ```
    Scan via `PythonRecognizer().recognize(Path("models.py"), SOURCE)`.
    Find nodes with `type == "database_table"`.
    Assert exactly two table nodes exist.
    Assert one node has `metadata["table_name"] == "users"` and the other has `"orders"`.
  - Test 2 (`test_first_model_explicit_second_model_default`): source with one explicit `__tablename__`
    and one class with no `__tablename__` (should default to lowercased class name).
    Assert the first gets the explicit name; the second gets the class name lowercased.
  - Run `pytest tests/test_scanner.py -k table_name` — confirm RED (both tests fail because the
    current code gives both models the same table name).

- [ ] T010 [US4] Fix per-class `__tablename__` scoping in `src/codegiraffe/scanner.py`
  - Depends on T009 (tests must be RED first).
  - In `PythonRecognizer.recognize()`, inside the `for match in _SQLALCHEMY_MODEL_RE.finditer(cleaned)` loop:
    - Replace `_TABLENAME_RE.search(cleaned)` with a scoped search:
      ```python
      class_body_start = match.start()
      next_class = _SQLALCHEMY_MODEL_RE.search(cleaned, match.end())
      class_body_end = next_class.start() if next_class else len(cleaned)
      class_slice = cleaned[class_body_start:class_body_end]
      tablename_match = _TABLENAME_RE.search(class_slice)
      ```
  - Run `pytest tests/test_scanner.py -k table_name` — confirm GREEN.
  - Run `pytest tests/test_scanner.py` — confirm no regressions.

**Checkpoint**: US4 complete when T010 passes. Multi-model files produce correct per-model table names.

---

## Phase 6: User Story 5 — No Duplicate Edges from Repeated Scans (Priority: P3)

**Goal**: Scanning an unchanged project twice produces an identical edge count.
**Independent test**: Run the scanner on a fixture project twice; assert edge counts are equal.

> Write the RED test first — it must FAIL before implementation begins.

- [ ] T011 [P] [US5] Write failing test for idempotent edge deduplication
  - File: `tests/test_scanner.py`
  - Add a test class `TestEdgeDeduplicationIdempotency`
  - Test 1 (`test_double_scan_produces_same_edge_count`): create a small multi-file Python project
    in `tmp_path` with at least one endpoint and one SQLAlchemy model class (so cross-file edge
    inference runs); scan once via `scan_project()`; record `edge_count_1 = len(result.edges)`;
    scan again with the same `project_path`; record `edge_count_2 = len(result.edges)`;
    assert `edge_count_1 == edge_count_2`.
  - Test 2 (`test_dedup_key_types_are_consistent`): create `ScanResult` with edges whose `type` is
    a plain string (`"reads"`); build the `existing_edges` set; assert that a key constructed with
    `EdgeType.READS` and a key constructed with `"reads"` both test as `in existing_edges`
    (validates the StrEnum equality assumption is preserved after the fix).
  - Run `pytest tests/test_scanner.py -k dedup` — confirm the idempotency test RED if a real
    duplicate exists, or that the consistency test catches type form divergence.

- [ ] T012 [US5] Normalize EdgeType dedup keys in `src/codegiraffe/scanner.py`
  - Depends on T011 (tests must be RED first).
  - In every function that builds an `existing_edges` set from `result.edges`:
    - Change `{(e.source, e.target, e.type) for e in result.edges}` to
      `{(e.source, e.target, str(e.type)) for e in result.edges}` to make form explicit.
  - Change all dedup key constructions that use bare `EdgeType.X` (without `.value`) to use
    `EdgeType.X.value` (e.g., line 1024: `EdgeType.READS` → `EdgeType.READS.value`).
  - Change the same-file edge storage at line 918 from `type=EdgeType.READS` to
    `type=EdgeType.READS.value` so stored `edge.type` is always a plain string.
  - Affected functions (by approx line number):
    - `_infer_cross_file_edges()` — line 1012–1034
    - `_infer_inheritance_edges()` — line 1057–1104
    - `_infer_import_edges_universal()` — line 1124–1152
    - `_infer_interface_satisfaction()` — line 1166–1193
    - `_infer_contract_edges()` — line 1209+
    - `_infer_go_interface_satisfaction()` — line 1588+
  - Run `pytest tests/test_scanner.py -k dedup` — confirm GREEN.
  - Run `pytest tests/test_scanner.py` — confirm no regressions.

**Checkpoint**: US5 complete when T012 passes. Repeated scans are idempotent.

---

## Phase 7: Final Verification

**Purpose**: Full regression check across all 1600+ tests.

- [ ] T013 Run full test suite
  - `python -m pytest tests/ -v --tb=short`
  - All tests must pass. Zero regressions permitted per SC-006.
  - If any test fails, route back to the relevant user story task.

- [ ] T014 [P] Manual smoke test for each user story
  - US1: Create a graph with `confidence=0.7` edges; save to SQLite; reload; print confidence values.
  - US2: Save a graph; observe the `.tmp` file lifecycle via file-system watcher or `strace`; confirm
    no partial file is left on `Ctrl-C`.
  - US3: Run `codegiraffe_coverage` on a real coverage report; restart the MCP server; call
    `codegiraffe_query` and verify `_test_coverage` metadata is present.
  - US4: Scan a file with two SQLAlchemy models; call `codegiraffe_query(node_type="database_table")`
    and verify distinct table names.
  - US5: Scan the same project twice; compare edge counts in the output.

---

## Dependencies & Execution Order

### Parallel opportunities (all stories are independent)

```
T001 [US1-SQLite RED]  ─────→ T002 [US1-SQLite GREEN]  ─┐
T003 [US1-Neo4j RED]   ─────→ T004 [US1-Neo4j GREEN]   ─┤
T005 [US2 RED]         ─────→ T006 [US2 GREEN]          ─┼─→ T013 [Full suite]
T007 [US3 RED]         ─────→ T008 [US3 GREEN]          ─┤
T009 [US4 RED]         ─────→ T010 [US4 GREEN]          ─┤
T011 [US5 RED]         ─────→ T012 [US5 GREEN]          ─┘
```

Within each story: RED test must fail before GREEN implementation begins.
All six story pairs can start in parallel.
T013 (full suite) runs after all GREEN tasks complete.

### Story independence

- **US1-SQLite** (T001–T002): touches only `sqlite_storage.py` and `test_sqlite_storage.py`
- **US1-Neo4j** (T003–T004): touches only `neo4j_storage.py` and `test_neo4j_storage.py`
- **US2** (T005–T006): touches only `storage.py` and `test_storage.py`
- **US3** (T007–T008): touches only `server.py` and `test_server.py`
- **US4** (T009–T010): touches only `scanner.py` and `test_scanner.py` (different test class from US5)
- **US5** (T011–T012): touches only `scanner.py` and `test_scanner.py` (different test class from US4)

Note: US4 and US5 both modify `scanner.py` — if worked in parallel they must be coordinated to
avoid merge conflicts.  Preferred: work US4 and US5 sequentially, or split into separate commits
within the same branch.

---

## Notes

- [P] marks tasks that can run in parallel with other [P] tasks in the same phase
- TDD is NON-NEGOTIABLE per the project constitution — RED before GREEN, always
- Commit after each GREEN task (or after the RED+GREEN pair for a story)
- Do not modify any file not listed in the story's scope — surgical changes only
- `Edge.confidence` already exists on the Pydantic model (`graph.py` line 35); no model changes needed
- JSON storage already persists `confidence` via `model_dump` — only SQLite and Neo4j need fixing
- The `StrEnum` dedup fix (US5) is a correctness hardening, not a functional regression fix today,
  but it is required to make scanning idempotent when `Edge.type` values from different code paths
  are compared as set keys

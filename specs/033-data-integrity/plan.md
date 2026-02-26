# Implementation Plan: Data Integrity

**Branch**: `033-data-integrity` | **Date**: 2026-02-25 | **Spec**: `specs/033-data-integrity/spec.md`

## Summary

Five targeted bug fixes that ensure data survives storage round-trips, writes are crash-safe, and
the scanner produces idempotent output.  No new abstractions are introduced; every change is a
surgical correction within an existing file.

---

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: NetworkX >= 3.0, Pydantic v2, FastMCP, sqlite3 (stdlib), neo4j >= 6.0 (optional)
**Storage**: JSON files (primary), SQLite (secondary), Neo4j (optional)
**Testing**: pytest >= 8.0, pytest-asyncio >= 0.23 — 1600+ existing tests; all fixes require new RED tests first
**Target Platform**: Linux/macOS/Windows (POSIX atomicity for JSON writes; best-effort on Windows)
**Constraints**: All existing tests must continue to pass; no new mandatory dependencies

---

## Constitution Check

- **I. MCP-Native**: No MCP tool interfaces change. All fixes are internal implementation details.
- **V. Incremental & Non-Destructive**: Backward compatibility required. Edges loaded from older
  storage files without a `confidence` column must default to `1.0`. No schema migration needed
  for users who reload — the schema changes are additive.
- **VI. Test-First (NON-NEGOTIABLE)**: All five fixes must have failing tests written first.
- **VII. Simplicity**: Each fix is the minimal change to close the defect. No redesign.

---

## Project Structure

```text
specs/033-data-integrity/
├── plan.md              # This file
└── spec.md              # Requirements and acceptance criteria

src/codegiraffe/
├── sqlite_storage.py    # US1 — add confidence column to schema + save/load
├── neo4j_storage.py     # US1 — add confidence to edge_params + load
├── storage.py           # US2 — atomic JSON write (tempfile + os.replace)
├── server.py            # US3 — add _storage.save() after map_coverage_to_nodes()
└── scanner.py           # US4 — scope _TABLENAME_RE per class body
                          # US5 — normalize EdgeType dedup keys to .value strings

tests/
├── test_sqlite_storage.py   # US1 tests (extend existing file)
├── test_neo4j_storage.py    # US1 tests (extend existing file)
├── test_storage.py          # US2 tests (extend existing file)
├── test_server.py           # US3 tests (extend existing file)
└── test_scanner.py          # US4 + US5 tests (extend existing file)
```

---

## Concrete Technical Findings

### US1 — Confidence not persisted in SQLite or Neo4j

**Root cause — SQLite** (`sqlite_storage.py`):

- `_ensure_schema()` at line 51 defines the `edges` table with columns:
  `id, source, target, type, metadata, manual` — **no `confidence` column**.
- `save()` at line 179 inserts edges with `INSERT OR IGNORE INTO edges (source, target, type, metadata, manual)` — confidence is dropped.
- `load()` at line 107 constructs `Edge(...)` without passing `confidence` — Pydantic default is `1.0`.

**Fix — SQLite**:
1. Add `confidence REAL NOT NULL DEFAULT 1.0` to the `edges` CREATE TABLE statement.
2. Add `ALTER TABLE edges ADD COLUMN confidence REAL NOT NULL DEFAULT 1.0` guard for existing
   databases (run `ADD COLUMN` inside `_ensure_schema` only if the column is missing; use
   `PRAGMA table_info(edges)` to detect this at startup).
3. Include `confidence` in the INSERT and SELECT statements.

**Root cause — Neo4j** (`neo4j_storage.py`):

- `save()` at line 290 builds `edge_params` as:
  `{"source": ..., "target": ..., "type": ..., "metadata": ..., "manual": ...}` — no `confidence`.
- The Cypher `SET r.type = edge.type, r.metadata = ..., r.manual = ...` at line 306 never writes confidence.
- `load()` at line 218 constructs `Edge(...)` without `confidence` — defaults to `1.0`.

**Fix — Neo4j**:
1. Add `"confidence": edge.confidence` to `edge_params` dict.
2. Add `r.confidence = edge.confidence` to the `SET` clause.
3. Read `props.get("confidence", 1.0)` in `load()` and pass to `Edge(confidence=...)`.

**Backward compatibility**: Both fixes use `DEFAULT 1.0` in SQLite schema and `props.get("confidence", 1.0)` in Neo4j load — older data reads as `1.0` (correct).

---

### US2 — JSON writes are not atomic (`storage.py`)

**Root cause** (`storage.py` line 81–94):

```python
def save(self, project_path: str, data: GraphData) -> None:
    path = self._graph_path(project_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = data.model_dump(mode="json")
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
```

`path.write_text()` opens and truncates the file before writing.  A crash or power loss after
truncation but before the write completes leaves a zero-byte or partial file.

**Fix** — write-to-temp then `os.replace()`:

```python
import os, tempfile

def save(self, project_path: str, data: GraphData) -> None:
    path = self._graph_path(project_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = data.model_dump(mode="json")
    content = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
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

`os.replace()` is atomic on POSIX (rename syscall).  On Windows it is also atomic since Python 3.3+.
Writing to a temp file in the **same directory** as the target ensures the rename is on the same
filesystem, making it a cheap metadata operation.

**Test approach**: Write a valid graph, then monkeypatch `os.replace` to raise mid-save.  Verify the
original file is still loadable.  Also verify a normal save round-trips correctly.

---

### US3 — Coverage annotations are not persisted (`server.py`)

**Root cause** (`server.py` `codegiraffe_coverage` tool, around line 1471–1491):

```python
with _graph_lock:
    ...
    map_coverage_to_nodes(graph, coverage_data)   # mutates in-memory nodes
    # <-- no _storage.save() call here
```

`map_coverage_to_nodes()` writes `node.metadata["_test_coverage"] = pct` in place, but the
`_storage.save()` call that would flush the updated `GraphData` back to disk is absent.

**Fix** — add `_storage.save(project_path, graph.to_data())` inside the `with _graph_lock` block,
after `map_coverage_to_nodes()` completes and before building the report string.

**Note**: `_storage` and `_graph` are module-level globals in `server.py`.  The save must occur
while the lock is held to prevent a concurrent rescan from clobbering the freshly-annotated graph.

---

### US4 — Table name detection bug in scanner (`scanner.py`)

**Root cause** (`scanner.py` line 819–823):

```python
for match in _SQLALCHEMY_MODEL_RE.finditer(cleaned):
    class_name = match.group(1)
    # Bug: searches the entire file, not just this class's body
    tablename_match = _TABLENAME_RE.search(cleaned)
    table_name = tablename_match.group(1) if tablename_match else class_name.lower()
```

`_TABLENAME_RE.search(cleaned)` always finds the **first** `__tablename__` in the file.
When there are two model classes, both get the first class's table name.

**Fix** — scope the search to the text **starting at** `match.start()` (the current class header)
and ending before the next class definition.  The simplest correct approach:

```python
for match in _SQLALCHEMY_MODEL_RE.finditer(cleaned):
    class_name = match.group(1)
    # Scope to the slice of content from this class header onward
    class_body_start = match.start()
    next_class_match = _SQLALCHEMY_MODEL_RE.search(cleaned, match.end())
    class_body_end = next_class_match.start() if next_class_match else len(cleaned)
    class_slice = cleaned[class_body_start:class_body_end]
    tablename_match = _TABLENAME_RE.search(class_slice)
    table_name = tablename_match.group(1) if tablename_match else class_name.lower()
```

**Test fixture**: a Python file string containing two SQLAlchemy model classes with distinct
`__tablename__` values.  Scan the file and assert each model node has its own table name.

---

### US5 — Edge dedup key type mismatch (`scanner.py`)

**Root cause** — two distinct inconsistencies in how `existing_edges` sets are built and queried:

**Inconsistency A** (line 1012 vs 1024):
```python
# Set built with e.type — a plain string from Edge.type
existing_edges = {(e.source, e.target, e.type) for e in result.edges}

# Lookup key uses EdgeType enum object (not .value)
edge_key = (ep_id, table_id, EdgeType.READS)           # line 1024
```
Because `EdgeType` is a `StrEnum`, `EdgeType.READS == "reads"` is `True` and Python set lookup
works correctly **today**.  However, the inconsistency is a latent risk: if `EdgeType` is ever
changed to a non-StrEnum (e.g., a regular `Enum`), or if an edge is stored with `.value` while
the key uses the enum object, the dedup silently fails.

**Inconsistency B** (lines 1079, 1139, 1176 etc.) — some dedup sets are built with `e.type` (string)
but keys use `EdgeType.IMPLEMENTS.value`, while others (line 918) store edges with `type=EdgeType.READS`
(enum, not `.value`) and build dedup keys with `EdgeType.READS` (also enum).

The actual production bug is in the **cross-file endpoint→table inference** at line 1024:
- `existing_edges` at line 1012 is built from `e.type` for edges created in the same-file pass
  where `type=EdgeType.READS` (StrEnum, equals `"reads"`).
- The lookup at line 1024 uses `EdgeType.READS` (StrEnum).
- Both resolve to `"reads"`, so the dedup **does work** for same-file edges.
- But newly created edges at line 1030 use `type=EdgeType.READS` and are added to `existing_edges`
  as `(ep_id, table_id, EdgeType.READS)` — which equals `(ep_id, table_id, "reads")` due to StrEnum.
- The real duplicate accumulation risk is when `type` values stored in `Edge.type` from different
  code paths differ in form (one path stores `EdgeType.READS`, another stores `"reads"`).

**Fix** — normalize all dedup key construction and edge storage to use `.value` strings consistently:
- Build `existing_edges` sets using `e.type` as-is (already a string from Pydantic).
- Use `EdgeType.READS.value` (or just `"reads"`) in all dedup keys.
- Store edges with `type=EdgeType.READS.value` (or use the StrEnum directly — both are fine since
  Pydantic stores them as strings).

The most surgical fix is to normalize the `existing_edges` building to always use `str(e.type)` and
all lookup keys to use `EdgeType.X.value`, making the intent explicit and immune to enum changes.

**Idempotency test**: scan a fixture project twice, assert `len(edges)` is identical both runs.

---

## Complexity Tracking

No constitution violations.  All five fixes are surgical, single-file or two-file changes with no
new abstractions, new dependencies, or cross-system contract changes.

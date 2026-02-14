# Implementation Plan: Scanner Intelligence Improvements (v0.4.0)

**Branch**: `005-scanner-intelligence` | **Date**: 2026-02-13 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/005-scanner-intelligence/spec.md`

## Summary

Dogfooding Code Giraffe on itself revealed critical scanner quality issues: 65% false-positive nodes (test classes) and zero real architectural edges. This plan addresses four improvements: test file exclusion, import-based dependency detection, class inheritance/protocol detection, and module-level nodes. All changes target the Python scanner (regex + AST modes) while maintaining backward compatibility with existing graphs and all 426 tests.

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: FastMCP (mcp[cli] >= 1.2.0), NetworkX >= 3.0, Pydantic v2
**Storage**: JSON + SQLite + Neo4j (existing, unchanged)
**Testing**: pytest >= 8.0, pytest-asyncio >= 0.23
**Target Platform**: Any OS with Python 3.11+ and MCP clients
**Project Type**: Single Python package (src-layout)
**Performance Goals**: 1000-file project scans in <30 seconds
**Constraints**: Backward compatible with pre-v0.4.0 graphs, all 426 existing tests must pass
**Scale/Scope**: Typical Python projects (10–1000 source files)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. MCP-Native | PASS | No new tools needed; improvements surface through existing `init`/`sync`/`query` tools with new optional parameters |
| II. Graph-First | PASS | New node type (`module`) and edge types (`imports`, `implements`, `contains`) extend the typed graph |
| III. Beyond-AST | PASS with justification | Import/inheritance detection IS AST-level analysis, but the constitution's exception clause applies: "Code Giraffe SHOULD NOT duplicate [IDE-derivable relationships] *unless doing so adds architectural context*." These edges connect to beyond-AST nodes (env vars, external APIs, queues) to form a complete graph that no IDE provides |
| IV. Context Efficiency | PASS | Test exclusion REDUCES noise (108→<20 nodes). Module nodes add structure but scoped queries still work |
| V. Incremental & Non-Destructive | PASS | New types are additive. Existing graphs load without migration (FR-015) |
| VI. Test-First | PASS | TDD mandatory, 60+ new tests target (SC-006) |
| VII. Simplicity | PASS | 3 new edge types + 1 node type = minimal schema extension. String filtering adds ~50 lines. No new dependencies |

## Project Structure

### Documentation (this feature)

```text
specs/005-scanner-intelligence/
├── spec.md              # Feature specification
├── plan.md              # This file
├── research.md          # Phase 0: research findings
├── data-model.md        # Phase 1: new node/edge types
├── quickstart.md        # Phase 1: usage guide
├── checklists/
│   └── requirements.md  # Spec quality validation
└── tasks.md             # Phase 2: implementation tasks (next step)
```

### Source Code (files to modify/create)

```text
src/codegiraffe/
├── schema.py            # MODIFY: Add MODULE node type, IMPORTS/IMPLEMENTS/CONTAINS edge types
├── scanner.py           # MODIFY: Test exclusion, string filtering, import detection, inheritance detection, module nodes
├── ast_scanner.py       # MODIFY: Import detection, inheritance detection, module nodes (AST mode)
├── server.py            # MODIFY: Add include_tests parameter to init/sync tools
├── graph.py             # NO CHANGE (Pydantic models already flexible)
├── query.py             # NO CHANGE (queries work with any node/edge types)
├── storage.py           # NO CHANGE (serializes whatever GraphData contains)
└── dashboard.py         # MODIFY: Add module type color/shape to dashboard palette

tests/
├── test_scanner.py      # MODIFY: Add tests for test exclusion, string filtering, imports, inheritance, modules
├── test_ast_scanner.py  # MODIFY: Add tests for AST-mode imports, inheritance, modules
└── test_schema.py       # NEW: Test new enum values
```

**Structure Decision**: Existing src-layout maintained. No new files except `tests/test_schema.py`. All changes are modifications to existing modules.

## Architecture: Implementation Phases

### Phase A: Schema Extension (FR-012, FR-013)

Add to `schema.py`:
- `NodeType.MODULE = "module"`
- `EdgeType.IMPORTS = "imports"`
- `EdgeType.IMPLEMENTS = "implements"`
- `EdgeType.CONTAINS = "contains"`

**Impact**: Purely additive. Existing enum values unchanged. All existing code continues to work.

### Phase B: Test File Exclusion (FR-001, FR-002)

Modify `scanner.py`:

1. **Extend `_should_skip()`** — Add test directory patterns to `_IGNORE_DIRS`: `"tests"`, `"test"`
2. **Add `_is_test_file()`** — New predicate matching `test_*.py`, `*_test.py`, `conftest.py`
3. **Add `include_tests` parameter** to `scan_project()` — When False (default), skip test files via `_should_skip()` + `_is_test_file()`. When True, scan them but add `source: test` to node metadata.
4. **Wire through MCP tools** — Add `include_tests` param to `codegiraffe_init` and `codegiraffe_sync` in `server.py`

### Phase C: String/Comment Filtering (FR-003)

Modify `scanner.py`:

1. **Add `_strip_strings_and_comments()`** — Regex-based preprocessing that removes:
   - Triple-quoted strings (`"""..."""`, `'''...'''`)
   - Single-line comments (`# ...`)
   - Quoted strings (`"..."`, `'...'`) with escape handling
2. **Apply in `PythonRecognizer.recognize()`** — Call on content before pattern matching
3. **AST mode exempt** — Tree-sitter inherently avoids string matches (verified in research)

### Phase D: Import Detection (FR-004–FR-007)

Modify `scanner.py` (regex mode) and `ast_scanner.py` (AST mode):

1. **New regex patterns** in `scanner.py`:
   - `_IMPORT_RE`: Matches `import X` and `from X import Y`
   - `_RELATIVE_IMPORT_RE`: Matches `from . import X`, `from ..X import Y`
2. **Import resolution logic**:
   - Build set of project-internal module paths from scanned files
   - Filter out stdlib (`sys.stdlib_module_names`) and third-party imports
   - Resolve relative imports using file path + package structure
3. **Edge creation**:
   - One `imports` edge per unique (source_module, target_module) pair
   - Metadata: `{symbols: [...], style: "absolute"|"relative"}`
   - Deduplication: combine symbols when multiple imports from same module
4. **AST mode**: Add tree-sitter query for `import_statement` and `import_from_statement` nodes

### Phase E: Inheritance Detection (FR-008, FR-009)

Modify `scanner.py` and `ast_scanner.py`:

1. **Enhance `_CLASS_DEF_RE`** — Change to `^class\s+(\w+)(?:\(([^)]*?)\))?\s*:` to capture base classes in Group 2
2. **Build class registry** — During scan, map class names to node IDs across all files
3. **Cross-file resolution** — After all files scanned, resolve base class names against the registry
4. **Edge creation** — Create `implements` edge from subclass to each base class found in registry
5. **AST mode**: Add tree-sitter query for class definitions with `superclasses` field

### Phase F: Module Nodes (FR-010, FR-011)

Modify `scanner.py` and `ast_scanner.py`:

1. **Module path derivation** — Convert file path to dotted module path:
   - `/home/user/project/src/codegiraffe/graph.py` → `mod:codegiraffe.graph`
   - Detect src-layout (`src/` prefix) and flat-layout
   - `__init__.py` → package node (e.g., `mod:codegiraffe`)
2. **Module node creation** — Create `module` type node for each scanned file
3. **Contains edges** — After recognizing entities in a file, create `contains` edges from the file's module node to each entity node
4. **Import edges target modules** — Import edges connect module nodes (from Phase D)

### Phase G: Dashboard Update

Modify `dashboard.py`:

1. **Add `module` to TYPE_COLORS** — New color (e.g., amber/orange) for module nodes
2. **Add `module` to TYPE_SHAPES** — e.g., `round-rectangle` to distinguish from services

## Complexity Tracking

> No constitution violations requiring justification. All changes are minimal, additive, and within existing patterns.

# Research: Scanner Intelligence Improvements (v0.4.0)

**Date**: 2026-02-13
**Branch**: `005-scanner-intelligence`

## R1: Python Standard Library Detection

**Decision**: Use `sys.stdlib_module_names` (frozenset, O(1) lookup)
**Rationale**: Available in Python 3.10+, covers all stdlib modules (~297), zero dependencies, constant-time checks.
**Alternatives considered**:
- `importlib.util.find_spec()` — more robust but slower, requires exception handling, can trigger side effects
- Hardcoded module list — fragile, version-dependent, maintenance burden

## R2: Go Recognizer Import Detection (Reference Implementation)

**Decision**: Mirror the Go recognizer's import pattern for Python
**Rationale**: Go recognizer (recognizers/go.py) already implements the exact pattern we need:
- `_GO_INTERNAL_IMPORT_RE` regex finds internal imports
- Creates `depends_on` edges with `{inferred: True}` metadata
- Uses `seen_imports` set for deduplication
- Creates target package nodes on-demand if not already discovered
- Filters self-imports

**Python adaptation**: Replace Go's `"pkg/internal/(\w+)"` with Python's `from X import Y` / `import X` regex. Create `imports` edges (new type) instead of reusing `depends_on`.

## R3: Class Definition Regex Enhancement

**Decision**: Enhance `_CLASS_DEF_RE` to capture base classes in a second group
**Rationale**: Current regex `^class\s+(\w+)\s*(?:\(.*?\))?\s*:` uses non-capturing group for bases. Changing to `^class\s+(\w+)(?:\(([^)]*?)\))?\s*:` adds Group 2 for base classes.
**Impact**: Minimal — only changes group structure, all existing matches still work.

## R4: Test File Exclusion Strategy

**Decision**: Extend `_should_skip()` in scanner.py with test directory and file name patterns
**Rationale**: Current `_IGNORE_DIRS` frozenset skips 13 directory patterns but has zero test-related entries.
**Implementation**:
- Add `"tests"`, `"test"` to `_IGNORE_DIRS` for directory-level exclusion
- Add file name checks: `test_*.py`, `*_test.py`, `conftest.py`
- New `include_tests` parameter on `scan_project()` bypasses exclusion when True
- When `include_tests=True`, tag resulting nodes with `source: test` metadata

## R5: String/Comment Filtering (FR-003)

**Decision**: Use regex-based string stripping (Approach A) for regex scanner mode; AST mode already handles this natively
**Rationale**:
- All 7 PythonRecognizer patterns are vulnerable to false positives in strings/comments
- Regex preprocessing: `_strip_strings_and_comments()` removes triple-quoted strings, comments, and quoted strings before pattern matching
- ~0.5% performance overhead, zero dependencies
- AST scanner (tree-sitter) automatically avoids string matches — no changes needed

**Alternatives rejected**:
- `tokenize` module (Approach B) — Python-specific, 10x slower, can't be reused for other languages
- Line-level heuristic (Approach C) — insufficient accuracy, misses inline strings

## R6: Import Resolution for Relative Imports

**Decision**: Resolve relative imports using file path + package structure
**Rationale**: Given `from . import graph` in `src/codegiraffe/scanner.py`:
1. Determine current package from file path: `codegiraffe`
2. Resolve `.` to `codegiraffe`
3. Target module: `codegiraffe.graph` → `mod:codegiraffe.graph`

For `from ..utils import helper` in `src/codegiraffe/recognizers/go.py`:
1. Current package: `codegiraffe.recognizers`
2. Resolve `..` to `codegiraffe`
3. Target: `codegiraffe.utils` → `mod:codegiraffe.utils`

**Key logic**: Count leading dots, remove that many trailing package components from current module path, append the imported module name.

## R7: Cross-File Class Resolution

**Decision**: Two-pass approach — first pass collects all class definitions, second pass resolves inheritance
**Rationale**: When `class Foo(Bar)` is found in file A but `class Bar` is in file B, we need a global class name → node ID map built during scanning. After all files are processed, resolve base class references against this map to create `implements` edges.
**Implementation**: Extend `_infer_cross_file_edges()` (scanner.py lines 164-192) to also handle inheritance resolution alongside the existing endpoint→table cross-file inference.

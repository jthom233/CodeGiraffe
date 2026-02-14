# Implementation Plan: Code Giraffe v0.10.0 -- Change Impact Validation

## Overview

This plan adds pre-commit change validation, test suggestion, and file coupling
analysis to CodeGiraffe. Two new utility modules (`diff_parser.py`,
`git_utils.py`) provide shared infrastructure for parsing unified diffs and
executing git commands. Three new MCP tools and one enhancement to
`codegiraffe_context_for` give AI agents active change awareness before code is
committed.

**Scope:** 7 phases, 5 source files modified, 2 new source modules, 8 new test
files, 3 new MCP tools + 1 enhanced tool (~28 total), 100+ new tests (890+
total).

**Dependency Note:** The spec lists v0.9.0 (Scanner Depth / call-graph edges) as
a soft dependency. This plan is designed to work without v0.9.0 -- blast radius
and impact analysis will use whatever edges exist in the graph (imports,
implements, contains, produces, consumes_contract, etc.). If v0.9.0 is
implemented first, the impact reports will be richer, but all logic is correct
either way.

---

## Architecture Overview

```
                     +-----------------+
                     |   server.py     |  MCP tool entry points
                     | (3 new tools +  |  codegiraffe_validate_changes
                     |  1 enhanced)    |  codegiraffe_suggest_tests
                     +-------+---------+  codegiraffe_file_coupling
                             |            codegiraffe_context_for (enhanced)
                             v
                     +-----------------+
                     |   query.py      |  Analysis logic
                     | map_files_to_   |  validate_changes()
                     |   nodes()       |  suggest_tests()
                     | validate_       |  file_coupling()
                     |   changes()     |
                     +---+----+--------+
                         |    |
              +----------+    +----------+
              v                          v
    +-----------------+        +-----------------+
    | diff_parser.py  |        | git_utils.py    |
    | (NEW module)    |        | (NEW module)    |
    | parse_diff()    |        | get_uncommitted |
    | DiffFile        |        |   _diff()       |
    | DiffHunk        |        | get_commit_file |
    |                 |        |   _history()    |
    +-----------------+        | is_git_repo()   |
                               +-----------------+
```

**Key architectural decisions:**
- `diff_parser.py` is a pure, stateless module with no dependencies on the graph
  or git. It accepts a raw diff string and returns structured data. This makes it
  independently testable and reusable.
- `git_utils.py` is a thin wrapper around `subprocess.run()` for git commands.
  It follows the pattern established by `_detect_git_renames()` in `query.py`
  (line 96) but lives in its own module to avoid growing `query.py` further.
- All analysis logic (validation, test suggestion, coupling) lives in `query.py`,
  consistent with existing functions like `compute_blast_radius()`,
  `detect_drift()`, and `get_contracts()`.
- MCP tool wrappers in `server.py` are thin: load graph, call query function,
  return markdown. Same pattern as `codegiraffe_blast_radius` (line 408).

---

## Phase 1: Data Models (Serial -- Must Go First)

### Rationale
All subsequent phases reference the new Pydantic models. Define them first so
everything else has stable types to import.

### Files to Create

#### `src/codegiraffe/diff_parser.py`

Create a new module with Pydantic v2 models for representing parsed diffs.

**Models:**

```python
"""Unified diff parser for Code Giraffe change impact analysis.

Parses the output of `git diff` into structured data. Pure Python
implementation using regex -- no external diff parsing libraries.
"""

from __future__ import annotations

import re
from pydantic import BaseModel, Field


class DiffHunk(BaseModel):
    """A single hunk within a diff file."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    header: str = ""  # The @@ context text (often contains function/class name)


class DiffFile(BaseModel):
    """A single file entry within a unified diff."""

    path: str  # File path relative to repository root
    old_path: str | None = None  # For renames: the old file path
    status: str  # "added", "modified", "deleted", "renamed"
    hunks: list[DiffHunk] = Field(default_factory=list)
    is_binary: bool = False
    additions: int = 0  # Count of added lines
    deletions: int = 0  # Count of deleted lines
```

**Pattern to follow:** Pydantic v2 `BaseModel` with `Field(default_factory=...)`
for mutable defaults -- same pattern as `Node` and `Edge` in `graph.py`
(lines 15-33).

Also define the output models for the analysis tools:

```python
class TestSuggestion(BaseModel):
    """A suggested test file with relevance scoring."""

    file_path: str
    score: float  # 0.0 to 1.0
    reason: str  # Why this test is relevant
    strategy: str  # "graph", "naming", "blast_radius"


class CouplingPair(BaseModel):
    """A pair of files with co-change coupling data."""

    file_a: str
    file_b: str
    co_change_count: int
    change_count_a: int
    change_count_b: int
    coupling: float  # co_change_count / max(change_count_a, change_count_b)
    in_graph: bool  # Whether an edge exists between these files in the graph
    edge_type: str | None = None  # The graph edge type if in_graph is True


class ChangeReport(BaseModel):
    """Structured output of change impact validation."""

    changed_files: list[DiffFile]
    changed_nodes: list[str]  # Node IDs mapped from changed files
    covered_nodes: list[str]  # Blast-radius nodes that ARE in the diff
    uncovered_nodes: list[dict]  # Blast-radius nodes NOT in the diff (with reasons)
    contract_violations: list[dict]  # Producers changed without consumers
    recommendations: list[str]  # Actionable suggestions
    total_blast_radius: int
```

### Tests

#### `tests/test_diff_parser.py` (new file -- model tests only in Phase 1)

```python
"""Tests for diff parser data models."""

from codegiraffe.diff_parser import (
    ChangeReport,
    CouplingPair,
    DiffFile,
    DiffHunk,
    TestSuggestion,
)
```

**Tests:**
- `test_diff_hunk_defaults` -- Create `DiffHunk` with required fields only, verify defaults.
- `test_diff_file_defaults` -- Create `DiffFile`, verify `hunks=[]`, `is_binary=False`, etc.
- `test_diff_file_rename_has_old_path` -- Create with `status="renamed"` and `old_path`.
- `test_change_report_structure` -- Create `ChangeReport` with all fields populated.
- `test_test_suggestion_model` -- Create `TestSuggestion`, verify score range.
- `test_coupling_pair_model` -- Create `CouplingPair`, verify coupling computation.

**Test count:** +6 tests

---

## Phase 2: Diff Parser (Depends on Phase 1)

### Rationale
The diff parser is the foundation for Features 1, 2, and 4. It has zero
dependencies on the graph or git and can be thoroughly tested with raw diff
strings. Building it first enables parallel development of all three features.

### Files to Modify

#### `src/codegiraffe/diff_parser.py` (add parsing function)

##### New function: `parse_diff`

**Insert after:** the model definitions

**Signature:**
```python
def parse_diff(raw_diff: str) -> list[DiffFile]:
    """Parse a unified diff string into structured DiffFile objects.

    Handles:
    - Standard unified diff format (git diff output)
    - New files (--- /dev/null)
    - Deleted files (+++ /dev/null)
    - Renamed files (rename from/rename to or --- a/old +++ b/new)
    - Binary files (Binary files ... differ)
    - Multiple files in a single diff

    Parameters
    ----------
    raw_diff:
        Raw unified diff string, typically from `git diff` output.

    Returns
    -------
    list[DiffFile]
        One DiffFile per changed file, in the order they appear in the diff.
    """
```

**Algorithm:**
1. Split the raw diff on `^diff --git` lines (each starts a new file entry).
2. For each file section:
   a. Extract file paths from `--- a/path` and `+++ b/path` lines.
   b. Determine status:
      - `--- /dev/null` -> "added"
      - `+++ /dev/null` -> "deleted"
      - `rename from` / `rename to` headers -> "renamed"
      - Otherwise -> "modified"
   c. Check for `Binary files` line -> set `is_binary=True`, skip hunks.
   d. Parse `@@ -old_start,old_count +new_start,new_count @@ header` lines.
   e. Count `+` lines (additions) and `-` lines (deletions) within hunks.
3. Return list of `DiffFile` objects.

**Regex patterns:**
```python
_DIFF_HEADER_RE = re.compile(r"^diff --git a/(.*?) b/(.*?)$", re.MULTILINE)
_FILE_OLD_RE = re.compile(r"^--- (?:a/)?(.*?)$", re.MULTILINE)
_FILE_NEW_RE = re.compile(r"^\+\+\+ (?:b/)?(.*?)$", re.MULTILINE)
_HUNK_RE = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@\s*(.*?)$", re.MULTILINE
)
_RENAME_FROM_RE = re.compile(r"^rename from (.+)$", re.MULTILINE)
_RENAME_TO_RE = re.compile(r"^rename to (.+)$", re.MULTILINE)
_BINARY_RE = re.compile(r"^Binary files", re.MULTILINE)
```

**Pattern to follow:** Pure regex parsing with no external dependencies. Similar
approach to the recognizer regex patterns in `scanner.py` (e.g.,
`_ROUTE_DECORATOR_RE` at line 23).

##### New function: `extract_symbol_hints`

**Insert after:** `parse_diff`

**Signature:**
```python
def extract_symbol_hints(hunks: list[DiffHunk]) -> list[str]:
    """Extract likely function/class names from hunk headers.

    Git diff hunk headers (the text after `@@`) typically contain the
    enclosing function or class name. This provides approximate symbol-level
    change information without full AST parsing.

    Returns a deduplicated list of symbol name strings.
    """
```

**Algorithm:**
1. For each hunk, parse `header` text.
2. Apply language-agnostic patterns:
   - Python: `def function_name(`, `class ClassName(`
   - Generic: identifier at start of line (likely function/method)
3. Return unique names.

### Tests

#### `tests/test_diff_parser.py` (extend from Phase 1)

**Test class: `TestParseDiff`**
- `test_parse_single_modified_file` -- Standard diff with one modified file, verify path and status.
- `test_parse_multiple_files` -- Diff with 3 files, verify all 3 returned in order.
- `test_parse_new_file` -- `--- /dev/null` indicates added file.
- `test_parse_deleted_file` -- `+++ /dev/null` indicates deleted file.
- `test_parse_renamed_file` -- `rename from` / `rename to` headers.
- `test_parse_binary_file` -- Binary file diff, `is_binary=True`, no hunks.
- `test_parse_hunks` -- Verify hunk start/count parsed from `@@` markers.
- `test_parse_hunk_header_context` -- Verify function name extracted from `@@ ... @@ def foo()`.
- `test_parse_addition_deletion_counts` -- Count `+` and `-` lines within hunks.
- `test_parse_empty_diff` -- Empty string returns empty list.
- `test_parse_diff_with_no_newline_marker` -- Handle `\ No newline at end of file`.
- `test_parse_path_with_spaces` -- File paths containing spaces.

**Test class: `TestExtractSymbolHints`**
- `test_extract_python_function` -- Hunk header `def my_function(` -> `"my_function"`.
- `test_extract_python_class` -- Hunk header `class MyClass(` -> `"MyClass"`.
- `test_extract_empty_header` -- Empty header returns no hints.
- `test_extract_deduplication` -- Same function in multiple hunks, only one entry.

**Test count:** +16 tests

---

## Phase 3: Git Utilities (Parallel with Phase 2)

### Rationale
Git command execution is needed by Features 1, 2, 3, and 4. Isolating it in its
own module keeps `query.py` focused on graph analysis and makes git interactions
independently testable and mockable.

### Files to Create

#### `src/codegiraffe/git_utils.py`

```python
"""Git command helpers for Code Giraffe change impact analysis.

Thin wrappers around subprocess calls to the git CLI. All functions
accept a project_path parameter and run git commands in that directory.

Follows the pattern established by _detect_git_renames() in query.py.
"""

from __future__ import annotations

import subprocess


class GitError(Exception):
    """Raised when a git command fails or git is not available."""
    pass


class NotAGitRepoError(GitError):
    """Raised when the project_path is not a git repository."""
    pass
```

##### Function: `is_git_repo`

```python
def is_git_repo(project_path: str) -> bool:
    """Check whether project_path is inside a git repository.

    Returns True if `git rev-parse --git-dir` succeeds.
    """
```

**Implementation:** Run `git -C {project_path} rev-parse --git-dir` with
`capture_output=True`. Return `True` if returncode == 0.

##### Function: `get_uncommitted_diff`

```python
def get_uncommitted_diff(project_path: str) -> str:
    """Return the unified diff of all uncommitted changes (staged + unstaged).

    Runs `git diff HEAD` in the project directory. Returns the raw diff
    string. Returns empty string if there are no uncommitted changes.

    Raises
    ------
    NotAGitRepoError
        If project_path is not a git repository.
    GitError
        If the git command fails for other reasons.
    """
```

**Implementation:**
1. Call `is_git_repo()` first -- raise `NotAGitRepoError` if false.
2. Run `git -C {project_path} diff HEAD`.
3. Handle the special case where there are no commits yet: fall back to
   `git -C {project_path} diff --cached` (initial commit scenario).
4. Return `result.stdout`.

**Pattern to follow:** `_detect_git_renames()` in `query.py` (line 96) -- uses
`subprocess.run()` with `capture_output=True, text=True, timeout=10`.

##### Function: `get_changed_files`

```python
def get_changed_files(project_path: str) -> list[str]:
    """Return list of file paths with uncommitted changes.

    Runs `git diff HEAD --name-only`. Lighter weight than get_uncommitted_diff
    when only file paths are needed (used by codegiraffe_context_for enhancement).

    Returns empty list if no changes or not a git repo (does not raise).
    """
```

##### Function: `get_commit_file_history`

```python
def get_commit_file_history(
    project_path: str, depth: int = 100
) -> list[list[str]]:
    """Mine git log to get the list of changed files per commit.

    Runs `git log --name-only --pretty=format:"COMMIT:%H" -n {depth}`.

    Parameters
    ----------
    project_path:
        Path to the git repository.
    depth:
        Number of recent commits to analyze.

    Returns
    -------
    list[list[str]]
        Each inner list contains the file paths changed in one commit.
        Commits with no file changes are omitted. Ordered most-recent-first.

    Raises
    ------
    NotAGitRepoError
        If project_path is not a git repository.
    """
```

**Algorithm:**
1. Run `git -C {project_path} log --name-only --pretty=format:"COMMIT:%H" -n {depth}`.
2. Split output on `COMMIT:` markers.
3. For each commit section, extract non-empty file path lines.
4. Return list of file lists.

**subprocess pattern:**
All functions use:
```python
subprocess.run(
    cmd,
    capture_output=True,
    text=True,
    cwd=project_path,
    timeout=30,
)
```

Timeout is 30s for git log (which can be slow on large repos), 10s for simpler
commands. The `cwd=project_path` pattern is preferred over `git -C` for
consistency, but either works.

### Tests

#### `tests/test_git_utils.py` (new file)

**Test class: `TestIsGitRepo`**
- `test_is_git_repo_true` -- Use `tmp_path`, run `git init`, verify returns True.
- `test_is_git_repo_false` -- Use bare `tmp_path`, verify returns False.

**Test class: `TestGetUncommittedDiff`**
- `test_get_uncommitted_diff_with_changes` -- Init repo, create file, add, commit,
  modify file, verify diff output contains the modification.
- `test_get_uncommitted_diff_no_changes` -- Clean repo, returns empty string.
- `test_get_uncommitted_diff_not_git_repo` -- Raises `NotAGitRepoError`.
- `test_get_uncommitted_diff_staged_changes` -- Stage a file without committing,
  verify diff captures it.
- `test_get_uncommitted_diff_new_repo_no_commits` -- New repo with staged files
  but no commits yet, verify graceful handling.

**Test class: `TestGetChangedFiles`**
- `test_get_changed_files_returns_paths` -- Modified files listed.
- `test_get_changed_files_empty_when_clean` -- No changes, empty list.
- `test_get_changed_files_not_git_repo` -- Returns empty list (no exception).

**Test class: `TestGetCommitFileHistory`**
- `test_get_commit_file_history` -- Create 3 commits each touching different files,
  verify 3 inner lists with correct file paths.
- `test_get_commit_file_history_depth_limit` -- Create 5 commits, request depth=2,
  verify only 2 returned.
- `test_get_commit_file_history_not_git_repo` -- Raises `NotAGitRepoError`.
- `test_get_commit_file_history_empty_repo` -- No commits, returns empty list.

**Test count:** +13 tests

---

## Phase 4: Query Engine -- Core Analysis Functions (Depends on Phases 2, 3)

### Rationale
This is the largest phase. It adds the core analysis logic to `query.py`:
file-to-node mapping, change validation, test suggestion, and file coupling.
These functions are called by the MCP tools in Phase 5.

### Files to Modify

#### `src/codegiraffe/query.py`

##### 1. New import block

**Location:** After existing imports (line 18)

**Add:**
```python
from codegiraffe.diff_parser import (
    ChangeReport,
    CouplingPair,
    DiffFile,
    TestSuggestion,
    extract_symbol_hints,
    parse_diff,
)
from codegiraffe.git_utils import (
    GitError,
    NotAGitRepoError,
    get_changed_files,
    get_commit_file_history,
    get_uncommitted_diff,
    is_git_repo,
)
```

##### 2. New function: `map_files_to_nodes`

**Insert after:** `_score_node` (line 223)

**Signature:**
```python
def map_files_to_nodes(
    graph: ArchGraph, file_paths: list[str]
) -> dict[str, list[str]]:
    """Map file paths to graph node IDs.

    For each file path, finds all graph nodes associated with that file:
    - Nodes whose `file_path` metadata matches (suffix matching for
      absolute vs. relative path differences)
    - Module nodes whose ID contains the file path (e.g., `module:src/foo.py`)

    Parameters
    ----------
    graph:
        The architecture graph.
    file_paths:
        List of file paths relative to the repository root.

    Returns
    -------
    dict[str, list[str]]
        Mapping of file path -> list of matching node IDs.
        Files with no matching nodes are included with an empty list.
    """
```

**Algorithm:**
1. Build an index: iterate all graph nodes, collect `node.file_path` and `node.id`
   values into a lookup dict keyed by normalized path suffixes.
2. For each input file path:
   a. Direct match: check if any node's `file_path` matches (using suffix matching
      to handle `src/foo.py` vs `/abs/path/src/foo.py`).
   b. Module ID match: check if any node's `id` contains the file path
      (e.g., `module:src/foo/handler.py`).
   c. Collect all matching node IDs.
3. Return the mapping.

**Pattern to follow:** Similar to the node iteration in `detect_drift()` (line
1002) -- iterates `graph.graph.nodes` and checks `node.file_path`.

##### 3. New function: `validate_changes`

**Insert after:** `map_files_to_nodes`

**Signature:**
```python
def validate_changes(
    graph: ArchGraph,
    diff_files: list[DiffFile],
) -> ChangeReport:
    """Validate a set of file changes against the architecture graph.

    Computes the combined blast radius of all changed nodes, then
    cross-references with the actual changes to identify:
    - Covered impact (blast radius nodes also modified in the diff)
    - Uncovered impact (blast radius nodes NOT modified -- potentially missing)
    - Contract violations (producers changed without consumer updates)

    Parameters
    ----------
    graph:
        The architecture graph.
    diff_files:
        Parsed diff files (from parse_diff()).

    Returns
    -------
    ChangeReport
        Structured validation results with recommendations.
    """
```

**Algorithm:**
1. Extract changed file paths from `diff_files`.
2. Call `map_files_to_nodes(graph, changed_paths)` to get changed node IDs.
3. Flatten to a set of all changed node IDs.
4. For each changed node, call `compute_blast_radius(graph, node_id)`.
5. Merge all blast radius results into a combined impact set (deduplicate by
   node ID, keep the shortest distance / highest severity).
6. Partition impact set:
   - **Covered:** nodes whose file_path matches any changed file path.
   - **Uncovered:** all others -- these are "potentially missing changes."
7. **Contract check:** For each changed node, find contract nodes where this
   node is the producer (check `metadata["producer"]`). For each such contract,
   check if consumer nodes are in the changed set. If not, add to
   `contract_violations`.
8. **Generate recommendations:** For each uncovered node, create a human-readable
   suggestion explaining the relationship (edge type, hop distance, which changed
   node connects to it).
9. Return `ChangeReport`.

##### 4. New function: `suggest_tests`

**Insert after:** `validate_changes`

**Signature:**
```python
def suggest_tests(
    graph: ArchGraph,
    diff_files: list[DiffFile],
    max_suggestions: int = 20,
) -> list[TestSuggestion]:
    """Identify and rank test files relevant to the given changes.

    Uses three strategies in priority order:
    1. Graph-based: test nodes with `source: test` metadata that import
       or depend on changed nodes.
    2. Naming convention: language-specific test file naming patterns.
    3. Blast radius: test files that cover transitive dependencies.

    Parameters
    ----------
    graph:
        The architecture graph.
    diff_files:
        Parsed diff files (from parse_diff()).
    max_suggestions:
        Maximum number of test suggestions to return.

    Returns
    -------
    list[TestSuggestion]
        Test files sorted by relevance score (highest first).
    """
```

**Algorithm:**
1. Map changed files to nodes (reuse `map_files_to_nodes`).
2. **Strategy 1 -- Graph-based:**
   a. Find all nodes with `metadata.get("source") == "test"`.
   b. For each test node, check if it has an `imports` edge pointing to any
      changed node. If yes, score = 1.0, strategy = "graph".
   c. Also check `contains` edges: if a test node is in the same module
      hierarchy as a changed node, score = 0.7.
3. **Strategy 2 -- Naming convention:**
   a. For each changed file, generate candidate test file names using
      language-specific patterns (Python: `test_{name}.py`, `{name}_test.py`,
      `tests/test_{name}.py`; Go: `{name}_test.go`; etc.).
   b. Check if any candidate exists as a node in the graph (by file_path or ID).
   c. If found, score = 1.0, strategy = "naming".
   d. If not found in graph, still suggest the path with score = 0.8, strategy
      = "naming" (the file may exist but not be in the graph).
4. **Strategy 3 -- Blast radius:**
   a. Compute blast radius for each changed node.
   b. For each node in the blast radius, check if it's a test file (by metadata
      or naming heuristic).
   c. Score = 0.5 for 1-hop distance, 0.3 for 2+ hops. Strategy = "blast_radius".
5. Deduplicate by file path. When the same test appears from multiple strategies,
   keep the highest score.
6. Sort by score descending, truncate to `max_suggestions`.

**Test naming patterns** (embedded in the function, not configurable):
```python
_TEST_PATTERNS: dict[str, list[str]] = {
    ".py": ["test_{name}.py", "{name}_test.py", "tests/test_{name}.py"],
    ".go": ["{name}_test.go"],
    ".ts": ["{name}.test.ts", "{name}.spec.ts", "__tests__/{name}.ts"],
    ".tsx": ["{name}.test.tsx", "{name}.spec.tsx", "__tests__/{name}.tsx"],
    ".js": ["{name}.test.js", "{name}.spec.js", "__tests__/{name}.js"],
    ".jsx": ["{name}.test.jsx", "{name}.spec.jsx", "__tests__/{name}.jsx"],
    ".rs": ["tests/{name}.rs"],
    ".java": ["{Name}Test.java", "{Name}Tests.java"],
    ".cs": ["{Name}Tests.cs", "{Name}Test.cs"],
    ".php": ["{Name}Test.php"],
    ".rb": ["{name}_spec.rb", "test_{name}.rb"],
}
```

##### 5. New function: `file_coupling`

**Insert after:** `suggest_tests`

**Signature:**
```python
def file_coupling(
    graph: ArchGraph,
    project_path: str,
    file_path: str | None = None,
    depth: int = 100,
    min_commits: int = 3,
    min_coupling: float = 0.1,
) -> list[CouplingPair]:
    """Mine git commit history to discover implicit file coupling.

    Files that are frequently changed together in the same commit have
    temporal coupling, regardless of whether they have an architectural
    relationship in the graph.

    Parameters
    ----------
    graph:
        The architecture graph (used to cross-reference coupling with edges).
    project_path:
        Path to the git repository.
    file_path:
        If provided, return only pairs involving this file.
    depth:
        Number of recent commits to analyze.
    min_commits:
        Minimum co-change commits for a pair to be reported.
    min_coupling:
        Minimum coupling ratio for a pair to be reported.

    Returns
    -------
    list[CouplingPair]
        Coupling pairs sorted by coupling ratio descending.

    Raises
    ------
    NotAGitRepoError
        If project_path is not a git repository.
    """
```

**Algorithm:**
1. Call `get_commit_file_history(project_path, depth)`.
2. Build co-change matrix:
   a. `file_change_counts: dict[str, int]` -- number of commits each file appears in.
   b. `co_change_counts: dict[tuple[str, str], int]` -- for each pair of files
      in the same commit, increment count. Use sorted tuple keys for dedup.
3. Compute coupling ratio for each pair:
   `coupling = co_change_count / max(change_count_a, change_count_b)`
4. Filter by `min_commits` and `min_coupling`.
5. If `file_path` is provided, filter to pairs containing that file.
6. **Cross-reference with graph:** For each pair, map both files to nodes using
   `map_files_to_nodes()`. Check if any edge exists between any pair of nodes.
   Set `in_graph=True` and `edge_type` if found.
7. Sort by coupling descending. Limit to top 20 if `file_path` is None.
8. Return list of `CouplingPair` objects.

### Tests

#### `tests/test_validate_changes.py` (new file)

**Test class: `TestMapFilesToNodes`**
- `test_map_files_exact_match` -- Node with `file_path="src/foo.py"`, map
  `["src/foo.py"]`, verify match.
- `test_map_files_suffix_match` -- Node with `file_path="src/foo.py"`, map with
  absolute path `/project/src/foo.py`, verify match via suffix.
- `test_map_files_module_id_match` -- Module node `module:src/foo.py`, map
  `["src/foo.py"]`, verify match.
- `test_map_files_no_match` -- File not in graph, returns empty list for that path.
- `test_map_files_multiple_nodes_per_file` -- File with module node + endpoint node,
  both returned.
- `test_map_files_empty_graph` -- No nodes, all files map to empty lists.

**Test class: `TestValidateChanges`**
- `test_validate_detects_uncovered_nodes` -- Change file A, A imports B, B not in
  diff -> B is uncovered.
- `test_validate_covered_node_not_flagged` -- Change files A and B, A imports B,
  B is covered.
- `test_validate_contract_violation` -- Change producer endpoint, consumer not in
  diff -> contract violation reported.
- `test_validate_no_contract_violation_when_consumer_changed` -- Both producer and
  consumer in diff, no violation.
- `test_validate_empty_diff` -- Empty diff files list, returns empty report.
- `test_validate_files_not_in_graph` -- Changed files don't map to nodes, report
  indicates this.
- `test_validate_recommendations_include_edge_type` -- Recommendations mention the
  relationship type (imports, contains, etc.).
- `test_validate_multi_file_combined_blast_radius` -- Change 3 files, verify blast
  radii are merged and deduplicated.

**Test count:** +14 tests

#### `tests/test_suggest_tests.py` (new file)

**Test class: `TestSuggestTests`**
- `test_suggest_graph_based_direct_import` -- Test node imports changed node, score = 1.0.
- `test_suggest_graph_based_sibling` -- Test node in same module as changed node, score = 0.7.
- `test_suggest_naming_convention_python` -- Changed `handler.py`, suggests
  `test_handler.py`.
- `test_suggest_naming_convention_go` -- Changed `handler.go`, suggests
  `handler_test.go`.
- `test_suggest_naming_convention_typescript` -- Changed `handler.ts`, suggests
  `handler.test.ts`, `handler.spec.ts`.
- `test_suggest_naming_convention_java` -- Changed `Handler.java`, suggests
  `HandlerTest.java`.
- `test_suggest_blast_radius_transitive` -- Test imports a node 2 hops from changed
  node, lower score.
- `test_suggest_deduplication` -- Same test found by graph + naming, highest score kept.
- `test_suggest_max_suggestions_limit` -- More test files found than max, truncated.
- `test_suggest_no_tests_found` -- No test nodes, no naming matches, returns empty.
- `test_suggest_generates_quick_run_command` -- Not part of the model, but validate
  the MCP tool formats it correctly (integration test).

**Test count:** +11 tests

#### `tests/test_file_coupling.py` (new file)

**Test class: `TestFileCoupling`**
- `test_coupling_basic` -- 3 commits where A+B always co-change, coupling = 1.0.
- `test_coupling_partial` -- A changes 10 times, B changes 5 times, 3 co-changes,
  coupling = 3/10 = 0.3.
- `test_coupling_min_commits_filter` -- Pair with 2 co-changes, `min_commits=3`,
  filtered out.
- `test_coupling_min_coupling_filter` -- Pair with coupling 0.05, `min_coupling=0.1`,
  filtered out.
- `test_coupling_file_path_filter` -- With `file_path` set, only pairs involving
  that file returned.
- `test_coupling_cross_reference_in_graph` -- Coupled pair has graph edge,
  `in_graph=True`.
- `test_coupling_cross_reference_not_in_graph` -- Coupled pair without graph edge,
  `in_graph=False`.
- `test_coupling_top_20_limit` -- More than 20 pairs, only top 20 returned when
  `file_path=None`.
- `test_coupling_not_git_repo` -- Raises `NotAGitRepoError`.
- `test_coupling_empty_history` -- No commits, returns empty list.
- `test_coupling_single_file_commits` -- Commits with only one file, no pairs.

**Test count:** +11 tests

---

## Phase 5: MCP Tool Wrappers (Depends on Phase 4)

### Rationale
Three new MCP tools and one enhancement. Each tool is a thin wrapper that loads
the graph, calls the corresponding query function, and formats the result as
markdown. This follows the exact pattern of every existing MCP tool in `server.py`.

### Files to Modify

#### `src/codegiraffe/server.py`

##### 1. Add imports

**Location:** After existing `from codegiraffe.query import` block (line 19-28)

**Add to the import list:**
```python
from codegiraffe.query import (
    # ... existing imports ...
    file_coupling,
    map_files_to_nodes,
    suggest_tests,
    validate_changes,
)
from codegiraffe.diff_parser import parse_diff
from codegiraffe.git_utils import (
    get_changed_files,
    get_uncommitted_diff,
    is_git_repo,
    NotAGitRepoError,
)
```

##### 2. New section header

**Insert after:** `codegiraffe_add_contract` tool (after the cross-system contract
tools section)

```python
# ---------------------------------------------------------------------------
# Change impact validation tools (v0.10.0)
# ---------------------------------------------------------------------------
```

##### 3. New tool: `codegiraffe_validate_changes`

**Signature:**
```python
@mcp.tool()
def codegiraffe_validate_changes(
    project_path: str,
    diff: str | None = None,
    auto: bool = True,
) -> str:
    """Analyze uncommitted changes against the architecture graph.

    Detects incomplete modifications, missed contract updates, and impacted
    nodes that were not touched. Returns a markdown validation report with
    specific recommendations.

    When `auto` is True (default), reads uncommitted changes via `git diff HEAD`.
    Alternatively, pass a raw unified diff string via the `diff` parameter.
    """
```

**Implementation:**
```python
    try:
        graph = _ensure_graph(project_path)

        # Get the diff
        if diff is not None:
            raw_diff = diff
        elif auto:
            raw_diff = get_uncommitted_diff(project_path)
        else:
            return "Error: either provide a `diff` string or set `auto=True`."

        if not raw_diff.strip():
            return "No uncommitted changes detected."

        # Parse and validate
        diff_files = parse_diff(raw_diff)
        if not diff_files:
            return "No file changes found in the diff."

        report = validate_changes(graph, diff_files)
        return _format_validation_report(report)
    except NotAGitRepoError:
        return (
            "Error: project is not a git repository. "
            "Provide a `diff` string explicitly or initialize git."
        )
    except Exception as exc:
        return f"Error validating changes: {exc}"
```

##### 4. New helper: `_format_validation_report`

**Insert after:** `codegiraffe_validate_changes`

```python
def _format_validation_report(report: ChangeReport) -> str:
    """Format a ChangeReport as a markdown validation report."""
```

**Output format:** Follows the markdown structure specified in the spec:
- `## Change Impact Validation`
- `### Changes Detected` -- list of changed files with status and hunk/line info
- `### Impact Analysis` -- total blast radius with severity breakdown
- `### Covered Impact` -- blast radius nodes already in the diff
- `### Potentially Missing Changes` -- uncovered nodes with relationship explanations
- `### Contract Violations` -- producers changed without consumer updates
- `### Recommendations` -- numbered actionable suggestions

##### 5. New tool: `codegiraffe_suggest_tests`

**Signature:**
```python
@mcp.tool()
def codegiraffe_suggest_tests(
    project_path: str,
    diff: str | None = None,
    auto: bool = True,
    max_suggestions: int = 20,
) -> str:
    """Suggest test files relevant to uncommitted changes.

    Identifies and ranks test files using graph relationships, naming
    conventions, and blast radius analysis. Returns a markdown report
    with a quick-run command.

    When `auto` is True (default), reads uncommitted changes via `git diff HEAD`.
    """
```

**Implementation:**
```python
    try:
        graph = _ensure_graph(project_path)

        if diff is not None:
            raw_diff = diff
        elif auto:
            raw_diff = get_uncommitted_diff(project_path)
        else:
            return "Error: either provide a `diff` string or set `auto=True`."

        if not raw_diff.strip():
            return "No uncommitted changes detected."

        diff_files = parse_diff(raw_diff)
        if not diff_files:
            return "No file changes found in the diff."

        suggestions = suggest_tests(graph, diff_files, max_suggestions)
        return _format_test_suggestions(suggestions, diff_files)
    except NotAGitRepoError:
        return (
            "Error: project is not a git repository. "
            "Provide a `diff` string explicitly or initialize git."
        )
    except Exception as exc:
        return f"Error suggesting tests: {exc}"
```

##### 6. New helper: `_format_test_suggestions`

```python
def _format_test_suggestions(
    suggestions: list[TestSuggestion],
    diff_files: list[DiffFile],
) -> str:
    """Format test suggestions as a markdown report."""
```

**Output format:** As specified:
- `## Suggested Tests`
- `### High Relevance (direct coverage)` -- score >= 0.8
- `### Medium Relevance (related coverage)` -- 0.5 <= score < 0.8
- `### Low Relevance (transitive coverage)` -- score < 0.5
- `**Quick run command:**` -- pytest/go test/etc. for top suggestions

##### 7. New tool: `codegiraffe_file_coupling`

**Signature:**
```python
@mcp.tool()
def codegiraffe_file_coupling(
    project_path: str,
    file_path: str | None = None,
    depth: int = 100,
    min_commits: int = 3,
    min_coupling: float = 0.1,
) -> str:
    """Mine git history to discover implicit file coupling.

    Files frequently changed together in the same commit have temporal coupling.
    Cross-references coupling data with the architecture graph to identify
    implicit dependencies not captured by static analysis.

    When `file_path` is provided, shows files most coupled to that file.
    Otherwise, shows the top coupled pairs across the project.
    """
```

**Implementation:**
```python
    try:
        graph = _ensure_graph(project_path)
        pairs = file_coupling(
            graph, project_path,
            file_path=file_path,
            depth=depth,
            min_commits=min_commits,
            min_coupling=min_coupling,
        )
        return _format_coupling_report(pairs, file_path, depth)
    except NotAGitRepoError:
        return "Error: project is not a git repository."
    except Exception as exc:
        return f"Error analyzing file coupling: {exc}"
```

##### 8. New helper: `_format_coupling_report`

```python
def _format_coupling_report(
    pairs: list[CouplingPair],
    file_path: str | None,
    depth: int,
) -> str:
    """Format coupling pairs as a markdown report."""
```

**Output format:** As specified:
- `## File Coupling Analysis`
- `**Commits analyzed:** {depth}`
- Table with columns: Coupled File, Co-Changes, Coupling, In Graph?
- `### Implicit Coupling (not in graph)` -- pairs without graph edges

##### 9. Enhance: `codegiraffe_context_for`

**Location:** Existing function at line 264

**Changes:**
1. Add `include_changes: bool = False` parameter to the function signature.
2. Add to the docstring: `"When *include_changes* is True, reads uncommitted git
   changes and boosts scores for recently changed and blast-radius-adjacent nodes."`
3. After `subgraph = context_for_task(...)` (line 287), add the change-awareness
   logic:

```python
        if include_changes:
            try:
                changed_paths = get_changed_files(project_path)
                if changed_paths:
                    file_node_map = map_files_to_nodes(graph, changed_paths)
                    changed_nids = set()
                    for nids in file_node_map.values():
                        changed_nids.update(nids)

                    # Compute blast radius of changed nodes
                    blast_nids: set[str] = set()
                    for nid in changed_nids:
                        if nid in graph.graph:
                            descendants = graph.get_all_descendants(nid)
                            blast_nids.update(descendants)

                    # Boost scores
                    for nid, node in subgraph.nodes.items():
                        current_score = node.metadata.get("_relevance_score", 0)
                        if nid in changed_nids:
                            node.metadata["_relevance_score"] = current_score + 0.3
                            node.metadata["_recently_changed"] = True
                        elif nid in blast_nids:
                            node.metadata["_relevance_score"] = current_score + 0.15
                            node.metadata["_in_change_blast_radius"] = True
            except Exception:
                pass  # Silently fall back -- change awareness is best-effort
```

4. The `include_changes=False` default ensures backward compatibility.

### Tests

#### `tests/test_server_validate_changes.py` (new file)

**Test class: `TestValidateChangesTool`**
- `test_validate_changes_auto_detects_diff` -- Integration: init repo, make changes,
  run tool with `auto=True`.
- `test_validate_changes_explicit_diff` -- Pass diff string directly.
- `test_validate_changes_no_diff_no_auto` -- `diff=None, auto=False` returns error.
- `test_validate_changes_not_git_repo` -- Returns git error message.
- `test_validate_changes_no_graph` -- Returns "init first" error.
- `test_validate_changes_no_uncommitted` -- `auto=True`, clean repo, returns
  "no changes" message.

**Test class: `TestSuggestTestsTool`**
- `test_suggest_tests_returns_markdown` -- Verify markdown output structure.
- `test_suggest_tests_quick_run_command` -- Verify pytest command in output.
- `test_suggest_tests_no_tests_found_message` -- Helpful message about rescanning.

**Test class: `TestFileCouplingTool`**
- `test_file_coupling_returns_table` -- Verify markdown table in output.
- `test_file_coupling_with_file_path` -- Filtered to specific file.
- `test_file_coupling_not_git_repo` -- Returns error message.
- `test_file_coupling_no_pairs_above_threshold` -- Returns threshold guidance.

**Test count:** +13 tests

#### `tests/test_context_for_changes.py` (new file)

**Test class: `TestContextForChanges`**
- `test_include_changes_false_unchanged_behavior` -- Default parameter, verify
  output is identical to v0.8.0 behavior (no boost metadata).
- `test_include_changes_true_boosts_changed_nodes` -- Changed node gets +0.3
  score boost and `_recently_changed=True`.
- `test_include_changes_true_boosts_blast_radius` -- Node in blast radius of
  changed node gets +0.15 boost and `_in_change_blast_radius=True`.
- `test_include_changes_true_not_git_repo_silent_fallback` -- Not a git repo,
  silently falls back to normal behavior (no error).
- `test_include_changes_true_no_uncommitted_changes` -- Clean repo, normal
  behavior (no boost).
- `test_include_changes_true_score_ordering` -- Verify nodes are re-sorted by
  boosted scores.

**Test count:** +6 tests

---

## Phase 6: Format Helpers + Edge Cases (Parallel with Phase 5)

### Rationale
The markdown formatting functions (`_format_validation_report`,
`_format_test_suggestions`, `_format_coupling_report`) are complex enough to
warrant dedicated tests. This phase also covers edge case handling that cuts
across features.

### Tests

#### `tests/test_format_reports.py` (new file)

**Test class: `TestFormatValidationReport`**
- `test_format_empty_report` -- No uncovered nodes, no violations, clean output.
- `test_format_with_uncovered_nodes` -- Verify "Potentially Missing Changes" section.
- `test_format_with_contract_violations` -- Verify "Contract Violations" section.
- `test_format_recommendations_numbered` -- Verify numbered recommendation list.
- `test_format_changed_files_list` -- Verify file status indicators (added/modified/deleted).

**Test class: `TestFormatTestSuggestions`**
- `test_format_high_relevance_section` -- Score >= 0.8 in "High Relevance" section.
- `test_format_medium_relevance_section` -- 0.5 <= score < 0.8 in "Medium".
- `test_format_low_relevance_section` -- Score < 0.5 in "Low Relevance".
- `test_format_quick_run_command` -- pytest command includes top suggestion paths.
- `test_format_empty_suggestions` -- No suggestions, helpful message.

**Test class: `TestFormatCouplingReport`**
- `test_format_coupling_table` -- Verify markdown table structure.
- `test_format_implicit_coupling_section` -- Pairs not in graph highlighted.
- `test_format_no_pairs` -- No coupling pairs, threshold guidance message.
- `test_format_with_file_path_header` -- When `file_path` provided, header mentions it.

**Test count:** +14 tests

---

## Phase 7: Polish (Last)

### Rationale
Version bump, documentation, and final verification. No new features.

### Files to Modify

#### `pyproject.toml`
- Bump `version` from `"0.8.0"` to `"0.10.0"`.

#### `CLAUDE.md`
- Update `Version` line to `0.10.0`.
- Update tool count from 25 to ~28.
- Update test count target to 890+.
- Add `diff_parser.py` and `git_utils.py` to project structure.
- Add `Recent Changes` entry for v0.10.0.
- Add new MCP tool descriptions.

#### `README.md`
- Add change impact validation tools to tool list.
- Add feature description for v0.10.0.
- Update version references.

### Verification

Run the full test suite:
```bash
source .venv/bin/activate && python -m pytest tests/ -v
```

- All 791 existing tests must pass unchanged.
- 100+ new tests must pass.
- Total test count: 890+.

### Test count: +0 (no new tests in this phase)

---

## Summary

| Phase | Files Created/Modified | New Functions | Tests Added |
|-------|----------------------|---------------|-------------|
| 1. Data Models | diff_parser.py (create) | 0 (models only) | 6 |
| 2. Diff Parser | diff_parser.py (modify) | 2 (parse_diff, extract_symbol_hints) | 16 |
| 3. Git Utilities | git_utils.py (create) | 4 (is_git_repo, get_uncommitted_diff, get_changed_files, get_commit_file_history) | 13 |
| 4. Query Engine | query.py (modify) | 4 (map_files_to_nodes, validate_changes, suggest_tests, file_coupling) | 36 |
| 5. MCP Tools | server.py (modify) | 7 (3 tools + 3 formatters + 1 enhancement) | 19 |
| 6. Format Helpers | (tests only) | 0 | 14 |
| 7. Polish | pyproject.toml, CLAUDE.md, README.md | 0 | 0 |
| **Total** | **5 source files, 8 test files** | **17 functions** | **104 tests** |

### Dependency Graph

```
Phase 1 (Data Models)
  |
  +---> Phase 2 (Diff Parser) ---+
  |                               |
  +---> Phase 3 (Git Utilities) --+--> Phase 4 (Query Engine) --> Phase 5 (MCP Tools)
                                  |                                      |
                                  +--> Phase 6 (Format Helpers) ---------+--> Phase 7 (Polish)
```

Phases 2 and 3 can proceed in parallel once Phase 1 is complete.
Phase 4 depends on both Phases 2 and 3 (needs both diff parsing and git utils).
Phases 5 and 6 can proceed in parallel once Phase 4 is complete.
Phase 7 is the final merge/polish after all feature phases.

### New MCP Tools (3 new + 1 enhanced, ~28 total)

| Tool | Description |
|------|-------------|
| `codegiraffe_validate_changes` | Pre-commit change validation against the architecture graph |
| `codegiraffe_suggest_tests` | Test file identification and ranking for changes |
| `codegiraffe_file_coupling` | Git history mining for implicit file coupling |
| `codegiraffe_context_for` (enhanced) | New `include_changes` parameter for change-aware context |

### New Source Files

| File | Description |
|------|-------------|
| `src/codegiraffe/diff_parser.py` | Unified diff parser + data models (DiffFile, DiffHunk, ChangeReport, TestSuggestion, CouplingPair) |
| `src/codegiraffe/git_utils.py` | Git command helpers (subprocess wrappers) |

### Modified Source Files

| File | Changes |
|------|---------|
| `src/codegiraffe/query.py` | +4 functions: map_files_to_nodes, validate_changes, suggest_tests, file_coupling |
| `src/codegiraffe/server.py` | +3 tools + 3 format helpers + 1 enhanced tool + new imports |
| `pyproject.toml` | Version bump to 0.10.0 |

### New Test Files

| File | Tests | Description |
|------|-------|-------------|
| `tests/test_diff_parser.py` | 22 | Diff parsing models and parse_diff function |
| `tests/test_git_utils.py` | 13 | Git command helpers |
| `tests/test_validate_changes.py` | 14 | map_files_to_nodes + validate_changes |
| `tests/test_suggest_tests.py` | 11 | Test suggestion logic |
| `tests/test_file_coupling.py` | 11 | File coupling analysis |
| `tests/test_server_validate_changes.py` | 13 | MCP tool integration tests |
| `tests/test_context_for_changes.py` | 6 | context_for include_changes enhancement |
| `tests/test_format_reports.py` | 14 | Markdown report formatting |

### Key Design Decisions

1. **Separate `diff_parser.py` module.** The diff parser has zero dependencies on
   the architecture graph, git, or any CodeGiraffe module. Keeping it separate
   makes it independently testable and ensures clean dependency boundaries. The
   alternative (putting it in `query.py`) would bloat an already-large module.

2. **Separate `git_utils.py` module.** Git command execution is currently scattered
   (`_detect_git_renames` in `query.py`). A dedicated module provides a single
   place for all git interactions, consistent error types (`GitError`,
   `NotAGitRepoError`), and uniform timeout/subprocess handling. The existing
   `_detect_git_renames` in `query.py` is left in place to avoid breaking the
   existing `detect_drift` function -- it can be migrated in a future refactor.

3. **Pydantic v2 models for outputs.** `ChangeReport`, `TestSuggestion`, and
   `CouplingPair` are Pydantic models rather than plain dicts. This gives us
   validation, serialization, and clear type contracts. The MCP tools convert
   these to markdown strings for human-readable output, but the structured models
   can also be used programmatically.

4. **`subprocess.run()` for git commands.** Consistent with the existing
   `_detect_git_renames()` pattern. No git libraries (like `gitpython`) are
   introduced -- this keeps the dependency footprint zero for new required deps.

5. **Suffix matching for file-to-node mapping.** Graph nodes may have relative
   paths (`src/foo.py`) while diffs may have the same or different relative paths
   depending on the working directory. Suffix matching (`file_path.endswith(path)`)
   handles this robustly without requiring path normalization.

6. **Scoring constants inline.** Test suggestion scoring (1.0, 0.7, 0.5, 0.3)
   and context_for boosting (+0.3, +0.15) are inline constants, not configurable.
   This follows the existing pattern where `_compute_severity` uses hardcoded
   hop-distance thresholds and `_score_node` uses simple keyword counting.

7. **Silent fallback for `include_changes`.** When `include_changes=True` but
   git is not available or fails, the tool silently falls back to normal behavior.
   This matches the spec: change awareness is "nice to have" enrichment, not a
   hard requirement. The try/except around the entire block ensures no error
   propagation.

8. **No new required dependencies.** All git operations use `subprocess`. Diff
   parsing is pure Python regex. No new pip packages are required.

### Risk Assessment

**Low risk:**
- Phase 1 (new models, purely additive, no existing code touched)
- Phase 2 (new module with no dependencies on existing code)
- Phase 3 (new module; git operations follow proven `_detect_git_renames` pattern)
- Phase 7 (documentation only)

**Medium risk:**
- Phase 4 (new functions in `query.py` -- extensive logic, but additive only;
  no existing functions are modified)
  - Mitigation: `map_files_to_nodes` is a simple lookup. `validate_changes` and
    `suggest_tests` compose existing functions (`compute_blast_radius`,
    `map_files_to_nodes`). `file_coupling` is self-contained.
- Phase 6 (formatting functions must produce correct markdown)
  - Mitigation: dedicated tests for each format function covering edge cases.

**Highest risk:**
- Phase 5 (`codegiraffe_context_for` modification -- changing an existing function)
  - Mitigation: The `include_changes` parameter defaults to `False`, so all
    existing behavior is preserved. The new code block is wrapped in try/except
    with a bare `pass`, so even if the change-awareness logic crashes, the tool
    returns normal results. All 6 existing `context_for` tests will pass
    unchanged because they never set `include_changes=True`.
  - Additional mitigation: 6 dedicated tests in `test_context_for_changes.py`
    cover the new behavior.

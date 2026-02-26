# Implementation Plan: Security Hardening

**Branch**: `036-security-hardening` | **Date**: 2026-02-25 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/036-security-hardening/spec.md`

## Summary

Six targeted hardening changes across three surface areas (dashboard HTTP API, scanner file traversal, subprocess execution) plus test infrastructure consolidation. The changes are additive guards — they tighten existing code without replacing its architecture. Every fix has an independent test scenario verifiable in isolation.

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: FastMCP (mcp[cli] >= 1.2.0), NetworkX >= 3.0, Starlette (via FastMCP custom routes), pytest >= 8.0
**Storage**: JSON files (primary), SQLite (secondary) — no storage-layer changes in this spec
**Testing**: pytest >= 8.0, pytest-asyncio >= 0.23
**Target Platform**: Linux server (localhost-only dashboard)
**Performance Goals**: No new latency introduced; all guards operate in O(1) path lookups or short-circuit before file I/O
**Constraints**: No breaking changes to MCP tool signatures; all parameter caps must be silent (clamp, not reject); dashboard path guard must survive a server restart (projects re-initialize themselves via normal MCP tool usage)
**Scale/Scope**: 6 user stories, ~8 source files touched, ~10 new test files or expansions

## Constitution Check

| Principle | Assessment |
|-----------|-----------|
| I. MCP-Native | All fixes are in MCP tools or their HTTP backing routes. No new protocols. |
| II. Graph-First | No graph model changes — hardening only. |
| III. Beyond-AST | Not applicable — security hardening. |
| IV. Context Efficiency | Path-validation guard is O(1) set lookup; no extra traversal. |
| V. Incremental & Non-Destructive | All changes are additive guards. `manual=True` nodes unaffected. |
| VI. Test-First (NON-NEGOTIABLE) | Tests written before every implementation task. |
| VII. Simplicity | Each fix is the simplest possible change: guard function, `timeout=` arg, `html.escape()` call, `min(depth, MAX)`. |

## Project Structure

### Documentation (this feature)

```text
specs/036-security-hardening/
├── plan.md              # This file
├── spec.md              # Feature specification (already exists)
├── checklists/          # Already exists
└── tasks.md             # Phase 2 output (tasks.md — created separately)
```

### Source Code (affected files)

```text
src/codegiraffe/
├── dashboard.py         # US1: add path allowlist guard; US4: escape t variable in dist/legend innerHTML
├── scanner.py           # US2: add symlink boundary check in scan_project() rglob loop
├── git_utils.py         # US3: add timeout=30 to all subprocess.run() calls
├── server.py            # US5: add MAX_QUERY_DEPTH / MAX_COUPLING_DEPTH / MAX_EXPORT_DEPTH constants and clamping

tests/
├── conftest.py          # US6: add reset_server_state fixture + git helper functions (_GIT_ENV, _git, _init_repo, _commit_file/_commit_files)
├── test_dashboard_path_guard.py    # US1: new test file
├── test_scanner_symlinks.py        # US2: new test file
├── test_git_utils_timeout.py       # US3: new test file (or expand test_git_utils.py)
├── test_dashboard_xss.py           # US4: new test file (or expand test_dashboard.py)
├── test_depth_bounds.py            # US5: new test file
├── test_server.py                  # US6: remove local reset_server_state, import from conftest
├── test_server_integration.py      # US6: remove local reset_server_state, import from conftest
├── test_server_validate_changes.py # US6: remove local reset_server_state, import from conftest
├── test_context_for_changes.py     # US6: remove local reset_server_state, import from conftest
├── test_task_ordering.py           # US6: remove local reset_server_state class fixture, use module-level from conftest
├── test_file_coupling.py           # US6: remove local _GIT_ENV/_git/_init_repo/_commit_files, import from conftest
├── test_graph_diff.py              # US6: remove local _GIT_ENV/_git/_init_repo/_commit_file, import from conftest
└── test_git_utils.py               # US6: remove local _GIT_ENV/_git/_init_repo/_commit_file, import from conftest
```

**Structure Decision**: Single project layout — all source under `src/codegiraffe/`, all tests under `tests/`. No structural changes, only file edits and additions.

---

## Detailed Technical Findings

### US1 — Dashboard Path Guard (`dashboard.py`, `server.py`)

**Current behavior**: `POST /api/init` at line 1242–1277 of `dashboard.py` accepts any `project_path` string, calls `scan_project(project_path)` on it without validation. `GET /api/graph`, `GET /api/node`, `GET /api/subgraph` call `ensure_graph_fn(project_path)` which loads from disk storage — similarly unrestricted.

**Root cause**: No allowlist of initialized projects is maintained in server state. The dashboard's `/api/init` endpoint independently scans arbitrary paths without consulting `server.py`'s `_ensure_graph` guard.

**Fix design**:
1. Add `_initialized_project_paths: set[str]` to `server.py` module globals (alongside `_graph`, `_storage`, etc.), protected by `_graph_lock`.
2. When `codegiraffe_init()` succeeds, add `project_path` to the set.
3. In `dashboard.py`'s `init_graph()` route, before calling `scan_project()`, check `project_path` against the allowlist from `srv._initialized_project_paths` — reject with HTTP 403 if not found.
4. The `_ensure_graph` path (`/api/graph`, `/api/node`, `/api/subgraph`) already raises `RuntimeError` when no graph is stored — that is sufficient for those routes.
5. Reset fixture must also reset `_initialized_project_paths = set()`.

**Key insight**: The allowlist lives in memory. After a server restart, `_initialized_project_paths` is empty. Projects re-enter the allowlist when `codegiraffe_init()` is called via MCP tools (as intended per the spec assumption).

---

### US2 — Symlink Boundary Check (`scanner.py`)

**Current behavior**: `scan_project()` at line 2144 uses `root.rglob("*")` which does not follow symlinks by default in Python's `pathlib`. However, symlinked files that exist within the traversal are returned by `rglob` as entries. The check at line 2145 (`source_file.is_file()`) returns `True` for symlinked files, and line 2164 reads the symlink target's content unconditionally.

**Specific issue**: `Path.rglob("*")` in Python 3.11 does yield symlinks to files (as file entries). Symlinks to directories inside the root are followed only if `Path.rglob` crosses into them. The critical gap is: a symlinked file or directory whose resolved path falls outside the project root will be traversed.

**Fix design**:
```python
def _is_within_root(path: Path, root: Path) -> bool:
    """Return True if path resolves to a location inside root."""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False
```
In the `for source_file in sorted(root.rglob("*")):` loop, after the `is_file()` check, add:
```python
if source_file.is_symlink() and not _is_within_root(source_file, root):
    import warnings
    warnings.warn(f"Skipping symlink outside project root: {source_file}", stacklevel=2)
    continue
```
Symlinks within the project root pass through unchanged (US2 acceptance scenario 3).
Circular symlinks: `Path.resolve()` follows the chain; on Linux it will eventually raise `OSError` (too many levels of symbolic links). Wrap in a `try/except OSError` that skips the path with a warning.

---

### US3 — Subprocess Timeouts (`git_utils.py`)

**Current behavior**: All 5 `subprocess.run()` calls in `git_utils.py` lack `timeout=`. On a slow or corrupt repository, any of these hangs indefinitely, blocking the MCP server thread.

**Affected calls** (file lines):
- `is_git_repo()` — line 27
- `get_uncommitted_diff()` — line 51, 61 (fallback)
- `get_changed_files()` — line 81
- `get_commit_file_history()` — line 110

**Fix design**:
1. Add module-level constant: `GIT_COMMAND_TIMEOUT: int = 30`
2. Add `timeout=GIT_COMMAND_TIMEOUT` to every `subprocess.run()` call.
3. Catch `subprocess.TimeoutExpired` in each function and raise a new `GitTimeoutError(GitError)` with a message including the command list and timeout value.
4. Callers (`server.py`, `patterns.py`) already catch broad exceptions — `GitTimeoutError` propagates naturally.

**Error message format**: `f"Git command timed out after {GIT_COMMAND_TIMEOUT}s: {cmd}"`

---

### US4 — XSS Escaping in Dashboard (`dashboard.py`)

**Current behavior**: The `escapeHtml(s)` JavaScript function (line 476) is defined and used correctly in node detail panels (lines 647, 650, 661, 670) and tooltip text (line 688). However, three `innerHTML` assignments use unescaped graph-derived values:

1. **Type distribution panel** (line 785): `html += '...' + t + '...'` where `t` comes from `graphologyGraph.getNodeAttribute(id, 'nodeType')` — graph data, unescaped.
2. **Legend panel** (line 831): `html += '...' + t + '...'` where `t` iterates `Object.keys(TYPE_COLORS)` — these are hardcoded constants, not graph data, so they are actually safe. However, for defense in depth the escaping should be applied.
3. **Legend edge styles** (line 843): `html += '...' + t + '...'` where `t` iterates `Object.keys(edgeStyles)` — same as above (hardcoded, but should be escaped).

**The actual XSS vector**: The type distribution panel (1) is the real risk — node types come from scanned files. A malicious repo could define a class/entity whose inferred node type contains `<script>`.

**Fix**: Wrap `t` with `escapeHtml(t)` in all three innerHTML-building loops. The `escapeHtml` function is already available in the same script scope.

---

### US5 — Parameter Upper Bounds (`server.py`)

**Current behavior**: The following tool parameters have no upper bound:

| Tool | Parameter | Default | No Cap |
|------|-----------|---------|--------|
| `codegiraffe_query` | `depth` | 2 | passes directly to `query_by_node()` NetworkX BFS |
| `codegiraffe_blast_radius` | `max_depth` | `None` | `None` means unlimited depth in `compute_blast_radius()` |
| `codegiraffe_file_coupling` | `depth` | 100 | passes directly to `get_commit_file_history()` which uses `-n{depth}` in git log |
| `codegiraffe_export` | `depth` | 2 | passes to `graph.get_subgraph()` |
| `codegiraffe_cross_query` | `depth` | 2 | passes to `_federation.query_federated()` |

**Fix design**:
```python
# Named constants at top of server.py (after imports, before mcp = FastMCP)
MAX_QUERY_DEPTH: int = 20          # graph traversal hops
MAX_COUPLING_DEPTH: int = 500      # git log commits
MAX_BLAST_DEPTH: int = 20          # blast radius hops
```
Apply with `min()` at each call site:
- `codegiraffe_query`: `depth = min(depth, MAX_QUERY_DEPTH)` before `query_by_node()`
- `codegiraffe_blast_radius`: `max_depth = min(max_depth, MAX_BLAST_DEPTH) if max_depth is not None else MAX_BLAST_DEPTH`
- `codegiraffe_file_coupling`: `depth = min(depth, MAX_COUPLING_DEPTH)` before `file_coupling()`
- `codegiraffe_export`: `depth = min(depth, MAX_QUERY_DEPTH)` before `graph.get_subgraph()`
- `codegiraffe_cross_query`: `depth = min(depth, MAX_QUERY_DEPTH)` before `_federation.query_federated()`

Values within bounds pass through unchanged (acceptance scenario 2).

---

### US6 — Test Infrastructure Consolidation (`tests/conftest.py`)

**Current duplication inventory**:

**`reset_server_state` fixture** — defined in 5 locations with variations:
| File | Scope | What it resets |
|------|-------|----------------|
| `test_server.py` L30 | module autouse | `_graph`, `_storage`, `_version_store`, `_federation` |
| `test_server_validate_changes.py` L31 | module autouse | `_graph`, `_storage` only |
| `test_server_integration.py` L52 | module autouse | `_graph`, `_storage`, `_version_store`, `_federation` |
| `test_context_for_changes.py` L27 | module autouse | `_graph`, `_storage` only |
| `test_task_ordering.py` L312 | class autouse | `_graph`, `_storage` only |

**Canonical version**: Must reset `_graph`, `_storage`, `_version_store`, `_federation`, and (after US1) `_initialized_project_paths`. Place in `conftest.py` with `autouse=False` (modules that need it opt in via `usefixtures` or parameter, to avoid polluting tests that don't use server state).

**`_GIT_ENV` / `_git()` / `_init_repo()` / `_commit_file()` / `_commit_files()`** — defined in 3 locations:
| File | Functions |
|------|-----------|
| `test_git_utils.py` L28–L60 | `_GIT_ENV`, `_git`, `_init_repo`, `_commit_file` |
| `test_file_coupling.py` L23–L55 | `_GIT_ENV`, `_git`, `_init_repo`, `_commit_files` (plural) |
| `test_graph_diff.py` L45–L75 | `_GIT_ENV`, `_git`, `_init_repo`, `_commit_file` |

**Canonical version**: Expose in `conftest.py` as module-level functions. Both `_commit_file` and `_commit_files` variants are needed (different call signatures used by different tests).

---

## Complexity Tracking

No constitution violations. All changes are minimal guards on existing surfaces.

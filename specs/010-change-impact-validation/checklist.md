# Validation Checklist: Code Giraffe v0.10.0 -- Change Impact Validation

Use this checklist to verify all requirements are met before merging.

---

## 1. Diff Parsing Correctness

### Unified Diff Format
- [ ] Single modified file parsed correctly (path, status="modified")
- [ ] Multiple files in one diff parsed in order
- [ ] New file detected (`--- /dev/null` -> status="added")
- [ ] Deleted file detected (`+++ /dev/null` -> status="deleted")
- [ ] Renamed file detected (`rename from`/`rename to` headers -> status="renamed", `old_path` set)
- [ ] Hunk markers parsed: `@@ -old_start,old_count +new_start,new_count @@`
- [ ] Hunk header context text extracted (function/class name after `@@`)
- [ ] Addition count (`+` lines) and deletion count (`-` lines) accurate per file

### Edge Cases
- [ ] Empty diff string returns empty list (no crash)
- [ ] Binary file diff sets `is_binary=True`, no hunks parsed
- [ ] `\ No newline at end of file` marker handled without corrupting counts
- [ ] File paths with spaces parsed correctly
- [ ] Diff with only `diff --git` header and no hunks handled gracefully
- [ ] Hunk with count=0 (e.g., `@@ -0,0 +1,5 @@`) parsed correctly

### Symbol Hints
- [ ] Python `def function_name(` extracted from hunk header
- [ ] Python `class ClassName(` extracted from hunk header
- [ ] Empty hunk header produces no hints
- [ ] Duplicate function names across hunks deduplicated

---

## 2. Git Utility Reliability

### is_git_repo
- [ ] Returns `True` for valid git repository (initialized with `git init`)
- [ ] Returns `False` for plain directory (no `.git`)
- [ ] Does not raise exceptions for non-git directories

### get_uncommitted_diff
- [ ] Returns diff string when unstaged changes exist
- [ ] Returns diff string when only staged changes exist
- [ ] Returns empty string when working tree is clean
- [ ] Raises `NotAGitRepoError` for non-git directory
- [ ] Handles new repository with no commits (falls back to `git diff --cached`)
- [ ] Subprocess timeout set (does not hang on large repos)

### get_changed_files
- [ ] Returns list of modified file paths
- [ ] Returns empty list when working tree is clean
- [ ] Returns empty list (not exception) for non-git directory
- [ ] Paths are relative to repository root

### get_commit_file_history
- [ ] Returns correct file lists per commit (most-recent-first)
- [ ] Respects `depth` parameter (limits number of commits analyzed)
- [ ] Raises `NotAGitRepoError` for non-git directory
- [ ] Returns empty list for repository with no commits
- [ ] Omits commits with no file changes (e.g., merge commits)

### Error Handling
- [ ] `GitError` is base exception, `NotAGitRepoError` inherits from it
- [ ] Git not installed on system does not crash (graceful error)
- [ ] Subprocess timeout prevents hanging on unresponsive git

---

## 3. validate_changes Accuracy

### File-to-Node Mapping
- [ ] Exact path match (`src/foo.py` -> node with `file_path="src/foo.py"`)
- [ ] Suffix match (absolute path `/project/src/foo.py` matches node `src/foo.py`)
- [ ] Module ID match (`src/foo.py` matches node `module:src/foo.py`)
- [ ] Multiple nodes per file all returned (e.g., module node + endpoint node)
- [ ] Files not in graph mapped to empty list (not omitted)
- [ ] Empty graph returns all files mapped to empty lists

### Blast Radius Computation
- [ ] Single changed node: blast radius computed via `compute_blast_radius()`
- [ ] Multiple changed nodes: blast radii merged and deduplicated
- [ ] Blast radius nodes in diff marked as "covered"
- [ ] Blast radius nodes NOT in diff marked as "uncovered" with reason
- [ ] `total_blast_radius` count is accurate

### Contract Violation Detection
- [ ] Producer endpoint changed, consumer not in diff -> violation reported
- [ ] Producer endpoint changed, consumer also in diff -> no violation
- [ ] Non-contract nodes changed -> no spurious violations
- [ ] Multiple contracts with same producer all checked

### Recommendations
- [ ] Each uncovered node has a recommendation with relationship type (imports, contains, etc.)
- [ ] Recommendations mention which changed file triggered the impact
- [ ] Empty diff produces empty report (no recommendations)
- [ ] Files not in graph produce appropriate guidance (e.g., "rescan to capture these files")

---

## 4. suggest_tests Relevance

### Strategy 1: Graph-Based
- [ ] Test node with `source: test` metadata importing changed node -> score 1.0, strategy "graph"
- [ ] Test node in same module hierarchy as changed node -> score 0.7, strategy "graph"
- [ ] Non-test nodes not suggested even if they import changed nodes

### Strategy 2: Naming Convention
- [ ] Python: `handler.py` -> suggests `test_handler.py`, `handler_test.py`, `tests/test_handler.py`
- [ ] Go: `handler.go` -> suggests `handler_test.go`
- [ ] TypeScript: `handler.ts` -> suggests `handler.test.ts`, `handler.spec.ts`
- [ ] Java: `Handler.java` -> suggests `HandlerTest.java`, `HandlerTests.java`
- [ ] C#: `Handler.cs` -> suggests `HandlerTests.cs`, `HandlerTest.cs`
- [ ] PHP: `Handler.php` -> suggests `HandlerTest.php`
- [ ] Ruby: `handler.rb` -> suggests `handler_spec.rb`, `test_handler.rb`
- [ ] Rust: `handler.rs` -> suggests `tests/handler.rs`
- [ ] JavaScript/JSX: suggests `.test.js`, `.spec.js`, `__tests__/` variants
- [ ] Naming match in graph -> score 1.0; naming match not in graph -> score 0.8

### Strategy 3: Blast Radius
- [ ] Test file 1-hop from changed node -> score 0.5
- [ ] Test file 2+ hops from changed node -> score 0.3
- [ ] Strategy tagged as "blast_radius"

### Deduplication and Ranking
- [ ] Same test found by multiple strategies keeps highest score
- [ ] Results sorted by score descending
- [ ] `max_suggestions` parameter respected (truncation works)
- [ ] No suggestions returns empty list (not error)

### Quick Run Command
- [ ] pytest command generated for Python test suggestions
- [ ] Appropriate commands for other languages (go test, etc.)

---

## 5. file_coupling from Git History

### Co-Change Detection
- [ ] Files always changed together in N commits -> coupling = 1.0
- [ ] Partial co-changes computed correctly: `coupling = co_change_count / max(change_count_a, change_count_b)`
- [ ] Commits with only one file produce no pairs

### Filtering
- [ ] `min_commits` filter: pairs below threshold excluded
- [ ] `min_coupling` filter: pairs below ratio excluded
- [ ] `file_path` filter: only pairs involving that file returned
- [ ] No filter (`file_path=None`): top 20 pairs returned

### Graph Cross-Reference
- [ ] Coupled file pair with existing graph edge -> `in_graph=True`, `edge_type` set
- [ ] Coupled file pair without graph edge -> `in_graph=False`, `edge_type=None`
- [ ] Node mapping uses same suffix matching as `map_files_to_nodes`

### Error Handling
- [ ] Non-git repository raises `NotAGitRepoError`
- [ ] Empty commit history returns empty list
- [ ] Repository with merge-only commits handled correctly

---

## 6. Enhanced codegiraffe_context_for (include_changes parameter)

### Backward Compatibility
- [ ] Default `include_changes=False` produces identical output to v0.8.0
- [ ] All existing `context_for` tests pass without modification
- [ ] No new required parameters added

### Change Awareness (include_changes=True)
- [ ] Changed nodes receive +0.3 score boost
- [ ] Changed nodes tagged with `_recently_changed=True` metadata
- [ ] Blast radius nodes (of changed nodes) receive +0.15 score boost
- [ ] Blast radius nodes tagged with `_in_change_blast_radius=True` metadata
- [ ] Nodes both changed and in blast radius get the higher boost (+0.3, not cumulative)
- [ ] Score ordering reflects boosted values

### Silent Fallback
- [ ] Non-git repository: falls back silently, returns normal context (no error)
- [ ] No uncommitted changes: returns normal context (no boost applied)
- [ ] Git command failure: falls back silently (try/except with pass)
- [ ] No graph initialized: standard error before change logic runs

---

## 7. Backward Compatibility

### Existing Tests
- [ ] All 791 existing tests pass without modification
- [ ] No existing function signatures changed (additive only)
- [ ] No existing imports broken
- [ ] `_detect_git_renames` in `query.py` left unchanged (not migrated to `git_utils.py`)

### Existing Tool Behavior
- [ ] All 25 existing MCP tools return identical results
- [ ] `codegiraffe_context_for` with default parameters unchanged
- [ ] `codegiraffe_blast_radius` unaffected by new query functions
- [ ] `codegiraffe_contracts` / `codegiraffe_validate_contracts` unaffected

---

## 8. Error Handling

### Graceful Failures
- [ ] `codegiraffe_validate_changes` with no graph initialized -> clear error message
- [ ] `codegiraffe_validate_changes` with `auto=True` on non-git repo -> `NotAGitRepoError` message
- [ ] `codegiraffe_validate_changes` with `diff=None, auto=False` -> parameter error message
- [ ] `codegiraffe_validate_changes` with empty diff -> "no changes" message
- [ ] `codegiraffe_suggest_tests` mirrors same error handling as validate_changes
- [ ] `codegiraffe_file_coupling` on non-git repo -> clear error message
- [ ] `codegiraffe_file_coupling` with no pairs above threshold -> guidance message
- [ ] All tools catch generic exceptions and return `f"Error: {exc}"` (no stack traces in MCP output)
- [ ] Git binary not installed -> `GitError` with helpful message (not `FileNotFoundError`)

### Edge Cases
- [ ] Diff with only binary files -> validation report acknowledges binary files, no hunk analysis
- [ ] Changed files that map to zero graph nodes -> report notes files not in graph
- [ ] Graph with no edges -> blast radius is empty, validation still completes
- [ ] Extremely large diff (100+ files) -> completes within timeout
- [ ] Unicode file paths in diffs handled correctly

---

## 9. Documentation Updates

### CLAUDE.md
- [ ] Version updated to `0.10.0`
- [ ] Tool count updated to ~28
- [ ] Test count updated to 890+
- [ ] `diff_parser.py` and `git_utils.py` added to project structure
- [ ] v0.10.0 entry added to Recent Changes section
- [ ] New MCP tool signatures documented

### README.md
- [ ] Change impact validation tools listed in tool table
- [ ] v0.10.0 feature description added
- [ ] Version references updated throughout
- [ ] New tool parameters documented

---

## 10. Tool Count and Architecture

### MCP Tools (28 total)
- [ ] 25 existing tools present and functional
- [ ] `codegiraffe_validate_changes` registered as MCP tool with `@mcp.tool()`
- [ ] `codegiraffe_suggest_tests` registered as MCP tool with `@mcp.tool()`
- [ ] `codegiraffe_file_coupling` registered as MCP tool with `@mcp.tool()`
- [ ] `codegiraffe_context_for` enhanced with `include_changes` parameter (not a new tool, still 1 tool)
- [ ] Total tool count: 28

### New Source Modules
- [ ] `src/codegiraffe/diff_parser.py` exists with 5 models + 2 functions
- [ ] `src/codegiraffe/git_utils.py` exists with 2 exceptions + 4 functions
- [ ] Both modules importable from `codegiraffe` package

### Modified Source Files
- [ ] `src/codegiraffe/query.py` has 4 new functions (additive, no existing functions changed)
- [ ] `src/codegiraffe/server.py` has 3 new tools + 3 format helpers + 1 enhanced tool
- [ ] `pyproject.toml` version is `"0.10.0"`

### Test Files (8 new)
- [ ] `tests/test_diff_parser.py` -- 22 tests
- [ ] `tests/test_git_utils.py` -- 13 tests
- [ ] `tests/test_validate_changes.py` -- 14 tests
- [ ] `tests/test_suggest_tests.py` -- 11 tests
- [ ] `tests/test_file_coupling.py` -- 11 tests
- [ ] `tests/test_server_validate_changes.py` -- 13 tests
- [ ] `tests/test_context_for_changes.py` -- 6 tests
- [ ] `tests/test_format_reports.py` -- 14 tests
- [ ] Total new tests: 104+
- [ ] Total test count: 895+

---

## Final Verification

- [ ] `source .venv/bin/activate && python -m pytest tests/ -v` passes with 0 failures
- [ ] No new required pip dependencies introduced
- [ ] All new code follows existing patterns (Pydantic v2, `@mcp.tool()`, subprocess with timeout)
- [ ] No secrets or credentials in committed code
- [ ] Feature branch created, clean commit history, ready for PR

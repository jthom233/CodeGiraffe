# Task List: Code Giraffe v0.10.0 -- Change Impact Validation

**Scope:** 7 phases, 2 new source modules, 5 modified source files, 8 new test files, 3 new MCP tools + 1 enhanced tool (~28 total), 104 new tests (890+ total).

---

## Phase 1: Data Models (Serial -- Must Go First)

All subsequent phases reference these Pydantic models. No dependencies.

- [ ] **P1-1** Create `src/codegiraffe/diff_parser.py` with `DiffHunk` model (fields: `old_start`, `old_count`, `new_start`, `new_count`, `header`). Follow Pydantic v2 BaseModel pattern from `graph.py`.
- [ ] **P1-2** Add `DiffFile` model to `diff_parser.py` (fields: `path`, `old_path`, `status`, `hunks`, `is_binary`, `additions`, `deletions`). Use `Field(default_factory=list)` for `hunks`.
- [ ] **P1-3** Add `TestSuggestion` model to `diff_parser.py` (fields: `file_path`, `score`, `reason`, `strategy`).
- [ ] **P1-4** Add `CouplingPair` model to `diff_parser.py` (fields: `file_a`, `file_b`, `co_change_count`, `change_count_a`, `change_count_b`, `coupling`, `in_graph`, `edge_type`).
- [ ] **P1-5** Add `ChangeReport` model to `diff_parser.py` (fields: `changed_files`, `changed_nodes`, `covered_nodes`, `uncovered_nodes`, `contract_violations`, `recommendations`, `total_blast_radius`).
- [ ] **P1-6** Create `tests/test_diff_parser.py` with 6 model tests: `test_diff_hunk_defaults`, `test_diff_file_defaults`, `test_diff_file_rename_has_old_path`, `test_change_report_structure`, `test_test_suggestion_model`, `test_coupling_pair_model`.
- [ ] **P1-7** Run tests -- confirm 6 new tests pass, all 791 existing tests still pass.

---

## Phase 2: Diff Parser (Depends on Phase 1)

Pure string-to-model parsing. Zero dependencies on graph or git.

- [ ] **P2-1** Add regex constants to `diff_parser.py`: `_DIFF_HEADER_RE`, `_FILE_OLD_RE`, `_FILE_NEW_RE`, `_HUNK_RE`, `_RENAME_FROM_RE`, `_RENAME_TO_RE`, `_BINARY_RE`.
- [ ] **P2-2** Implement `parse_diff(raw_diff: str) -> list[DiffFile]` in `diff_parser.py`. Split on `^diff --git` lines, extract paths from `--- a/` and `+++ b/`, determine status (added/deleted/renamed/modified), detect binary files, parse `@@` hunk markers, count `+`/`-` lines.
- [ ] **P2-3** Implement `extract_symbol_hints(hunks: list[DiffHunk]) -> list[str]` in `diff_parser.py`. Parse hunk `header` text for Python `def`/`class` names and generic leading identifiers. Return deduplicated list.
- [ ] **P2-4** Add `TestParseDiff` test class to `tests/test_diff_parser.py` with 12 tests: `test_parse_single_modified_file`, `test_parse_multiple_files`, `test_parse_new_file`, `test_parse_deleted_file`, `test_parse_renamed_file`, `test_parse_binary_file`, `test_parse_hunks`, `test_parse_hunk_header_context`, `test_parse_addition_deletion_counts`, `test_parse_empty_diff`, `test_parse_diff_with_no_newline_marker`, `test_parse_path_with_spaces`.
- [ ] **P2-5** Add `TestExtractSymbolHints` test class to `tests/test_diff_parser.py` with 4 tests: `test_extract_python_function`, `test_extract_python_class`, `test_extract_empty_header`, `test_extract_deduplication`.
- [ ] **P2-6** Run tests -- confirm 22 total new tests in `test_diff_parser.py` pass.

---

## Phase 3: Git Utilities (Parallel with Phase 2)

Thin subprocess wrappers for git CLI commands. Independent of graph.

- [ ] **P3-1** Create `src/codegiraffe/git_utils.py` with module docstring, imports (`subprocess`), and exception classes `GitError` and `NotAGitRepoError(GitError)`.
- [ ] **P3-2** Implement `is_git_repo(project_path: str) -> bool` in `git_utils.py`. Run `git rev-parse --git-dir` with `capture_output=True`, return `True` if returncode == 0.
- [ ] **P3-3** Implement `get_uncommitted_diff(project_path: str) -> str` in `git_utils.py`. Call `is_git_repo()` first (raise `NotAGitRepoError` if false), run `git diff HEAD`, fall back to `git diff --cached` for initial-commit scenario, return stdout.
- [ ] **P3-4** Implement `get_changed_files(project_path: str) -> list[str]` in `git_utils.py`. Run `git diff HEAD --name-only`, return file paths. Return empty list on non-git repos (no exception).
- [ ] **P3-5** Implement `get_commit_file_history(project_path: str, depth: int = 100) -> list[list[str]]` in `git_utils.py`. Run `git log --name-only --pretty=format:"COMMIT:%H" -n {depth}`, split on `COMMIT:` markers, extract file paths per commit.
- [ ] **P3-6** Create `tests/test_git_utils.py` with `TestIsGitRepo` (2 tests: `test_is_git_repo_true`, `test_is_git_repo_false`).
- [ ] **P3-7** Add `TestGetUncommittedDiff` to `tests/test_git_utils.py` (5 tests: `test_get_uncommitted_diff_with_changes`, `test_get_uncommitted_diff_no_changes`, `test_get_uncommitted_diff_not_git_repo`, `test_get_uncommitted_diff_staged_changes`, `test_get_uncommitted_diff_new_repo_no_commits`).
- [ ] **P3-8** Add `TestGetChangedFiles` to `tests/test_git_utils.py` (3 tests: `test_get_changed_files_returns_paths`, `test_get_changed_files_empty_when_clean`, `test_get_changed_files_not_git_repo`).
- [ ] **P3-9** Add `TestGetCommitFileHistory` to `tests/test_git_utils.py` (4 tests: `test_get_commit_file_history`, `test_get_commit_file_history_depth_limit`, `test_get_commit_file_history_not_git_repo`, `test_get_commit_file_history_empty_repo`).
- [ ] **P3-10** Run tests -- confirm 13 new tests in `test_git_utils.py` pass.

---

## Phase 4: Query Engine -- Core Analysis Functions (Depends on Phases 2 and 3)

Core analysis logic added to `query.py`. Composes diff_parser, git_utils, and existing graph functions.

- [ ] **P4-1** Add import block to `src/codegiraffe/query.py` for `diff_parser` types (`ChangeReport`, `CouplingPair`, `DiffFile`, `TestSuggestion`, `extract_symbol_hints`, `parse_diff`) and `git_utils` functions (`GitError`, `NotAGitRepoError`, `get_changed_files`, `get_commit_file_history`, `get_uncommitted_diff`, `is_git_repo`).
- [ ] **P4-2** Implement `map_files_to_nodes(graph: ArchGraph, file_paths: list[str]) -> dict[str, list[str]]` in `query.py`. Build index of node file_path/ID values, match input paths using suffix matching and module ID matching. Insert after `_score_node`.
- [ ] **P4-3** Implement `validate_changes(graph: ArchGraph, diff_files: list[DiffFile]) -> ChangeReport` in `query.py`. Map files to nodes, compute combined blast radius for each changed node, partition into covered/uncovered impact, check contract violations (producers changed without consumers), generate recommendations.
- [ ] **P4-4** Define `_TEST_PATTERNS` dict in `query.py` mapping file extensions to test file naming patterns for 11 extensions (`.py`, `.go`, `.ts`, `.tsx`, `.js`, `.jsx`, `.rs`, `.java`, `.cs`, `.php`, `.rb`).
- [ ] **P4-5** Implement `suggest_tests(graph: ArchGraph, diff_files: list[DiffFile], max_suggestions: int = 20) -> list[TestSuggestion]` in `query.py`. Three strategies: (1) graph-based -- test nodes with `source: test` metadata importing changed nodes; (2) naming convention -- language-specific test file patterns; (3) blast radius -- test files in transitive dependency set. Deduplicate, sort by score descending, truncate to max.
- [ ] **P4-6** Implement `file_coupling(graph: ArchGraph, project_path: str, file_path: str | None = None, depth: int = 100, min_commits: int = 3, min_coupling: float = 0.1) -> list[CouplingPair]` in `query.py`. Mine git history, build co-change matrix, compute coupling ratios, filter thresholds, cross-reference with graph edges, sort by coupling descending.
- [ ] **P4-7** Create `tests/test_validate_changes.py` with `TestMapFilesToNodes` (6 tests: exact match, suffix match, module ID match, no match, multiple nodes per file, empty graph).
- [ ] **P4-8** Add `TestValidateChanges` to `tests/test_validate_changes.py` (8 tests: uncovered nodes detected, covered node not flagged, contract violation, no contract violation when consumer changed, empty diff, files not in graph, recommendations include edge type, multi-file combined blast radius).
- [ ] **P4-9** Create `tests/test_suggest_tests.py` with `TestSuggestTests` (11 tests: graph-based direct import, graph-based sibling, naming conventions for Python/Go/TypeScript/Java, blast radius transitive, deduplication, max suggestions limit, no tests found, quick run command formatting).
- [ ] **P4-10** Create `tests/test_file_coupling.py` with `TestFileCoupling` (11 tests: basic coupling, partial coupling, min_commits filter, min_coupling filter, file_path filter, cross-reference in graph, cross-reference not in graph, top 20 limit, not git repo, empty history, single file commits).
- [ ] **P4-11** Run tests -- confirm 36 new tests across 3 test files pass, all existing tests still pass.

---

## Phase 5: MCP Tool Wrappers (Depends on Phase 4)

Thin wrappers in server.py that load graph, call query functions, format as markdown.

- [ ] **P5-1** Add imports to `src/codegiraffe/server.py`: `file_coupling`, `map_files_to_nodes`, `suggest_tests`, `validate_changes` from `query.py`; `parse_diff` from `diff_parser`; `get_changed_files`, `get_uncommitted_diff`, `is_git_repo`, `NotAGitRepoError` from `git_utils`.
- [ ] **P5-2** Add section header comment `# Change impact validation tools (v0.10.0)` after the cross-system contract tools section in `server.py`.
- [ ] **P5-3** Implement `codegiraffe_validate_changes(project_path, diff=None, auto=True)` MCP tool in `server.py`. Get diff (auto from git or explicit), parse, call `validate_changes()`, format report. Handle `NotAGitRepoError` and empty diff cases.
- [ ] **P5-4** Implement `_format_validation_report(report: ChangeReport) -> str` helper in `server.py`. Markdown sections: Changes Detected, Impact Analysis, Covered Impact, Potentially Missing Changes, Contract Violations, Recommendations.
- [ ] **P5-5** Implement `codegiraffe_suggest_tests(project_path, diff=None, auto=True, max_suggestions=20)` MCP tool in `server.py`. Same diff-fetching pattern, call `suggest_tests()`, format suggestions.
- [ ] **P5-6** Implement `_format_test_suggestions(suggestions, diff_files) -> str` helper in `server.py`. Markdown sections: High/Medium/Low Relevance, Quick run command.
- [ ] **P5-7** Implement `codegiraffe_file_coupling(project_path, file_path=None, depth=100, min_commits=3, min_coupling=0.1)` MCP tool in `server.py`. Call `file_coupling()`, format report.
- [ ] **P5-8** Implement `_format_coupling_report(pairs, file_path, depth) -> str` helper in `server.py`. Markdown table with columns: Coupled File, Co-Changes, Coupling, In Graph?. Implicit coupling section.
- [ ] **P5-9** Enhance `codegiraffe_context_for` in `server.py`: add `include_changes: bool = False` parameter. When True, read changed files via `get_changed_files()`, map to nodes, compute blast radius, boost scores (+0.3 for changed nodes, +0.15 for blast radius nodes), add `_recently_changed`/`_in_change_blast_radius` metadata. Wrap in try/except for silent fallback.
- [ ] **P5-10** Create `tests/test_server_validate_changes.py` with `TestValidateChangesTool` (6 tests: auto detects diff, explicit diff, no diff no auto error, not git repo error, no graph error, no uncommitted changes message).
- [ ] **P5-11** Add `TestSuggestTestsTool` to `tests/test_server_validate_changes.py` (3 tests: returns markdown, quick run command, no tests found message).
- [ ] **P5-12** Add `TestFileCouplingTool` to `tests/test_server_validate_changes.py` (4 tests: returns table, with file_path, not git repo, no pairs above threshold).
- [ ] **P5-13** Create `tests/test_context_for_changes.py` with `TestContextForChanges` (6 tests: include_changes=False unchanged behavior, boosts changed nodes, boosts blast radius, silent fallback on non-git, no uncommitted changes, score ordering).
- [ ] **P5-14** Run tests -- confirm 19 new tests in `test_server_validate_changes.py` and 6 in `test_context_for_changes.py` pass.

---

## Phase 6: Format Helpers + Edge Cases (Parallel with Phase 5)

Dedicated tests for markdown formatting functions and edge case coverage.

- [ ] **P6-1** Create `tests/test_format_reports.py` with `TestFormatValidationReport` (5 tests: empty report, uncovered nodes, contract violations, numbered recommendations, changed files list with status indicators).
- [ ] **P6-2** Add `TestFormatTestSuggestions` to `tests/test_format_reports.py` (5 tests: high relevance section, medium relevance section, low relevance section, quick run command, empty suggestions).
- [ ] **P6-3** Add `TestFormatCouplingReport` to `tests/test_format_reports.py` (4 tests: table structure, implicit coupling section, no pairs message, file_path header).
- [ ] **P6-4** Run tests -- confirm 14 new tests in `test_format_reports.py` pass.

---

## Phase 7: Polish (Last -- Depends on Phases 5 and 6)

Version bump, documentation updates, final verification. No new features.

- [ ] **P7-1** Bump `version` in `pyproject.toml` from `"0.8.0"` to `"0.10.0"`.
- [ ] **P7-2** Update `CLAUDE.md`: version to `0.10.0`, tool count to ~28, test count to 890+, add `diff_parser.py` and `git_utils.py` to project structure, add v0.10.0 Recent Changes entry, add new MCP tool descriptions.
- [ ] **P7-3** Update `README.md`: add change impact validation tools to tool list, add v0.10.0 feature description, update version references.
- [ ] **P7-4** Run full test suite: all 791 existing tests pass unchanged + 104 new tests pass = 895+ total.
- [ ] **P7-5** Verify no new required dependencies added (only stdlib `subprocess` and existing Pydantic).

---

## Summary

| Phase | Tasks | New Tests | Key Files |
|-------|-------|-----------|-----------|
| 1. Data Models | 7 | 6 | `diff_parser.py` (create), `test_diff_parser.py` (create) |
| 2. Diff Parser | 6 | 16 | `diff_parser.py` (modify), `test_diff_parser.py` (extend) |
| 3. Git Utilities | 10 | 13 | `git_utils.py` (create), `test_git_utils.py` (create) |
| 4. Query Engine | 11 | 36 | `query.py` (modify), 3 new test files |
| 5. MCP Tools | 14 | 25 | `server.py` (modify), 2 new test files |
| 6. Format Helpers | 4 | 14 | `test_format_reports.py` (create) |
| 7. Polish | 5 | 0 | `pyproject.toml`, `CLAUDE.md`, `README.md` |
| **Total** | **57** | **110** | **7 source + 8 test files** |

### Dependency Graph

```
Phase 1 (Data Models)
  |
  +---> Phase 2 (Diff Parser) -----+
  |                                 |
  +---> Phase 3 (Git Utilities) ----+--> Phase 4 (Query Engine) --> Phase 5 (MCP Tools) --+
                                    |                                                      |
                                    +--> Phase 6 (Format Helpers) -------------------------+--> Phase 7 (Polish)
```

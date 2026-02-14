# Specification

## Requirements

## Code Giraffe v0.10.0 — Change Impact Validation

### Overview

v0.10.0 transforms CodeGiraffe from a passive architecture observer into an active change validation layer. Three new MCP tools and an enhancement to the existing `codegiraffe_context_for` tool give AI agents the ability to analyze uncommitted changes against the architecture graph, detect incomplete modifications, identify missing test coverage, and surface implicit file coupling from git history — all before code is committed.

After this release, CodeGiraffe will expose ~30 MCP tools, support 9 languages, and have 890+ tests.

### Motivation

The number one failure mode in AI-assisted coding is **incomplete changes**. An AI agent modifies a handler but forgets to update the consumer. It changes an interface but misses an implementation. It renames a field but does not update the config. These are not bugs of logic — they are bugs of awareness. The agent simply did not know the full scope of what needed to change.

Today, these failures are discovered only after the fact: test failures (if tests exist), runtime errors, or manual review. By that point the agent has moved on and the fix requires re-loading context.

CodeGiraffe already has all the information needed to prevent this. The architecture graph captures module containment, import edges, implementation relationships, call-graph edges (v0.9.0), and cross-system contracts (v0.8.0). The blast radius tool (v0.7.0) can compute downstream impact for any node. The missing piece is connecting this intelligence to the *actual changes being made* — bridging the gap between "what the graph knows" and "what the diff shows."

v0.10.0 closes that gap. It gives agents a pre-commit validation step: "Here is what I changed. What did I miss?" This is the architectural equivalent of a type checker — it cannot catch every problem, but it catches the structural ones that are otherwise invisible.

### Features

#### Feature 1: New MCP Tool — `codegiraffe_validate_changes`

**Purpose:** Analyze uncommitted (or arbitrary) changes against the architecture graph to detect incomplete modifications, missed contract updates, and impacted nodes that were not touched.

**Signature:**
```python
codegiraffe_validate_changes(
    project_path: str,
    diff: str | None = None,
    auto: bool = True,
) -> str
```

**Parameters:**
- `project_path` (required): Path to the project with an initialized CodeGiraffe graph.
- `diff` (optional): Raw unified diff string to analyze. When provided, this diff is used instead of reading from git.
- `auto` (optional, default `True`): When `True` and `diff` is not provided, automatically reads uncommitted changes by running `git diff HEAD` (staged + unstaged) in the project directory. When both `diff` is `None` and `auto` is `False`, returns an error.

**Process:**
1. **Parse the diff** to extract:
   - Changed file paths (added, modified, deleted)
   - Changed symbol names where determinable (function/class names from diff hunks using `@@` markers)
2. **Map changed files to graph nodes.** For each changed file path, find all graph nodes whose `file` metadata or node ID matches. This includes module nodes (which have `file` metadata from the scanner), services, endpoints, and any other nodes associated with that file.
3. **Compute combined blast radius.** For each changed node, call the existing `compute_blast_radius()` function. Merge all downstream impact sets into a single combined impact set, deduplicating nodes.
4. **Cross-reference with changes.** Compare the combined blast radius against the set of files/nodes actually modified in the diff. Partition impacted nodes into two groups:
   - **Covered:** nodes in the blast radius that were also modified in the diff.
   - **Uncovered:** nodes in the blast radius that were NOT modified in the diff.
5. **Check contract integrity.** For each changed node that is a contract producer (has `produces` edges to contract nodes), verify whether the contract's consumers also appear in the diff. If a producer was changed but its consumers were not, flag this as a potential contract violation.
6. **Generate recommendations.** For each uncovered node, produce a specific, actionable suggestion explaining why it may need updating and what relationship connects it to the changed code.

**Output:** Markdown report with the following sections:
```
## Change Impact Validation

### Changes Detected
- `module:src/foo/handler.py` (modified) — 3 hunks, ~25 lines changed
- `module:src/foo/models.py` (modified) — 1 hunk, ~8 lines changed

### Impact Analysis
**Total blast radius:** 12 nodes across 8 files
- 4 direct dependencies
- 5 transitive dependencies (2-3 hops)
- 3 indirect dependencies (4+ hops)

### Covered Impact (already modified)
- `module:src/foo/models.py` — direct dependency via `imports` edge (covered in diff)

### Potentially Missing Changes
- `module:src/bar/consumer.py` — imports `src/foo/handler.py`, 1 hop away
- `endpoint:/api/users` — contained in `src/foo/handler.py`, may need route update
- `module:tests/test_handler.py` — test file for changed module

### Contract Violations
- **contract:api/users** — producer `endpoint:/api/users` was modified but consumer
  `external_api:user-service-client` in `src/bar/client.py` was not updated

### Recommendations
1. Review `src/bar/consumer.py` — it directly imports the changed handler module
2. Verify `endpoint:/api/users` route still matches client expectations
3. Run tests in `tests/test_handler.py` — direct test coverage for changed code
4. Check `src/bar/client.py` — consumes the `api/users` contract whose producer changed
```

**Error handling:**
- If the graph does not exist for `project_path`, return a clear error directing the user to run `codegiraffe_init` first.
- If `auto=True` but the project is not a git repository, return an error explaining that `diff` must be provided explicitly.
- If there are no uncommitted changes and `auto=True`, return a message: "No uncommitted changes detected."
- If changed files do not map to any graph nodes, return the list of changed files with a note that they are not tracked in the architecture graph (the graph may need a resync).

---

#### Feature 2: New MCP Tool — `codegiraffe_suggest_tests`

**Purpose:** Given a set of changes (from diff or auto-detected), identify and rank test files that should be run to validate those changes.

**Signature:**
```python
codegiraffe_suggest_tests(
    project_path: str,
    diff: str | None = None,
    auto: bool = True,
    max_suggestions: int = 20,
) -> str
```

**Parameters:**
- `project_path` (required): Path to the project with an initialized CodeGiraffe graph.
- `diff` (optional): Raw unified diff string. Behavior same as `codegiraffe_validate_changes`.
- `auto` (optional, default `True`): Behavior same as `codegiraffe_validate_changes`.
- `max_suggestions` (optional, default `20`): Maximum number of test files to return.

**Process:**
1. **Parse diff** to extract changed files/symbols (reuse the same diff parser from Feature 1).
2. **Map to graph nodes** (reuse the same mapping logic from Feature 1).
3. **Identify test files** through multiple strategies, in priority order:
   - **Graph-based (primary):** Find nodes with `source: test` metadata (test files are tagged by the scanner when `include_tests=True`). Check if any test node has an `imports` edge pointing to a changed node, or if a test node is `contains`-ed in the same module hierarchy.
   - **Naming convention (secondary):** For each changed file, look for test file counterparts using language-specific patterns:
     - Python: `test_{name}.py`, `{name}_test.py`, `tests/test_{name}.py`
     - Go: `{name}_test.go` (same directory)
     - TypeScript/JavaScript: `{name}.test.ts`, `{name}.spec.ts`, `__tests__/{name}.ts`
     - Rust: check for `#[cfg(test)]` modules in the same file, or `tests/{name}.rs`
     - Java: `{Name}Test.java`, `{Name}Tests.java` in corresponding test directory
     - C#: `{Name}Tests.cs`, `{Name}Test.cs`
     - PHP: `{Name}Test.php`
     - Ruby: `{name}_spec.rb`, `test_{name}.rb`
   - **Blast radius (tertiary):** For each changed node, check if any test file imports or depends on nodes in the blast radius (transitive test coverage).
4. **Score and rank** test files:
   - **Direct test** (imports or names match the changed file): relevance score 1.0
   - **Sibling test** (tests a module in the same package/directory as the changed file): relevance score 0.7
   - **Transitive test** (tests a node that depends on the changed node): relevance score 0.3-0.5, scaled by distance
5. **Deduplicate and sort** by relevance score descending.

**Output:** Markdown report:
```
## Suggested Tests

**Changes analyzed:** 3 files modified

### High Relevance (direct coverage)
1. `tests/test_handler.py` (score: 1.0) — directly tests `src/foo/handler.py`
2. `tests/test_models.py` (score: 1.0) — directly tests `src/foo/models.py`

### Medium Relevance (related coverage)
3. `tests/test_api_integration.py` (score: 0.7) — tests sibling module in `src/foo/`
4. `tests/test_consumer.py` (score: 0.5) — tests `src/bar/consumer.py` which imports changed module

### Low Relevance (transitive coverage)
5. `tests/test_reporting.py` (score: 0.3) — tests node 3 hops from changed code

**Quick run command:**
pytest tests/test_handler.py tests/test_models.py tests/test_api_integration.py tests/test_consumer.py
```

**Error handling:**
- Same git/graph existence checks as `codegiraffe_validate_changes`.
- If no test files are found, return a message suggesting the user run a rescan with `include_tests=True` and explaining the naming conventions checked.

---

#### Feature 3: New MCP Tool — `codegiraffe_file_coupling`

**Purpose:** Mine git commit history to discover implicit coupling between files — files that are frequently changed together in the same commit. This captures temporal coupling that no static analysis can detect: files that have no import/dependency relationship but are consistently co-modified because of shared business logic, coordinated configuration, or other implicit dependencies.

**Signature:**
```python
codegiraffe_file_coupling(
    project_path: str,
    file_path: str | None = None,
    depth: int = 100,
    min_commits: int = 3,
    min_coupling: float = 0.1,
) -> str
```

**Parameters:**
- `project_path` (required): Path to the git repository.
- `file_path` (optional): If provided, return files most frequently co-changed with this specific file. If `None`, return the top co-change pairs across the entire project.
- `depth` (optional, default `100`): Number of recent git commits to analyze. Higher values give more accurate coupling data but take longer.
- `min_commits` (optional, default `3`): Minimum number of co-change commits for a pair to be reported. Filters out coincidental co-changes.
- `min_coupling` (optional, default `0.1`): Minimum coupling ratio (co-changes / max(changes_A, changes_B)) for a pair to be reported. Filters out weakly coupled pairs.

**Process:**
1. **Mine git log.** Run `git log --name-only --pretty=format:"COMMIT:%H" -n {depth}` in the project directory to get the list of changed files per commit.
2. **Build co-change matrix.** For each commit, record every pair of files that were changed together. Track:
   - `co_change_count`: number of commits where both files appear
   - `change_count_a`: total commits touching file A
   - `change_count_b`: total commits touching file B
3. **Compute coupling ratio** for each pair:
   - `coupling = co_change_count / max(change_count_a, change_count_b)`
   - This normalizes for files that change very frequently (a file changed in every commit would have low coupling with everything unless the pairing is also frequent).
4. **Filter** pairs below `min_commits` and `min_coupling` thresholds.
5. **If `file_path` is provided:** filter to only pairs involving that file, sort by coupling descending.
6. **If `file_path` is not provided:** return top 20 pairs across the project, sorted by coupling descending.
7. **Cross-reference with graph.** For each reported pair, check whether the architecture graph already has an edge between the corresponding nodes. Flag pairs that are coupled in git history but have NO graph edge — these represent implicit dependencies the graph does not capture.

**Output:** Markdown report:
```
## File Coupling Analysis

**Commits analyzed:** 100
**Pairs above threshold:** 14

### Coupled to `src/foo/handler.py` (if file_path provided)
| Coupled File | Co-Changes | Coupling | In Graph? |
|---|---|---|---|
| `src/foo/models.py` | 28/35 | 0.80 | Yes (imports) |
| `src/foo/routes.py` | 22/35 | 0.63 | Yes (contains) |
| `src/bar/consumer.py` | 15/35 | 0.43 | Yes (calls) |
| `config/settings.yaml` | 8/35 | 0.23 | No |
| `docs/api.md` | 6/35 | 0.17 | No |

### Implicit Coupling (not in graph)
These file pairs are frequently co-changed but have no architectural relationship
in the graph. Consider adding explicit edges or investigating the coupling:
- `config/settings.yaml` <-> `src/foo/handler.py` (8 co-changes, 0.23 coupling)
- `docs/api.md` <-> `src/foo/handler.py` (6 co-changes, 0.17 coupling)
```

**Error handling:**
- If the project is not a git repository, return a clear error.
- If git history has fewer commits than `depth`, use all available commits and note this in the output.
- If no file pairs meet the thresholds, return a message explaining the thresholds and suggesting lowering them.

---

#### Feature 4: Enhanced `codegiraffe_context_for` — Change Awareness

**Purpose:** When an agent asks "what's relevant to this task?", factor in the current state of uncommitted changes so that recently modified and blast-radius-adjacent nodes receive boosted relevance.

**Enhancement to existing tool signature:**
```python
codegiraffe_context_for(
    project_path: str,
    task: str,
    max_nodes: int = 20,
    use_embeddings: bool = True,
    include_impact: bool = False,
    include_changes: bool = False,  # NEW parameter
) -> str
```

**New parameter:**
- `include_changes` (optional, default `False`): When `True`, reads uncommitted git changes via `git diff HEAD` and uses them to boost relevance scores.

**Process (when `include_changes=True`):**
1. Run `git diff HEAD --name-only` in the project directory to get the list of modified files.
2. Map modified files to graph nodes (same mapping logic as Feature 1).
3. Compute the blast radius of all changed nodes (combined, deduplicated).
4. Apply score boosting during the relevance scoring phase:
   - Nodes that were **directly changed**: boost score by +0.3
   - Nodes in the **blast radius** of changed nodes: boost score by +0.15
5. Add metadata to boosted nodes:
   - `_recently_changed: true` for directly modified nodes
   - `_in_change_blast_radius: true` for nodes in the blast radius of changes
6. Return the subgraph as normal (JSON), with the augmented scores and metadata.

**Backward compatibility:** When `include_changes=False` (the default), behavior is identical to the current implementation. The new parameter is purely additive.

**Error handling:**
- If the project is not a git repository and `include_changes=True`, silently fall back to `include_changes=False` behavior (do not error — this is a "nice to have" enrichment, not a required input).
- If there are no uncommitted changes, proceed with normal scoring (no boost applied).

### Technical Approach

#### Diff Parsing (new module: `diff_parser.py`)
Create a new module `src/codegiraffe/diff_parser.py` responsible for parsing unified diffs:

- **Input:** Raw unified diff string (output of `git diff`).
- **Output:** Structured data: list of `DiffFile` objects, each containing:
  - `path`: file path relative to the repository root
  - `status`: "added", "modified", or "deleted"
  - `hunks`: list of `DiffHunk` objects with start line, end line, and header text (which often contains the function/class name from the `@@` marker)
- Use `dataclass` or Pydantic model for `DiffFile` and `DiffHunk`.
- Parse the `--- a/path` and `+++ b/path` lines for file paths.
- Parse `@@ -start,count +start,count @@ context` lines for hunk info.
- Do not depend on external diff parsing libraries — keep it pure Python with regex parsing. The format is well-defined and stable.
- Handle edge cases: binary files (skip), renamed files (track both old and new paths), new files (`--- /dev/null`), deleted files (`+++ /dev/null`).

#### Node Mapping (in `query.py`)
Add a function `map_files_to_nodes()` to `query.py`:

- **Input:** `graph: ArchGraph`, `file_paths: list[str]`
- **Output:** `dict[str, list[str]]` mapping each file path to a list of matching node IDs.
- **Strategy:** Iterate all graph nodes, check if the node's `file` metadata matches any of the input paths. Also check for module nodes whose ID contains the file path (e.g., `module:src/foo/handler.py`). Use suffix matching to handle absolute vs. relative path differences.

#### Git Integration (in `query.py` or new `git_utils.py`)
Add helper functions for git operations:

- `get_uncommitted_diff(project_path: str) -> str`: Runs `git diff HEAD` and returns the raw diff string. Raises `ValueError` if not a git repository.
- `get_commit_file_history(project_path: str, depth: int) -> list[list[str]]`: Runs `git log --name-only` and returns a list of commits, where each commit is a list of changed file paths.
- All git commands use `subprocess.run()` with `capture_output=True`, `text=True`, `cwd=project_path`.
- Use `check=True` to propagate git errors as exceptions.

#### Shared Infrastructure
Features 1, 2, and 4 share common logic:
- Diff parsing (Feature 1, 2, 4)
- File-to-node mapping (Feature 1, 2, 4)
- Blast radius computation (Feature 1, 4 — reuse existing `compute_blast_radius()`)
- Git command execution (Feature 1, 2, 3, 4)

This shared logic should be factored into reusable functions in `diff_parser.py` and `query.py` (or a dedicated `git_utils.py`) to avoid duplication.

#### MCP Tool Registration (in `server.py`)
Add three new `@mcp.tool()` functions to `server.py`:
- `codegiraffe_validate_changes` — calls diff parser, node mapper, blast radius, and report generator
- `codegiraffe_suggest_tests` — calls diff parser, node mapper, test finder, and report generator
- `codegiraffe_file_coupling` — calls git log miner, co-change analyzer, and report generator

Extend the existing `codegiraffe_context_for` with the `include_changes` parameter.

Follow existing patterns: each tool loads the graph via `_ensure_graph()`, calls query functions, and returns markdown strings. Error handling follows the established try/except pattern with descriptive error messages.

#### New Files
- `src/codegiraffe/diff_parser.py` — Diff parsing models and functions
- `src/codegiraffe/git_utils.py` — Git command helpers (log mining, diff reading)
- `tests/test_diff_parser.py` — Unit tests for diff parsing
- `tests/test_git_utils.py` — Unit tests for git helpers
- `tests/test_validate_changes.py` — Unit and integration tests for `codegiraffe_validate_changes`
- `tests/test_suggest_tests.py` — Unit and integration tests for `codegiraffe_suggest_tests`
- `tests/test_file_coupling.py` — Unit and integration tests for `codegiraffe_file_coupling`
- `tests/test_context_for_changes.py` — Tests for the `include_changes` enhancement

#### Modified Files
- `src/codegiraffe/server.py` — Add 3 new tool definitions, extend `codegiraffe_context_for`
- `src/codegiraffe/query.py` — Add `map_files_to_nodes()`, test suggestion logic, file coupling analysis
- `pyproject.toml` — Version bump to 0.10.0

### Acceptance Criteria

- [ ] `codegiraffe_validate_changes` with `auto=True` detects uncommitted changes and maps them to graph nodes
- [ ] `codegiraffe_validate_changes` with explicit `diff` parameter parses and analyzes the provided diff
- [ ] `codegiraffe_validate_changes` correctly identifies impacted nodes NOT touched in the diff as "potentially missing changes"
- [ ] `codegiraffe_validate_changes` detects contract violations when a producer is changed but consumers are not
- [ ] `codegiraffe_validate_changes` returns actionable recommendations with specific file paths and relationship explanations
- [ ] `codegiraffe_validate_changes` handles edge cases: empty diff, non-git project, no graph, files not in graph
- [ ] `codegiraffe_suggest_tests` returns test files ranked by relevance (direct > sibling > transitive)
- [ ] `codegiraffe_suggest_tests` uses graph-based test discovery (imports, contains edges, `source: test` metadata)
- [ ] `codegiraffe_suggest_tests` falls back to naming convention matching when graph data is insufficient
- [ ] `codegiraffe_suggest_tests` generates a quick-run command for the suggested tests
- [ ] `codegiraffe_file_coupling` mines git history and returns co-change pairs with coupling ratios
- [ ] `codegiraffe_file_coupling` with `file_path` returns files coupled to that specific file
- [ ] `codegiraffe_file_coupling` without `file_path` returns top coupled pairs across the project
- [ ] `codegiraffe_file_coupling` cross-references coupling data with graph edges and flags implicit coupling
- [ ] `codegiraffe_file_coupling` handles edge cases: shallow history, non-git project, no co-changes above threshold
- [ ] `codegiraffe_context_for` with `include_changes=True` boosts scores for recently changed and blast-radius-adjacent nodes
- [ ] `codegiraffe_context_for` with `include_changes=False` (default) behaves identically to current implementation
- [ ] Diff parser correctly handles: additions, modifications, deletions, renames, binary files, and multi-file diffs
- [ ] All existing tests pass unchanged (850+ tests from v0.9.0)
- [ ] 40+ new tests covering all four features
- [ ] Total test count reaches 890+

### Non-Goals

- **Running tests automatically.** `codegiraffe_suggest_tests` only identifies which tests to run — it does not execute them. Test execution is the agent's or CI's responsibility.
- **Auto-fixing missing changes.** `codegiraffe_validate_changes` reports what is missing — it does not generate patches or modify code. The agent decides what to do with the information.
- **IDE integration.** MCP handles the protocol layer. CodeGiraffe does not need IDE-specific plugins.
- **Real-time file watching.** All tools are on-demand. There is no background process monitoring file changes. The agent calls the tool when it needs validation.
- **Semantic diff analysis.** The diff parser extracts structural information (files, hunks, approximate symbols from hunk headers). It does not perform full semantic analysis of what changed within a function body — that would require language-specific AST diffing, which is out of scope.
- **Git blame or authorship analysis.** File coupling is based on co-change frequency only. Authorship, blame, and review history are not considered.
- **Cross-repository change validation.** All analysis operates within a single repository. Cross-repo impact analysis via federation is a potential future enhancement.

### Dependencies

- **v0.9.0 (Scanner Depth):** Call-graph edges (`calls`) and enhanced interface/implementation tracking make blast radius and impact analysis significantly more precise. Without v0.9.0's deeper edges, `codegiraffe_validate_changes` will still work but will produce less complete impact reports.
- **Git:** Must be available and the project must be a git repository for `auto=True` mode and for `codegiraffe_file_coupling`. The `diff` parameter on Features 1 and 2 allows operation without git by accepting a diff string directly.
- **Existing infrastructure (v0.7.0+):** `compute_blast_radius()`, `generate_impact_summary()`, contract validation, and the existing `context_for_task()` scoring pipeline are all reused, not reimplemented.
- **No new required dependencies.** All git operations use `subprocess`. Diff parsing is pure Python regex. No new pip packages are required.

### Success Metrics

- **Self-validation:** Run `codegiraffe_validate_changes` against a synthetic partial change in the CodeGiraffe codebase itself (e.g., modify `scanner.py` without touching `server.py`) and verify it flags `server.py` as potentially missing.
- **Test suggestion accuracy:** For a change to `query.py`, `codegiraffe_suggest_tests` should rank `test_query.py` and related test files highest.
- **Coupling detection:** `codegiraffe_file_coupling` on the CodeGiraffe repo should identify `server.py` <-> `query.py` and `scanner.py` <-> `registry.py` as highly coupled pairs.
- **Zero regression:** All 850+ existing tests pass unchanged.
- **New test count:** 40+ new tests, 890+ total.

## User Stories

As an AI coding agent, I want to validate my uncommitted changes against the architecture graph so that I can discover impacted components I forgot to update before committing broken code.

As an AI coding agent, I want to know which tests are relevant to my changes so that I can run targeted tests instead of the entire suite, saving time and catching regressions faster.

As a developer, I want to see which files are implicitly coupled through git history so that I can understand hidden dependencies that static analysis misses and make more complete changes.

As an AI coding agent, I want context_for to be aware of my recent changes so that the nodes it returns are more relevant to what I am actively working on, not just what matches the task description.

As a developer, I want a pre-commit validation step that tells me "you changed the API handler but did not update the client that calls it" so that I catch contract violations before they reach production.

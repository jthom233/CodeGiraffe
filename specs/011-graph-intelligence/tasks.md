# Tasks: Graph Intelligence

**Input**: Design documents from `/specs/011-graph-intelligence/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/mcp-tools.md
**Constitution**: Principle VI (Test-First) is NON-NEGOTIABLE — tests are REQUIRED before implementation.

**Organization**: Tasks organized by release (v0.11.0 → v0.12.0 → v0.13.0), then by user story within each release. Each user story is independently testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2)
- Exact file paths included in all descriptions

---

# Release 1: v0.11.0 — Intelligent Context

**Features**: Token-Aware Context Budgets (US1), Intent-Aware Navigation (US2), Architectural Decision Records (US5), Convention Mining (US7)
**Target**: 29 MCP tools (1 new, 1 modified), ~57 new tests

---

## Phase 1: Setup (v0.11.0 Schema Foundation)

**Purpose**: Add new node/edge types needed by v0.11.0 features (ADRs)

- [x] T001 Add `DECISION` to `NodeType` enum and add `CONSTRAINS`, `MOTIVATED_BY`, `SUPERSEDES` to `EdgeType` enum in `src/codegiraffe/schema.py`
- [x] T002 [P] Add `DOMAIN` to `NodeType` enum and `BELONGS_TO`, `TESTED_BY` to `EdgeType` enum in `src/codegiraffe/schema.py` (added early to avoid cross-release schema merge conflicts — these types are inert until their respective features are implemented in v0.13.0)

**Checkpoint**: Schema updated — all existing 979 tests still pass.

---

## Phase 2: US1 — Token-Aware Context Retrieval (Priority: P1) MVP

**Goal**: AI agents specify a token budget and receive the highest-relevance subgraph that fits within that budget, with configurable detail levels.

**Independent Test**: Call `context_for` with `token_budget` parameter and verify response fits within budget while maximizing relevance.

### Tests for US1

> **Write these tests FIRST, ensure they FAIL before implementation**

- [x] T003 [P] [US1] Write token estimation tests in `tests/test_token_budget.py`: test `_estimate_tokens()` returns char_count/4 for a node with metadata and edges; test summary vs standard vs detailed detail levels produce different estimates for same node
- [x] T004 [P] [US1] Write token budget constraint tests in `tests/test_token_budget.py`: test `context_for_task` with `token_budget=4000` returns subgraph under 4000 estimated tokens; test response includes `_token_estimate` field; test nodes ordered by descending relevance score
- [x] T005 [P] [US1] Write dual-constraint tests in `tests/test_token_budget.py`: test when both `token_budget` and `max_nodes` specified, more restrictive wins; test `token_budget=100` (very small) returns single highest-relevance node or informative message
- [x] T006 [P] [US1] Write detail level tests in `tests/test_token_budget.py`: test `detail_level="summary"` returns only IDs and types (no metadata); test `detail_level="detailed"` includes full metadata; test more nodes fit in same budget at summary level vs detailed

### Implementation for US1

- [x] T007 [US1] Implement `_estimate_tokens(node_data: dict, detail_level: str) -> int` helper in `src/codegiraffe/query.py` — serialize node to JSON at given detail level, return `len(serialized) // 4`; implement `_format_node_for_detail_level(node_data: dict, detail_level: str) -> dict` to strip metadata for summary, include full for detailed
- [x] T008 [US1] Add `token_budget: int = 0` and `detail_level: str = "standard"` parameters to `context_for_task()` in `src/codegiraffe/query.py` — after scoring and sorting nodes by relevance, greedily add nodes until token budget exhausted; add `_token_estimate` to returned dict; when both `token_budget` and `max_nodes` set, apply whichever is more restrictive
- [x] T009 [US1] Update `codegiraffe_context_for` tool in `src/codegiraffe/server.py` — add `token_budget: int = 0` and `detail_level: str = "standard"` parameters; pass through to `context_for_task()`; include `_token_estimate` in formatted response

**Checkpoint**: US1 complete — `context_for` accepts token budgets and detail levels. All US1 tests pass.

---

## Phase 3: US2 — Intent-Aware Navigation (Priority: P1)

**Goal**: System classifies task intent (create/modify/debug/refactor/delete/test) and adjusts retrieval strategy — returning upstream deps for debugging, exemplar patterns for creation, blast radius for deletion.

**Independent Test**: Call `context_for` with different intent keywords and verify different subgraph structures returned.

### Tests for US2

- [x] T010 [P] [US2] Write intent classification tests in `tests/test_intent_navigation.py`: test `_classify_intent("create a new payment service")` returns "create"; test `_classify_intent("debug the timeout error")` returns "debug"; test `_classify_intent("refactor the auth module")` returns "refactor"; test `_classify_intent("delete the deprecated endpoint")` returns "delete"; test `_classify_intent("test the login flow")` returns "test"; test unclassifiable falls back to "modify"
- [x] T011 [P] [US2] Write intent-specific retrieval tests in `tests/test_intent_navigation.py`: test create intent returns exemplar nodes of same type; test debug intent returns upstream dependency chain; test refactor intent includes coupled files and cycles; test delete intent includes blast radius and contract violations; test "modify" intent matches current behavior
- [x] T012 [P] [US2] Write retrieval strategy response tests in `tests/test_intent_navigation.py`: test every `context_for` response includes `_retrieval_strategy` field; test ambiguous intent (e.g., "refactor and test") uses priority-ordered first match; test `_retrieval_strategy` value matches classified intent name

### Implementation for US2

- [x] T013 [US2] Implement `_classify_intent(task: str) -> str` in `src/codegiraffe/query.py` — keyword dictionary with priority-ordered matching per research.md decision #2: create → ["create", "add", "new", "build", "implement"], debug → ["debug", "fix", "bug", "error", "broken", "issue", "troubleshoot"], refactor → ["refactor", "restructure", "reorganize", "move", "extract", "split"], delete → ["delete", "remove", "deprecate", "drop"], test → ["test", "spec", "verify", "coverage", "assert"]; first match wins; unmatched → "modify"
- [x] T014 [US2] Implement per-intent retrieval strategies in `context_for_task()` in `src/codegiraffe/query.py` — create: boost exemplar nodes of same type as target; debug: include upstream dependency chain (reverse BFS on imports/calls edges); refactor: include coupled files via co-change data + cycles involving target; delete: include blast radius + contract violations; test: include target deps + associated test files; modify: current behavior (unchanged)
- [x] T015 [US2] Add `_retrieval_strategy` field to `context_for_task()` response dict in `src/codegiraffe/query.py`; update `codegiraffe_context_for` in `src/codegiraffe/server.py` to include strategy in formatted output

**Checkpoint**: US2 complete — `context_for` classifies intent and returns strategy-appropriate subgraphs. All US1 + US2 tests pass.

---

## Phase 4: US5 — Architectural Decision Records (Priority: P2, in v0.11.0)

**Goal**: Scanner detects `# DECISION:` and `// ADR-` markers in code comments and creates decision nodes linked to governed components. `context_for` auto-includes relevant decisions.

**Independent Test**: Add decision comments to test files, scan, verify decision nodes created and included in `context_for` results.

### Tests for US5

- [x] T016 [P] [US5] Write ADR detection tests in `tests/test_decisions.py`: test `_detect_decision_markers()` finds `# DECISION: Use event bus` in Python files; test `// ADR-007: JWT over sessions` in Go/TS/Java files; test `/* ADR-003: ... */` in block comments; test decision node ID format is `decision:{file}:{line}`; test decision metadata includes text, adr_id, file_path, line_number, mined_from="comment"
- [x] T017 [P] [US5] Write decision constraint targeting tests in `tests/test_decisions.py`: test `constrains` edge targets specific governed nodes (matched by node ID references in decision text), not just the file module node; test when no node ID matches in text, `constrains` edge targets the nearest enclosing symbol; test `_include_constraining_decisions()` adds decision nodes when governed nodes are in subgraph; test `supersedes` edge links newer decision to older
- [x] T018 [P] [US5] Write decision edge case and contract tests in `tests/test_decisions.py`: test orphan decision (governed node deleted) persists with warning flag; test decision with no matches creates no edges; test files with no decision markers produce no decision nodes; test `add_relation` accepts `decision` node type with `constrains`/`motivated_by`/`supersedes` edge types (contract test — verifies existing tool handles new schema types)

### Implementation for US5

- [x] T019 [US5] Implement `_detect_decision_markers(file_path: str, content: str) -> list[dict]` in `src/codegiraffe/scanner.py` — regex patterns per research.md decision #5: `# DECISION:`, `// ADR-\d+:`, `/* ADR-\d+:`; return list of dicts with text, adr_id, line_number; integrate into scanner pipeline as a new stage after `_infer_contract_edges()`
- [x] T020 [US5] Implement decision node creation and constraint targeting in scanner pipeline in `src/codegiraffe/scanner.py` — for each detected marker, create `Node(id=f"decision:{file}:{line}", type=NodeType.DECISION, ...)` with metadata; create `constrains` edges to **specific governed nodes** by: (1) scanning decision text for node ID references (e.g., "service:PaymentService"), (2) if no matches, target the nearest enclosing symbol node from the same file, (3) fallback to the file's module node; for ADR-numbered decisions, group by ADR ID
- [x] T021 [US5] Implement `_include_constraining_decisions(subgraph_nodes, graph)` in `src/codegiraffe/query.py` — given a set of nodes in a subgraph result, find all decision nodes connected via `constrains` edges and add them to the result; integrate into `context_for_task()` after initial subgraph extraction
- [x] T022 [US5] Add decision node and edge styling to `src/codegiraffe/dashboard.py` — decision nodes: color `#2196F3` (blue), shape `tag`; constrains edges: blue dotted, width 1.5; supersedes edges: gray dashed, width 1; add to `TYPE_COLORS`, `TYPE_SHAPES`, and edge style maps

**Checkpoint**: US5 complete — decisions detected from code comments and auto-included in context. All US1 + US2 + US5 tests pass.

---

## Phase 5: US7 — Convention Mining (Priority: P3, in v0.11.0)

**Goal**: New `codegiraffe_patterns` tool analyzes clusters of same-type nodes to extract naming conventions, structural patterns, and detect anti-patterns.

**Independent Test**: Call `codegiraffe_patterns` on a graph with 3+ nodes of the same type and verify pattern brief returned.

### Tests for US7

- [x] T023 [P] [US7] Write pattern extraction tests in `tests/test_patterns.py`: test `extract_patterns()` with 4 endpoint nodes sharing naming convention returns pattern brief with naming_pattern, common_attributes, exemplar; test outlier node flagged as anti-pattern when deviating from >66% convention; test `sample_size` in result matches input cluster size
- [x] T024 [P] [US7] Write minimum cluster tests in `tests/test_patterns.py`: test fewer than 3 nodes of a type returns insufficient data message; test exactly 3 nodes is the minimum for pattern extraction; test node types with no instances return appropriate error
- [x] T025 [P] [US7] Write pattern similarity and contract tests in `tests/test_patterns.py`: test `_extract_naming_pattern()` detects common prefixes/suffixes in node IDs; test common_attributes populated with attributes present in >66% of nodes; test 50/50 split patterns reported as alternatives (not single convention); contract test: verify `codegiraffe_patterns` tool accepts required params (project_path, node_type) and returns valid pattern brief JSON structure

### Implementation for US7

- [x] T026 [US7] Create `src/codegiraffe/patterns.py` — implement `extract_patterns(graph: ArchGraph, node_type: str, min_cluster: int = 3) -> dict` that: filters nodes by type, validates minimum cluster size, extracts naming patterns via `_extract_naming_pattern()`, counts attribute frequency, identifies outliers (missing >50% of conventions), selects exemplar (node closest to cluster center); implement `_extract_naming_pattern(node_ids: list[str]) -> str` using common prefix/suffix detection
- [x] T027 [US7] Add `codegiraffe_patterns` tool in `src/codegiraffe/server.py` — parameters: `project_path` (required), `node_type` (required), `min_cluster` (optional, default 3); call `extract_patterns()`; format result as pattern brief text

**Checkpoint**: US7 complete — convention mining tool available. All v0.11.0 tests pass.

---

## Phase 6: v0.11.0 Polish & Cross-Cutting

**Purpose**: Final integration, version bump, full test run

- [x] T028 Run full test suite (`python -m pytest tests/ -v`) and verify all existing 979 tests + new ~57 tests pass
- [x] T029 Update version to `0.11.0` in `src/codegiraffe/__init__.py` and `pyproject.toml`
- [x] T030 Update `README.md` tools table with `codegiraffe_patterns` and enhanced `context_for` parameters

**Checkpoint**: v0.11.0 release-ready — 29 MCP tools, ~1036 tests passing.

---
---

# Release 2: v0.12.0 — Graph Enrichment

**Features**: Confidence Scoring (US3), Ownership Layer (US4), Incremental Sync (US6)
**Target**: 31 MCP tools (2 new, 3 modified), ~42 new tests

---

## Phase 7: v0.12.0 Foundational — Confidence on Edges

**Purpose**: Add `confidence` field to Edge model — foundational for US3 and affects all downstream tools.

- [x] T031 Add `confidence: float = 1.0` field to `Edge` Pydantic model in `src/codegiraffe/graph.py` — default 1.0 ensures backward compatibility with existing stored graphs (Pydantic `model_validate` auto-fills default)

**Checkpoint**: Edge model updated — all existing tests still pass (default confidence = 1.0 is backward compatible).

---

## Phase 8: US3 — Confidence Scoring on Edges (Priority: P2)

**Goal**: Every edge carries a confidence value based on detection method. Agents can filter by `min_confidence`, and impact analysis weights by confidence.

**Independent Test**: Scan a project and verify edges have confidence values varying by detection method; filter by `min_confidence`.

### Tests for US3

- [x] T032 [P] [US3] Write confidence assignment tests in `tests/test_confidence.py`: test AST-parsed import edge gets confidence 1.0; test regex import edge gets 0.9; test call-graph direct match gets 0.8; test call-graph fallback gets 0.6; test interface satisfaction gets 0.7; test contract inference gets 0.5; test manual edge gets 1.0; test cross-file inference gets 0.8
- [x] T033 [P] [US3] Write confidence filtering tests in `tests/test_confidence.py`: test `context_for` with `min_confidence=0.8` excludes edges below 0.8; test `min_confidence=0.0` (default) includes all edges; test `min_confidence=1.0` only includes AST and manual edges
- [x] T034 [P] [US3] Write confidence-weighted impact tests in `tests/test_confidence.py`: test `blast_radius` with high-confidence path produces higher severity than same path at low confidence; test backward compatibility — loading graph with no confidence field defaults edges to 1.0

### Implementation for US3

- [x] T035 [US3] Update scanner pipeline functions in `src/codegiraffe/scanner.py` to assign confidence values: `_infer_import_edges()` → 0.9 (regex) or 1.0 (AST via ast_scanner); `_infer_call_edges()` → 0.8 (direct) or 0.6 (fallback); `_infer_interface_satisfaction()` → 0.7; `_infer_contract_edges()` → 0.5; inheritance regex → 0.8; contains edges → 1.0
- [x] T036 [US3] Add `min_confidence: float = 0.0` parameter to `context_for_task()` in `src/codegiraffe/query.py` — filter edges below threshold before subgraph extraction; update `codegiraffe_context_for` in `src/codegiraffe/server.py` with new parameter
- [x] T037 [US3] Update `compute_blast_radius()` in `src/codegiraffe/query.py` to weight impact severity by edge confidence — multiply severity score by confidence of the traversed edge; low-confidence paths produce lower severity ratings. **Note**: T044 (US4) also modifies this function to add cross-team impact — T044 must build on T037's changes.
- [x] T038 [US3] Add confidence-based edge opacity to `src/codegiraffe/dashboard.py` — edge opacity = max(0.3, confidence); update edge style generation to include opacity

**Checkpoint**: US3 complete — all edges have confidence scores, filtering and weighted impact work. All tests pass.

---

## Phase 9: US4 — Ownership and Annotation Layer (Priority: P2)

**Goal**: Nodes can be annotated with owner, stability, and notes. Ownership inferred from CODEOWNERS and git blame. Impact analysis flags cross-team impact.

**Independent Test**: Annotate nodes and verify annotations appear in `context_for` and `blast_radius` results.

### Tests for US4

- [x] T039 [P] [US4] Write CODEOWNERS parsing tests in `tests/test_ownership.py`: test `parse_codeowners()` with standard CODEOWNERS format; test gitignore-style pattern matching maps files to owners; test most specific rule wins (last match); test missing CODEOWNERS returns empty mapping
- [x] T040 [P] [US4] Write annotation tests in `tests/test_ownership.py`: test `codegiraffe_annotate` sets owner, stability, notes on a node; test annotations persist in node metadata; test `context_for` results include ownership annotations; test `stability=deprecated` visible in response
- [x] T041 [P] [US4] Write cross-team impact and contract tests in `tests/test_ownership.py`: test `blast_radius` flags nodes with different `owner` than changed node as cross-team impact; test cross-team report includes owner names; test nodes without ownership annotation are not flagged; contract test: verify `codegiraffe_annotate` tool accepts required params (project_path, node_id) and optional params (owner, stability, notes) and returns confirmation JSON

### Implementation for US4

- [x] T042 [US4] Create `src/codegiraffe/ownership.py` — implement `parse_codeowners(project_path: str) -> dict[str, str]` mapping file patterns to owners using gitignore-style matching; implement `infer_ownership_from_blame(project_path: str, file_path: str) -> str` returning most frequent committer via `git log --format=%an`; implement `map_ownership_to_nodes(graph: ArchGraph, ownership: dict)` setting `owner` metadata on nodes
- [x] T043 [US4] Add `codegiraffe_annotate` tool in `src/codegiraffe/server.py` — parameters: `project_path` (required), `node_id` (required), `owner` (optional), `stability` (optional: stable/experimental/deprecated/legacy), `notes` (optional); update node metadata directly
- [x] T044 [US4] Update `compute_blast_radius()` in `src/codegiraffe/query.py` to include `cross_team_impact` in result — when annotated nodes have different `owner` than the changed node, flag them in a separate list; add ownership badge overlay to `src/codegiraffe/dashboard.py`

**Checkpoint**: US4 complete — ownership annotations and cross-team impact flagging work. All tests pass.

---

## Phase 10: US6 — Incremental Sync (Priority: P2)

**Goal**: Agents can sync only changed files, keeping the graph current without full rescan overhead.

**Independent Test**: Modify a file, call `codegiraffe_sync_files` with that path, verify only that file's nodes/edges updated.

### Tests for US6

- [x] T045 [P] [US6] Write incremental sync tests in `tests/test_incremental_sync.py`: test `sync_files()` with single changed file only rescans that file; test old edges from changed file removed before new edges added; test deleted file removes all its nodes and edges; test manual annotations on synced nodes are preserved
- [x] T046 [P] [US6] Write edge invalidation and contract tests in `tests/test_incremental_sync.py`: test new import edges added without duplicating existing; test modified file with new function adds new node without losing siblings; test edge from non-synced file to synced file is preserved (only source-file edges invalidated); contract test: verify `codegiraffe_sync_files` tool accepts required params (project_path, file_paths) and returns summary JSON with added/removed/preserved counts

### Implementation for US6

- [x] T047 [US6] Implement `sync_files(graph: ArchGraph, project_path: str, file_paths: list[str], scanner_mode: str = "regex") -> dict` in `src/codegiraffe/scanner.py` — for each file: find all nodes with matching `file_path`, collect non-manual edges where source or target is one of those nodes, remove those edges, remove non-manual nodes from that file, rescan the file, re-add nodes and edges, re-run inference stages (`_infer_import_edges`, `_infer_call_edges`, etc.) for just those files; for deleted files: remove all nodes and edges originating from that file
- [x] T048 [US6] Add `codegiraffe_sync_files` tool in `src/codegiraffe/server.py` — parameters: `project_path` (required), `file_paths` (required, JSON array or comma-separated list), `scanner_mode` (optional, default "regex"); call `sync_files()`; return summary of nodes/edges added, removed, preserved

**Checkpoint**: US6 complete — incremental sync works. All tests pass.

---

## Phase 11: v0.12.0 Polish & Cross-Cutting

- [x] T049 Run full test suite and verify all existing + new ~42 tests pass
- [x] T050 Update version to `0.12.0` in `src/codegiraffe/__init__.py` and `pyproject.toml`
- [x] T051 Update `README.md` with `codegiraffe_annotate`, `codegiraffe_sync_files` tools and confidence scoring docs

**Checkpoint**: v0.12.0 release-ready — 31 MCP tools, ~1078 tests passing.

---
---

# Release 3: v0.13.0 — Advanced Analysis

**Features**: Test Coverage Mapping (US8), Graph Diffing (US9), Task Ordering (US10), Domain Abstraction (US11), CI/CD Integration (US12), Migration Planner (US13)
**Target**: 36 MCP tools (5 new, 2 modified), ~63 new tests

---

## Phase 12: US8 — Test Coverage Mapping (Priority: P3)

**Goal**: Integrate coverage.py/Istanbul data, map to graph nodes. Risk assessment uses coverage. Test suggestions distinguish "run existing" vs "write new."

**Independent Test**: Provide coverage JSON, verify nodes get `_test_coverage` metadata and risk/suggest_tests behavior changes.

### Tests for US8

- [ ] T052 [P] [US8] Write coverage parsing tests in `tests/test_coverage_mapper.py`: test `parse_coverage_py()` reads coverage.py JSON and returns file→percentage mapping; test `parse_istanbul()` reads Istanbul JSON; test `parse_lcov()` reads LCOV format; test `auto` format detection selects correct parser
- [ ] T053 [P] [US8] Write coverage mapping tests in `tests/test_coverage_mapper.py`: test `map_coverage_to_nodes()` sets `_test_coverage` metadata on matching nodes; test uncovered nodes (0%) get metadata; test file not in coverage data gets no metadata; test graceful degradation when no coverage data provided
- [ ] T054 [P] [US8] Write coverage-enhanced risk/test and contract tests in `tests/test_coverage_mapper.py`: test `risk_assessment` gives uncovered nodes 1.5x risk multiplier; test `suggest_tests` returns `coverage_status="uncovered"` for unmapped nodes; test `suggest_tests` returns `coverage_status="covered"` for mapped nodes; contract test: verify `codegiraffe_coverage` tool accepts required params (project_path, coverage_path) and returns valid mapping summary JSON

### Implementation for US8

- [ ] T055 [US8] Create `src/codegiraffe/coverage_mapper.py` — implement `parse_coverage_py(path: str) -> dict[str, float]`, `parse_istanbul(path: str) -> dict[str, float]`, `parse_lcov(path: str) -> dict[str, float]`, `auto_detect_format(path: str) -> str`; implement `map_coverage_to_nodes(graph: ArchGraph, coverage: dict)` setting `_test_coverage` metadata on nodes whose `file_path` matches coverage keys; create `tested_by` edges from covered nodes to their corresponding test module nodes (using the `TESTED_BY` edge type from schema.py)
- [ ] T056 [US8] Add `codegiraffe_coverage` tool in `src/codegiraffe/server.py`; update `compute_risk_assessment()` in `src/codegiraffe/query.py` to apply 1.5x risk multiplier for nodes with `_test_coverage == 0` or missing coverage; update `suggest_tests_for_changes()` in `src/codegiraffe/query.py` to include `coverage_status` field

**Checkpoint**: US8 complete — coverage data maps to nodes, risk and test suggestions enhanced.

---

## Phase 13: US9 — Graph Diffing for PR Review (Priority: P3)

**Goal**: Build graphs at two git refs and compute architectural delta (nodes/edges added/removed, contracts affected, new cycles).

**Independent Test**: Create commits that change architecture, call `codegiraffe_pr_diff`, verify structural diff detected.

### Tests for US9

- [ ] T057 [P] [US9] Write graph diff computation tests in `tests/test_graph_diff.py`: test `compute_graph_diff()` with two ArchGraph instances detects nodes added, removed, modified; test edges added/removed detected; test identical graphs produce empty diff; test contracts affected listed
- [ ] T058 [P] [US9] Write new cycle detection tests in `tests/test_graph_diff.py`: test diff that introduces a cycle flags it in `new_cycles`; test diff that removes a cycle doesn't flag it; test diff with no cycle changes returns empty `new_cycles`
- [ ] T059 [P] [US9] Write git worktree integration and contract tests in `tests/test_graph_diff.py`: test `build_graph_at_ref()` creates temporary worktree and scans; test worktree cleanup after scan; test error when refs have no common ancestor; contract test: verify `codegiraffe_pr_diff` tool accepts required params (project_path, base_ref) and returns structured diff report JSON with nodes_added/removed/modified, edges_added/removed, contracts_affected, new_cycles, summary

### Implementation for US9

- [ ] T060 [US9] Create `src/codegiraffe/graph_diff.py` — implement `compute_graph_diff(base_graph: ArchGraph, head_graph: ArchGraph) -> dict` comparing node sets (added/removed/modified by metadata diff), edge sets, contracts affected, new cycles (cycles in head not in base); implement `build_graph_at_ref(project_path: str, ref: str, scanner_mode: str) -> ArchGraph` using `git worktree add` to temp dir, scan, build graph, `git worktree remove`
- [ ] T061 [US9] Add `codegiraffe_pr_diff` tool in `src/codegiraffe/server.py` — parameters: `project_path` (required), `base_ref` (required), `head_ref` (optional, default "HEAD"); call `build_graph_at_ref` for both refs, `compute_graph_diff`, return structured report with summary

**Checkpoint**: US9 complete — PR architectural diffs available.

---

## Phase 14: US10 — Dependency-Aware Task Ordering (Priority: P3)

**Goal**: Given a list of tasks with target files, return topologically sorted execution plan with parallel groups and conflict zones.

**Independent Test**: Provide tasks with file targets, verify order respects import dependencies.

### Tests for US10

- [ ] T062 [P] [US10] Write task ordering tests in `tests/test_task_ordering.py`: test `order_tasks()` with task A (modifying imported file) appears before task B (importing it); test tasks C and D with no graph overlap marked as parallelizable; test tasks touching same file flagged as conflict zones; test circular dependency detected and reported
- [ ] T063 [P] [US10] Write parallel group and contract tests in `tests/test_task_ordering.py`: test `parallel_groups` contains task indices at same topological level; test `dependency_edges` includes (task_a, task_b, reason) triples; test single task returns trivial plan; contract test: verify `codegiraffe_order_tasks` tool accepts required params (project_path, tasks JSON) and returns execution plan JSON with ordered_tasks, parallel_groups, conflict_zones, dependency_edges

### Implementation for US10

- [ ] T064 [US10] Implement `order_tasks(graph: ArchGraph, tasks: list[dict]) -> dict` in `src/codegiraffe/query.py` — map each task's `target_files` to module nodes, build task dependency subgraph from module `imports` edges, topological sort via `nx.topological_sort()`, group tasks at same level as parallel groups, detect same-file conflicts; return `ordered_tasks`, `parallel_groups`, `conflict_zones`, `dependency_edges`
- [ ] T065 [US10] Add `codegiraffe_order_tasks` tool in `src/codegiraffe/server.py` — parameters: `project_path` (required), `tasks` (required, JSON array with `name` and `target_files` fields); parse JSON, call `order_tasks()`, format result

**Checkpoint**: US10 complete — task ordering with parallelization.

---

## Phase 15: US11 — Domain Model Abstraction (Priority: P3)

**Goal**: Map domain concepts (e.g., "payments", "auth") to clusters of graph nodes. Support auto-inference from directories and manual definition.

**Independent Test**: Define domains, query by domain name, verify domain grouping in blast radius.

### Tests for US11

- [ ] T066 [P] [US11] Write domain inference tests in `tests/test_domains.py`: test `infer_domains()` clusters nodes by top-level directory; test flat structure falls back to node ID prefix clustering; test domains have correct node_count; test no meaningful clusters returns empty list
- [ ] T067 [P] [US11] Write domain query tests in `tests/test_domains.py`: test `context_for` with domain name as task prioritizes domain-member nodes; test `blast_radius` groups impacted nodes by domain; test manual domain definition persists across rescans; test domain add/remove operations
- [ ] T068 [P] [US11] Write domain persistence and contract tests in `tests/test_domains.py`: test manual domains have `manual=True`; test inferred domains rebuilt on rescan; test `belongs_to` edges connect nodes to domain nodes; contract test: verify `codegiraffe_domains` tool accepts required params (project_path) and optional params (action, name, node_ids) and returns valid domain list or confirmation JSON

### Implementation for US11

- [ ] T069 [US11] Create `src/codegiraffe/domains.py` — implement `infer_domains(graph: ArchGraph) -> list[dict]` clustering nodes by directory path or ID prefix; implement `add_domain(graph: ArchGraph, name: str, node_ids: list[str])` creating domain node with `belongs_to` edges; implement `remove_domain(graph: ArchGraph, name: str)`; implement `list_domains(graph: ArchGraph) -> list[dict]`
- [ ] T070 [US11] Add `codegiraffe_domains` tool in `src/codegiraffe/server.py` — parameters: `project_path` (required), `action` (optional: list/infer/add/remove), `name` (optional), `node_ids` (optional JSON array); update `context_for_task()` in `src/codegiraffe/query.py` to boost domain-member nodes when task contains a domain name; update `compute_blast_radius()` to group by domain in `domain_groups` field

**Checkpoint**: US11 complete — domain abstraction layer available.

---

## Phase 16: US12 — CI/CD Integration (Priority: P3)

**Goal**: GitHub Actions workflow template for automated architectural validation on PRs.

**Independent Test**: Run workflow on test repo, verify PR comment posted.

### Tests for US12

- [ ] T071 [P] [US12] Write workflow validation tests in `tests/test_cicd.py`: test workflow YAML is valid GitHub Actions syntax; test configurable blast radius threshold parsing; test PR comment formatting with mock data (blast radius, contracts, cycles)

### Implementation for US12

- [ ] T072 [US12] Create `.github/workflows/codegiraffe-pr.yml` — workflow that: triggers on PR events, installs codegiraffe, runs `codegiraffe_init` or `codegiraffe_sync`, runs `codegiraffe_validate_changes` on PR diff, runs `codegiraffe_blast_radius` on changed files, posts PR comment via `gh pr comment` with architectural impact summary; support configurable `BLAST_RADIUS_THRESHOLD` env var for pass/fail
- [ ] T073 [US12] Create `.github/scripts/format-pr-comment.py` helper script — format blast radius, contract status, and cycle info into markdown PR comment template

**Checkpoint**: US12 complete — CI/CD workflow template ready.

---

## Phase 17: US13 — Migration Planner (Priority: P4)

**Goal**: Generate ordered transformation plans for large refactors that maintain consistency at each step.

**Independent Test**: Describe a migration, verify plan has valid intermediate states.

### Tests for US13

- [ ] T074 [P] [US13] Write migration plan tests in `tests/test_migration.py`: test `generate_migration_plan()` with "move reads to cache" produces ordered steps; test each step maintains valid import graph; test contract implications listed; test rollback checkpoints identified at safe states
- [ ] T075 [P] [US13] Write migration edge case and contract tests in `tests/test_migration.py`: test empty migration (no nodes affected) returns empty plan; test migration affecting all nodes in a cycle reports the cycle; test estimated_files count matches actual unique files in steps; contract test: verify `codegiraffe_migration_plan` tool accepts required params (project_path, description) and returns valid migration plan JSON with steps, checkpoints, contract_implications, estimated_files

### Implementation for US13

- [ ] T076 [US13] Create `src/codegiraffe/migration.py` — implement `generate_migration_plan(graph: ArchGraph, description: str, target_nodes: list[str] | None = None) -> dict` that: identifies affected nodes from description keywords or target_nodes list, computes dependency order for changes, validates each step maintains valid imports (no broken dependencies), identifies rollback checkpoints (steps where graph is in consistent state), reports contract implications; return `steps`, `checkpoints`, `contract_implications`, `estimated_files`
- [ ] T077 [US13] Add `codegiraffe_migration_plan` tool in `src/codegiraffe/server.py` — parameters: `project_path` (required), `description` (required), `target_nodes` (optional JSON array); call `generate_migration_plan()`, format result

**Checkpoint**: US13 complete — migration planning available.

---

## Phase 18: v0.13.0 Polish & Cross-Cutting

- [ ] T078 Add domain visual grouping to `src/codegiraffe/dashboard.py` — compound nodes via Cytoscape.js parent-child for domain clusters
- [ ] T079 Run full test suite and verify all existing + new ~63 tests pass
- [ ] T080 Update version to `0.13.0` in `src/codegiraffe/__init__.py` and `pyproject.toml`
- [ ] T081 Update `README.md` with all 8 new tools (codegiraffe_patterns, codegiraffe_annotate, codegiraffe_sync_files, codegiraffe_coverage, codegiraffe_pr_diff, codegiraffe_order_tasks, codegiraffe_domains, codegiraffe_migration_plan) and enhanced tool parameter documentation

**Checkpoint**: v0.13.0 release-ready — 36 MCP tools, ~1141 tests passing.

---

## Dependencies & Execution Order

### Release Dependencies

- **v0.11.0**: No dependencies on other releases — can start immediately
- **v0.12.0**: Depends on v0.11.0 completion (schema changes, context_for enhancements)
- **v0.13.0**: Depends on v0.12.0 completion (confidence scoring used by PR diff, coverage; incremental sync used by CI/CD)

### Phase Dependencies (within each release)

#### v0.11.0
- **Phase 1 (Setup)**: No dependencies — start here
- **Phase 2 (US1)**: Depends on Phase 1
- **Phase 3 (US2)**: Depends on Phase 2 (builds on context_for changes)
- **Phase 4 (US5)**: Depends on Phase 1 (schema); can run in parallel with Phase 2/3 if schema done
- **Phase 5 (US7)**: Depends on Phase 1 only; can run in parallel with Phase 2/3/4
- **Phase 6 (Polish)**: Depends on all Phase 2-5

#### v0.12.0
- **Phase 7 (Foundational)**: Depends on v0.11.0 complete
- **Phase 8 (US3)**: Depends on Phase 7
- **Phase 9 (US4)**: Depends on Phase 7; can run in parallel with Phase 8
- **Phase 10 (US6)**: Depends on Phase 7; can run in parallel with Phase 8/9
- **Phase 11 (Polish)**: Depends on all Phase 8-10

#### v0.13.0
- **Phase 12 (US8)**: Depends on v0.12.0; can run in parallel with Phase 13-17
- **Phase 13 (US9)**: Depends on v0.12.0; can run in parallel with Phase 12/14-17
- **Phase 14 (US10)**: Depends on v0.12.0; can run in parallel with Phase 12-13/15-17
- **Phase 15 (US11)**: Depends on v0.12.0; can run in parallel with Phase 12-14/16-17
- **Phase 16 (US12)**: Depends on v0.12.0; can run in parallel with Phase 12-15/17
- **Phase 17 (US13)**: Depends on v0.12.0; can run in parallel with Phase 12-16
- **Phase 18 (Polish)**: Depends on all Phase 12-17

### Parallel Opportunities

**Within v0.11.0:**
- US5 (ADRs) and US7 (Convention Mining) can run in parallel after Phase 1
- US1 and US2 must be sequential (US2 builds on US1's context_for changes)
- All test tasks within a user story can run in parallel

**Within v0.12.0:**
- US3 (Confidence), US4 (Ownership), US6 (Incremental Sync) can all run in parallel after Phase 7

**Within v0.13.0:**
- ALL six user stories (US8-US13) can run in parallel — they touch different files

---

## Implementation Strategy

### MVP First (v0.11.0 Only)

1. Complete Phase 1: Schema setup
2. Complete Phase 2: US1 (Token Budgets) — highest-impact single feature
3. **STOP and VALIDATE**: Test token-aware context_for independently
4. Continue Phase 3-5: US2, US5, US7
5. Phase 6: Polish → v0.11.0 release

### Incremental Delivery

1. v0.11.0 (Token budgets + Intent nav + ADRs + Patterns) → Test → Release → PR
2. v0.12.0 (Confidence + Ownership + Incremental sync) → Test → Release → PR
3. v0.13.0 (Coverage + PR diff + Tasks + Domains + CI/CD + Migration) → Test → Release → PR
4. Each release adds value without breaking previous releases

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks
- [Story] label maps task to specific user story for traceability
- Constitution VI (Test-First): ALL test tasks MUST be written and FAIL before implementation begins
- Each checkpoint validates that all prior stories remain functional
- Commit after each completed phase
- Total: 81 tasks across 18 phases and 3 releases

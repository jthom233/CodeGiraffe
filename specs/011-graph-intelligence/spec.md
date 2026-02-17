# Feature Specification: Graph Intelligence

**Feature Branch**: `011-graph-intelligence`
**Created**: 2026-02-16
**Status**: Draft
**Input**: CodeGiraffe v0.11.0+ Feature Expansion — 13 features across 3 tiers for intelligent graph capabilities
**Release Strategy**: Phased by tier — v0.11.0 (Token Budgets, Intent Navigation, ADRs, Convention Mining), v0.12.0 (Confidence Scoring, Ownership, Incremental Sync), v0.13.0 (Coverage, PR Diff, Task Ordering, Domains, CI/CD, Migration Planner)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Token-Aware Context Retrieval (Priority: P1)

An AI agent working on a task needs architecture context but has a limited context window. Instead of requesting a fixed number of nodes (which may overflow or underutilize its budget), the agent specifies a token budget and receives the highest-relevance subgraph that fits within that budget. The agent can also choose a detail level to control how much metadata is included per node.

**Why this priority**: Directly addresses the #1 challenge in AI context engineering. Every `context_for` call benefits immediately. Lowest effort, highest immediate impact. No competitor offers token-aware retrieval.

**Independent Test**: Can be tested by calling `context_for` with a `token_budget` parameter on any initialized graph and verifying the response fits within the budget while maximizing relevance.

**Acceptance Scenarios**:

1. **Given** an initialized graph with 50+ nodes, **When** an agent calls `context_for` with `token_budget=4000`, **Then** the returned subgraph's estimated token count is at or below 4000 and nodes are ordered by relevance score.
2. **Given** an initialized graph, **When** an agent calls `context_for` with `token_budget=4000` and `detail_level="summary"`, **Then** nodes include only IDs and types (no full metadata), allowing more nodes to fit in the budget.
3. **Given** an initialized graph, **When** an agent calls `context_for` with `token_budget=4000` and `detail_level="detailed"`, **Then** nodes include full metadata, and fewer nodes fit in the budget.
4. **Given** an initialized graph, **When** `context_for` returns results, **Then** the response includes a `_token_estimate` field with the estimated token count of the returned subgraph.
5. **Given** an initialized graph, **When** both `token_budget` and `max_nodes` are specified, **Then** the more restrictive constraint wins (whichever produces fewer nodes).

---

### User Story 2 - Intent-Aware Navigation (Priority: P1)

An AI agent describes a task like "debug the payment timeout issue" or "create a new notification service." The system classifies the task intent and adjusts its retrieval strategy accordingly — returning upstream dependencies for debugging, or exemplar patterns for creation — rather than treating all queries as generic keyword searches.

**Why this priority**: Transforms `context_for` from a search engine into a research assistant. Different kinds of work require different kinds of context, and this encodes that workflow knowledge into retrieval.

**Independent Test**: Can be tested by calling `context_for` with task descriptions containing different intent keywords and verifying the returned subgraph structure differs appropriately.

**Acceptance Scenarios**:

1. **Given** an initialized graph, **When** an agent calls `context_for` with a task containing "create" or "add new" keywords, **Then** the system returns exemplar nodes of the same type as the target, showing patterns to follow.
2. **Given** an initialized graph, **When** an agent calls `context_for` with a task containing "debug" or "fix" keywords, **Then** the system returns the target node plus its upstream dependency chain.
3. **Given** an initialized graph, **When** an agent calls `context_for` with a task containing "refactor" or "restructure" keywords, **Then** the system returns the target subgraph plus coupled files and any cycles involving the target.
4. **Given** an initialized graph, **When** an agent calls `context_for` with a task containing "delete" or "remove" keywords, **Then** the system returns the full blast radius plus contract violations and downstream consumers.
5. **Given** an initialized graph, **When** an agent calls `context_for` with a task containing "test" keywords, **Then** the system returns the target plus its dependencies and associated test files.
6. **Given** any `context_for` result, **Then** the response includes a `_retrieval_strategy` field indicating which intent was classified (create, modify, debug, refactor, delete, test, or general).

---

### User Story 3 - Confidence Scoring on Edges (Priority: P2)

The scanner detects relationships using various methods — AST parsing, regex matching, naming conventions, contract inference. Currently all edges are treated equally. With confidence scoring, each edge carries a confidence value reflecting how reliably it was detected. Agents can filter by minimum confidence, and impact analysis weights results by confidence.

**Why this priority**: Improves precision of all downstream tools (blast radius, context_for, cycles). Prevents agents from acting on weak signals. Low effort, foundational for other features.

**Independent Test**: Can be tested by scanning a project and verifying edges have appropriate confidence values based on their detection method.

**Acceptance Scenarios**:

1. **Given** a scanned project using AST mode, **When** an import edge is detected via tree-sitter parsing, **Then** the edge has confidence 1.0.
2. **Given** a scanned project using regex mode, **When** an import edge is detected via regex, **Then** the edge has confidence 0.9.
3. **Given** a scanned project, **When** a call edge is inferred from naming conventions, **Then** the edge has confidence 0.6.
4. **Given** a scanned project, **When** a contract edge is inferred from pattern matching, **Then** the edge has confidence 0.5.
5. **Given** a manually added edge, **Then** the edge has confidence 1.0.
6. **Given** an initialized graph, **When** `context_for` is called with `min_confidence=0.8`, **Then** only edges with confidence >= 0.8 are included in the subgraph.
7. **Given** an initialized graph, **When** `blast_radius` is computed, **Then** impact severity is weighted by edge confidence (low-confidence paths produce lower severity).

---

### User Story 4 - Ownership and Annotation Layer (Priority: P2)

Teams need to annotate graph nodes with ownership information, stability status, and tribal knowledge. The system infers ownership from CODEOWNERS files and git blame frequency, and provides a tool for manual annotations. Impact analysis flags cross-team impact.

**Why this priority**: Makes the graph a living knowledge base rather than just a structural map. Low effort, high value for teams.

**Independent Test**: Can be tested by annotating nodes and verifying annotations appear in context retrieval and impact analysis.

**Acceptance Scenarios**:

1. **Given** a project with a CODEOWNERS file, **When** the graph is initialized, **Then** nodes are annotated with their owner from CODEOWNERS.
2. **Given** a project with git history, **When** the graph is initialized with ownership inference enabled, **Then** nodes are annotated with the most frequent committer as owner.
3. **Given** an initialized graph, **When** an agent calls `codegiraffe_annotate` with a node ID, owner, and stability status, **Then** those annotations are persisted on the node.
4. **Given** annotated nodes, **When** `context_for` returns a subgraph, **Then** ownership and stability annotations are included in node metadata.
5. **Given** annotated nodes with different owners, **When** `blast_radius` is computed for a change, **Then** the report flags cross-team impact (nodes owned by teams different from the changed node's owner).
6. **Given** an annotated node with `stability=deprecated`, **When** the node appears in `context_for` results, **Then** the deprecation status is visible in the response.

---

### User Story 5 - Architectural Decision Records (Priority: P2)

AI agents make changes that violate past design decisions because they have no access to the reasoning behind the architecture. With ADR support, decisions are captured as graph nodes linked to the components they govern. When an agent retrieves context for a task, relevant decisions are automatically included.

**Why this priority**: Captures the "why" behind architecture, preventing agents from making technically valid but architecturally wrong decisions. Medium effort, high long-term strategic value.

**Independent Test**: Can be tested by adding decision nodes and verifying they appear in `context_for` results when their governed nodes are relevant.

**Acceptance Scenarios**:

1. **Given** a project with code comments containing `# DECISION:` or `// ADR-` markers, **When** the scanner runs, **Then** decision nodes are created with the decision text as metadata.
2. **Given** an initialized graph, **When** an agent manually adds a decision node with `codegiraffe_add_relation`, **Then** the decision is created with `constrains` edges to specified target nodes.
3. **Given** decision nodes that constrain nodes A and B, **When** `context_for` returns a subgraph containing node A, **Then** the constraining decision nodes are automatically included in the result.
4. **Given** decision nodes, **When** a decision supersedes a previous decision, **Then** a `supersedes` edge connects the new decision to the old one.
5. *(Deferred to future release)* **Given** a project with git history, **When** decision mining is enabled, **Then** commits containing keywords like "decided", "chose", "tradeoff" are surfaced as candidate decisions. *(Note: Git commit mining is out of scope for v0.11.0. ADR detection is limited to code comment markers.)*

---

### User Story 6 - Incremental Sync (Priority: P2)

In multi-agent workflows, agents actively modify files but the graph requires a full rescan to update. With incremental sync, agents can sync only changed files, keeping the graph current without the overhead of a full scan.

**Why this priority**: Eliminates a significant friction point in multi-agent workflows. The graph being stale is a correctness hazard.

**Independent Test**: Can be tested by modifying a single file, calling incremental sync with that file path, and verifying only that file's nodes/edges are updated.

**Acceptance Scenarios**:

1. **Given** an initialized graph, **When** an agent calls `codegiraffe_sync_files` with a list of changed file paths, **Then** only those files are rescanned and their nodes/edges updated.
2. **Given** a file that previously contributed nodes and edges, **When** that file is modified and synced incrementally, **Then** old edges from that file are removed before new edges are added (edge invalidation).
3. **Given** a file that is deleted, **When** `codegiraffe_sync_files` is called with that file path, **Then** all nodes and edges originating from that file are removed from the graph.
4. **Given** an incremental sync, **When** new import edges are detected, **Then** they are correctly added without duplicating existing edges.
5. **Given** manual annotations on nodes from the synced file, **When** incremental sync runs, **Then** manual annotations are preserved (not overwritten).

---

### User Story 7 - Convention Mining (Priority: P3)

When an AI agent creates new code, it needs to follow the project's existing patterns. The system analyzes clusters of same-type nodes to extract naming conventions, structural patterns, and common approaches, returning a compact "pattern brief" the agent can use as a template.

**Why this priority**: Agents produce more consistent, convention-following code. Reduces "fix the style" review cycles. Medium effort.

**Independent Test**: Can be tested by calling `codegiraffe_patterns` on a project with multiple endpoints or services and verifying it returns a coherent pattern summary.

**Acceptance Scenarios**:

1. **Given** a project with 3+ endpoint nodes, **When** an agent calls `codegiraffe_patterns` with `node_type="endpoint"`, **Then** the system returns a pattern brief describing common route naming, response format, and error handling patterns.
2. **Given** a project with 3+ service nodes, **When** an agent calls `codegiraffe_patterns` with `node_type="service"`, **Then** the system returns patterns for constructor style, dependency injection, and logging.
3. **Given** a project with patterns and one outlier, **When** `codegiraffe_patterns` is called, **Then** the outlier is flagged as an anti-pattern (deviating from the cluster norm).
4. **Given** a project with fewer than 3 nodes of a given type, **When** `codegiraffe_patterns` is called for that type, **Then** the system returns a message indicating insufficient data for pattern extraction.

---

### User Story 8 - Test Coverage Mapping (Priority: P3)

The system integrates with language-specific coverage tools to map test coverage back to graph nodes. Risk assessment incorporates coverage data, and test suggestions distinguish between "run these existing tests" and "you need to write new tests for these uncovered nodes."

**Why this priority**: Makes risk assessment and test suggestions dramatically more accurate. Medium effort.

**Independent Test**: Can be tested by providing coverage data and verifying it maps to graph nodes correctly.

**Acceptance Scenarios**:

1. **Given** a Python project with coverage.py output, **When** `codegiraffe_coverage` is called with the coverage data path, **Then** each node gets `_test_coverage` metadata with the coverage percentage for its source file.
2. **Given** coverage data mapped to nodes, **When** `risk_assessment` is computed, **Then** uncovered nodes receive elevated risk scores.
3. **Given** coverage data mapped to nodes, **When** `suggest_tests` is called, **Then** results distinguish "run existing tests" (covered nodes) from "write new tests" (uncovered nodes).
4. **Given** no coverage data available, **When** coverage-dependent features are queried, **Then** the system degrades gracefully to current behavior (no coverage information, no errors).

---

### User Story 9 - Graph Diffing for PR Review (Priority: P3)

A developer or CI pipeline wants to understand the architectural impact of a pull request — not just what code changed, but how the architecture graph changed. The system builds graphs at two git refs and computes the architectural delta.

**Why this priority**: Transforms code review from "what changed in the code" to "what changed in the architecture." Medium effort.

**Independent Test**: Can be tested by creating a git commit that adds/removes nodes and calling the diff tool to verify architectural changes are detected.

**Acceptance Scenarios**:

1. **Given** a git repository with two refs (base and head), **When** `codegiraffe_pr_diff` is called with those refs, **Then** the system returns a structured report of nodes added, removed, and modified.
2. **Given** a PR that introduces a new dependency cycle, **When** `codegiraffe_pr_diff` is called, **Then** the report flags the new cycle.
3. **Given** a PR that breaks an existing contract, **When** `codegiraffe_pr_diff` is called, **Then** the report flags the broken contract.
4. **Given** a PR with only formatting changes (no architectural impact), **When** `codegiraffe_pr_diff` is called, **Then** the report indicates zero architectural changes.

---

### User Story 10 - Dependency-Aware Task Ordering (Priority: P3)

An orchestrator has a list of tasks targeting different files and nodes. The system analyzes the dependency graph to produce a topologically sorted execution plan, identifying which tasks can run in parallel and which must be sequential.

**Why this priority**: Directly improves multi-agent orchestration efficiency. Reduces wasted work from ordering mistakes.

**Independent Test**: Can be tested by providing a list of tasks with file targets and verifying the returned order respects dependency constraints.

**Acceptance Scenarios**:

1. **Given** a list of tasks with target files, **When** `codegiraffe_order_tasks` is called, **Then** the system returns tasks sorted so that dependencies are resolved before dependents.
2. **Given** tasks A and B where A modifies a file that B imports, **When** `codegiraffe_order_tasks` is called, **Then** task A appears before task B.
3. **Given** tasks C and D with no graph overlap, **When** `codegiraffe_order_tasks` is called, **Then** C and D are marked as parallelizable.
4. **Given** tasks that touch the same file, **When** `codegiraffe_order_tasks` is called, **Then** those tasks are flagged as conflict zones requiring sequential execution.

---

### User Story 11 - Domain Model Abstraction (Priority: P3)

Developers and agents think at the domain level ("payments", "auth") but the graph operates at the code level (files, classes). The system maps domain concepts to clusters of graph nodes, allowing queries and impact analysis to operate at the domain level.

**Why this priority**: Bridges the abstraction gap between human intent and graph structure. Medium effort.

**Independent Test**: Can be tested by defining domain mappings and querying by domain name.

**Acceptance Scenarios**:

1. **Given** a project with naming patterns (e.g., files in `payments/` directory), **When** `codegiraffe_domains` is called with auto-inference enabled, **Then** domains are created based on directory structure and naming patterns.
2. **Given** defined domains, **When** `context_for` is called with a domain name as the task, **Then** nodes belonging to that domain are prioritized in results.
3. **Given** defined domains, **When** `blast_radius` is computed, **Then** the report groups impacted nodes by domain.
4. **Given** an agent manually defines a domain via `codegiraffe_domains`, **Then** the domain mapping is persisted and survives rescans.

---

### User Story 12 - CI/CD Integration (Priority: P3)

Development teams want automated architectural validation in their CI/CD pipelines. A GitHub Actions workflow runs graph validation on every PR, posts architectural impact summaries as PR comments, and optionally blocks merges that exceed impact thresholds.

**Why this priority**: Bridges the gap between architectural analysis and development workflow. Medium effort. High value for team adoption.

**Independent Test**: Can be tested by running the GitHub Actions workflow on a test repository and verifying PR comments are posted.

**Acceptance Scenarios**:

1. **Given** a GitHub Actions workflow configured for a repository, **When** a PR is opened, **Then** the workflow initializes or syncs the graph and runs `validate_changes` on the PR diff.
2. **Given** a PR with architectural impact, **When** the workflow runs, **Then** a comment is posted to the PR summarizing blast radius, contract status, and new cycles.
3. **Given** a configurable blast radius threshold, **When** a PR exceeds the threshold, **Then** the workflow reports a failure status on the PR check.
4. **Given** a PR with broken contracts, **When** the workflow runs, **Then** the PR comment highlights the broken contracts with severity.

---

### User Story 13 - Migration Planner (Priority: P4)

An agent is tasked with a large refactor (e.g., splitting a monolith, swapping a database). The system generates an ordered transformation plan that maintains consistency at each intermediate step, with rollback checkpoints and contract implications.

**Why this priority**: Large refactors are where AI agents fail most catastrophically. High effort but high strategic value.

**Independent Test**: Can be tested by describing a migration scenario and verifying the plan maintains valid intermediate states.

**Acceptance Scenarios**:

1. **Given** a graph and a migration description (e.g., "move reads from database_table:users to service:cache"), **When** `codegiraffe_migration_plan` is called, **Then** the system returns an ordered list of files/nodes to change.
2. **Given** a migration plan, **Then** each intermediate step maintains a valid import/dependency graph (no broken imports at any step).
3. **Given** a migration that affects contracts, **When** the plan is generated, **Then** contract implications are listed (which contracts break, when they can be restored).
4. **Given** a migration plan, **Then** rollback checkpoints are identified at safe intermediate states.

---

### Edge Cases

- What happens when `token_budget` is extremely small (e.g., 100 tokens)? System returns the single highest-relevance node or an informative message indicating the budget is too small for meaningful results.
- What happens when intent classification is ambiguous (e.g., "refactor and test the payment module")? System uses the first matching intent in priority order, or falls back to "modify" as the default.
- What happens when a CODEOWNERS file has conflicting ownership rules? System uses the most specific matching rule (last match wins, consistent with GitHub behavior).
- What happens when coverage data is stale or from a different branch? System uses the provided data with a staleness warning in metadata.
- What happens when `codegiraffe_pr_diff` is called on refs with no common ancestor? System returns an error with a descriptive message.
- What happens when `codegiraffe_order_tasks` receives tasks with circular dependencies? System detects the cycle and reports it, suggesting manual resolution.
- What happens when convention mining has mixed patterns (50/50 split)? System reports both patterns as alternatives rather than declaring a single convention.
- What happens when incremental sync encounters a file that was both renamed and modified? System treats it as a file deletion plus file addition, removing old nodes and creating new ones.
- What happens when a decision node's governed nodes are deleted? The decision node persists as an orphan with a warning flag.
- What happens when domain inference finds no meaningful clusters? System returns an empty domain list with guidance to create manual domains.

## Requirements *(mandatory)*

### Functional Requirements

**Token-Aware Context Budgets (Tier 1)**

- **FR-001**: System MUST accept a `token_budget` parameter on `context_for` specifying maximum estimated tokens for the response.
- **FR-002**: System MUST estimate token cost per node based on serialized size of the node plus its metadata and edges.
- **FR-003**: System MUST greedily fill the token budget with nodes ordered by descending relevance score.
- **FR-004**: System MUST return a `_token_estimate` field in every `context_for` response indicating the estimated token count.
- **FR-005**: System MUST accept a `detail_level` parameter ("summary", "standard", "detailed") controlling metadata verbosity per node.
- **FR-006**: When both `token_budget` and `max_nodes` are specified, system MUST apply whichever constraint is more restrictive.

**Intent-Aware Navigation (Tier 1)**

- **FR-007**: System MUST classify task intent from the task description using keyword heuristics (no external dependencies).
- **FR-008**: System MUST support at least 6 intent categories: create, modify, debug, refactor, delete, test.
- **FR-009**: System MUST adjust retrieval strategy based on classified intent: create → boost exemplar nodes of same type; debug → include upstream dependency chain (reverse BFS on imports/calls); refactor → include coupled files and cycles; delete → include blast radius and contract violations; test → include target deps and associated test files; modify → current behavior (unchanged).
- **FR-010**: System MUST return a `_retrieval_strategy` field indicating the classified intent and retrieval approach used.
- **FR-011**: System MUST fall back to "modify" intent (current behavior) when intent cannot be classified.

**Architectural Decision Records (Tier 1)**

- **FR-012**: System MUST support a `decision` node type in the graph schema.
- **FR-013**: System MUST support `constrains`, `motivated_by`, and `supersedes` edge types for decision nodes.
- **FR-014**: Scanner MUST detect `# DECISION:` and `// ADR-` comment markers and create decision nodes. Decision nodes MUST be linked via `constrains` edges to the specific nodes they govern (identified by node ID references in the decision text, or the nearest enclosing symbol if no explicit reference).
- **FR-015**: System MUST automatically include constraining decision nodes when `context_for` returns governed nodes.
- **FR-016**: System MUST support manual creation of decision nodes via `codegiraffe_add_relation` with `decision` node type and `constrains`/`motivated_by`/`supersedes` edge types.

**Convention Mining (Tier 1)**

- **FR-017**: System MUST provide a `codegiraffe_patterns` tool that analyzes clusters of same-type nodes.
- **FR-018**: System MUST extract naming conventions and structural patterns from node clusters via structural metadata analysis (naming patterns via regex, common attribute presence per FR-021a), not code content analysis.
- **FR-019**: System MUST require a minimum of 3 nodes of the given type before extracting patterns.
- **FR-020**: System MUST flag nodes that deviate from the cluster norm as potential anti-patterns, where convention is defined by >66% of nodes sharing a pattern.
- **FR-021**: System MUST return a compact "pattern brief" suitable for use as a template by AI agents.
- **FR-021a**: Pattern similarity MUST be measured via structural metadata (naming patterns via regex, common attribute presence), not code content analysis.

**Incremental Sync (Tier 2)**

- **FR-022**: System MUST provide a `codegiraffe_sync_files` tool that accepts a list of changed file paths.
- **FR-023**: System MUST rescan only the specified files, not the entire project.
- **FR-024**: System MUST invalidate (remove) old edges originating from changed files before adding new edges.
- **FR-025**: System MUST preserve manually annotated nodes and edges during incremental sync.
- **FR-026**: System MUST handle file deletions by removing all nodes and edges originating from deleted files.

**CI/CD Integration (Tier 2)**

- **FR-027**: System MUST provide a GitHub Actions workflow template for architectural validation on PRs.
- **FR-028**: Workflow MUST run `validate_changes` and `blast_radius` on the PR diff.
- **FR-029**: Workflow MUST post architectural impact summary as a PR comment.
- **FR-030**: Workflow MUST support configurable blast radius thresholds for pass/fail status.

**Graph Diffing for PR Review (Tier 2)**

- **FR-031**: System MUST provide a `codegiraffe_pr_diff` tool accepting a git ref range.
- **FR-032**: System MUST build graphs at both the base and head refs for comparison.
- **FR-033**: System MUST compute and report: nodes added/removed/modified, edges added/removed, contracts affected, new cycles introduced.
- **FR-034**: System MUST return a structured report suitable for posting as a PR comment.

**Confidence Scoring (Tier 3)**

- **FR-035**: Every edge in the graph MUST carry a `confidence` field (float, 0.0 to 1.0).
- **FR-036**: Scanner MUST assign confidence based on detection method (AST: 1.0, regex import: 0.9, inferred call: 0.6, contract inference: 0.5, manual: 1.0).
- **FR-037**: `context_for` MUST accept a `min_confidence` parameter to filter edges.
- **FR-038**: `blast_radius` MUST weight impact severity by edge confidence.

**Ownership Layer (Tier 3)**

- **FR-039**: System MUST support `owner`, `stability`, and `notes` metadata fields on nodes.
- **FR-040**: System MUST infer ownership from CODEOWNERS files when present.
- **FR-041**: System MUST provide a `codegiraffe_annotate` tool for manually setting ownership, stability, and notes.
- **FR-042**: `blast_radius` MUST flag nodes with different owners than the changed node as cross-team impact.

**Test Coverage Mapping (Tier 3)**

- **FR-043**: System MUST provide a `codegiraffe_coverage` tool that accepts coverage data paths.
- **FR-044**: System MUST map file-level coverage percentages to graph nodes via `_test_coverage` metadata.
- **FR-045**: Risk assessment MUST incorporate coverage data (uncovered nodes receive elevated risk).
- **FR-046**: `suggest_tests` MUST distinguish between "run existing tests" and "write new tests" based on coverage.

**Dependency-Aware Task Ordering (Tier 3)**

- **FR-047**: System MUST provide a `codegiraffe_order_tasks` tool accepting a list of tasks with target files or nodes.
- **FR-048**: System MUST return a topologically sorted execution plan respecting graph dependencies.
- **FR-049**: System MUST identify parallelizable task groups (tasks with no graph overlap).
- **FR-050**: System MUST flag conflict zones (tasks touching the same node or file).

**Domain Model Abstraction (Tier 3)**

- **FR-051**: System MUST provide a `codegiraffe_domains` tool for defining and querying domain concepts.
- **FR-052**: System MUST support auto-inference of domains from directory structure and naming patterns.
- **FR-053**: `context_for` MUST accept domain names as query input and prioritize domain-member nodes.
- **FR-054**: `blast_radius` MUST group impacted nodes by domain in its report.

**Migration Planner (Tier 3)**

- **FR-055**: System MUST provide a `codegiraffe_migration_plan` tool accepting from/to state descriptions.
- **FR-056**: System MUST return an ordered transformation plan where each step maintains valid dependencies.
- **FR-057**: System MUST identify rollback checkpoints at safe intermediate states.
- **FR-058**: System MUST report contract implications of the migration.

### Key Entities

- **Token Budget**: An estimated limit on the number of tokens an AI agent's context window can accommodate for graph results.
- **Intent**: A classified category of work (create, modify, debug, refactor, delete, test) that determines retrieval strategy.
- **Decision**: A recorded architectural choice with reasoning, linked to the graph nodes it governs.
- **Pattern Brief**: A compact summary of conventions extracted from clusters of same-type nodes.
- **Confidence**: A 0.0-1.0 score on each edge reflecting how reliably the relationship was detected.
- **Domain**: A named cluster of graph nodes representing a business concept (e.g., "Payments", "Auth").
- **Migration Plan**: An ordered sequence of transformations that transitions a codebase from one state to another while maintaining consistency.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: AI agents using `token_budget` parameter receive subgraphs that fit within their specified budget 100% of the time (no overflows).
- **SC-002**: Intent-aware retrieval returns demonstrably different subgraphs for different intents on the same codebase, with retrieval strategy documented in every response.
- **SC-003**: Confidence scoring is present on 100% of edges after a scan, with values varying by detection method.
- **SC-004**: Incremental sync of a single file completes in under 1 second for projects with up to 500 nodes (vs. full scan time).
- **SC-005**: `codegiraffe_pr_diff` correctly identifies all node and edge changes between two git refs with zero false negatives for additions and deletions.
- **SC-006**: `codegiraffe_order_tasks` produces execution plans where no task runs before its graph dependencies are satisfied.
- **SC-007**: All 13 features have dedicated test suites with at least 10 tests each (130+ new tests total).
- **SC-008**: Convention mining produces pattern briefs for node types with 3+ instances across all 9 supported languages.
- **SC-009**: Decision nodes from code comments are detected and included in `context_for` results when their governed nodes are relevant.
- **SC-010**: All new MCP tools (estimated 8-10 new tools) follow existing tool patterns and are accessible via the standard interface.
- **SC-011**: Token estimation and intent classification add less than 50ms overhead to `context_for` calls on graphs with up to 1000 nodes.
- **SC-012**: Dashboard renders new node types (decision) and edge confidence (opacity/thickness) without breaking existing visualization.

## Clarifications

### Session 2026-02-16

- Q: Should all 13 features ship as one release or be phased? → A: Phased by tier — P1 features as v0.11.0, P2 as v0.12.0, P3/P4 as v0.13.0.
- Q: How should existing stored graphs handle new schema fields (confidence, decision nodes)? → A: Default values on load — missing `confidence` defaults to 1.0 (trusted), missing node/edge types are ignored. No migration required.
- Q: Should the dashboard be updated for new features (decisions, confidence, domains)? → A: Yes, update dashboard incrementally per release. Decision nodes get distinct visual style. Confidence renders as edge opacity/thickness. Domains as visual grouping overlays.
- Q: What is acceptable performance overhead for token estimation and intent classification? → A: Less than 50ms overhead per `context_for` call. Both operations are lightweight (string length math, keyword matching).
- Q: How should convention mining measure pattern similarity and detect anti-patterns? → A: Structural similarity based on node metadata (naming patterns via regex, common attribute presence). Anti-pattern threshold: >66% of nodes sharing a pattern defines the convention; outliers are flagged.

### Analysis Remediation 2026-02-16

- ADR `constrains` edge targeting clarified: decisions target specific governed nodes (by node ID reference in text, or nearest enclosing symbol), not just the file module node. FR-014 updated.
- Git commit decision mining (US5 AS-5) deferred to future release. v0.11.0 ADR detection limited to code comment markers.
- Release strategy header fixed: ADRs removed from v0.12.0 (only in v0.11.0).
- FR-009 expanded with explicit per-intent retrieval strategies.
- FR-016 clarified to list specific edge types supported via `add_relation`.
- FR-018 clarified to reference FR-021a (structural metadata analysis).
- Contract tests added to all 8 new MCP tool test tasks per Constitution VI.
- `tested_by` edge creation added to US8 coverage mapper implementation.
- Quickstart.md corrected: Confidence scoring moved from v0.11.0 to v0.12.0.

## Assumptions

- Token estimation uses character count as a proxy for tokens (approximately 4 characters per token). This is a reasonable approximation across major model families.
- Intent classification uses keyword heuristics, not an external model. This keeps the tool dependency-free and fast. The keyword dictionary can be extended over time.
- CODEOWNERS file format follows the GitHub specification (gitignore-style patterns with owner columns).
- Coverage data is provided in standard formats: coverage.py JSON/XML for Python, Istanbul JSON/LCOV for JavaScript/TypeScript.
- Git operations for PR diffing use temporary worktrees to avoid disturbing the working directory.
- Convention mining samples the first 50 lines of each file for lightweight pattern extraction (configurable).
- Domain auto-inference uses directory names as the primary clustering signal, with node naming as secondary.
- Migration planning operates on the graph topology only — it does not generate actual code changes.
- The DiGraph limitation (one edge per source+target pair) persists for this release. Confidence scoring stores on the existing single edge. MultiDiGraph migration is deferred to a future version.
- Backward compatibility: existing stored graphs missing new fields (e.g., `confidence`) default to safe values on load (`confidence` defaults to 1.0). No schema migration required. New node/edge types are simply absent in older graphs.
- Token estimation and intent classification must add less than 50ms overhead per `context_for` call.
- Dashboard updates are incremental per release: v0.11.0 adds decision node styling, v0.12.0 adds confidence-based edge opacity and ownership overlays, v0.13.0 adds domain visual grouping.

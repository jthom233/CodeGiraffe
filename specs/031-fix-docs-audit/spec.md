# Feature Specification: Fix Documentation Audit Findings

**Feature Branch**: `031-fix-docs-audit`
**Created**: 2026-02-18
**Status**: Draft
**Input**: User description: "Fix all documentation inaccuracies found in comprehensive audit — stale Cytoscape.js references, wrong tool parameters, missing v0.14.0 content, CI workflow bugs"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Tool Parameter Docs Match Actual Signatures (Priority: P1)

An AI agent or developer reads the MCP tool documentation to learn how to call a tool. Every parameter name, type, default value, and accepted value must match the actual function signature in `server.py`. Wrong docs cause runtime errors.

**Why this priority**: Incorrect parameter documentation causes tools to fail at runtime. Users passing `"coverage.py"` instead of `"coverage_py"`, or using action `"create"` instead of `"add"`, get immediate errors with no indication the docs are wrong.

**Independent Test**: For each documented tool, compare every parameter's name, type, default, and allowed values against the actual `@mcp.tool()` function signature. Zero discrepancies.

**Acceptance Scenarios**:

1. **Given** a user reads `docs/tools/change-impact.md` for `codegiraffe_coverage`, **When** they pass `format="coverage_py"`, **Then** the tool accepts it (and `"auto"` default is documented)
2. **Given** a user reads `docs/tools/planning.md` for `codegiraffe_order_tasks`, **When** they pass tasks with `name` and `target_files` fields, **Then** the tool processes them correctly (not the old `id`/`description`/`dependencies` schema)
3. **Given** a user reads `docs/tools/planning.md` for `codegiraffe_domains`, **When** they use actions `"add"` and `"remove"`, **Then** the tool works (not the stale `"create"`/`"update"`)
4. **Given** a user reads `docs/tools/core.md` for `codegiraffe_sync_files`, **When** they see the `file_paths` parameter type, **Then** it shows `str` (comma-separated or JSON array), not `list[str]`
5. **Given** a user reads `docs/tools/change-impact.md` for `codegiraffe_pr_diff`, **When** they see `head_ref`, **Then** it shows as optional with default `"HEAD"`

---

### User Story 2 - Dashboard Documentation Reflects Sigma.js v3 (Priority: P1)

A developer reads the dashboard documentation to understand the visualization technology, available layouts, features, and styling. All references must reflect the current Sigma.js v3 + Graphology implementation, not the replaced Cytoscape.js.

**Why this priority**: The entire dashboard.md describes a technology stack that no longer exists. Every claim about layouts, edge styles, node shapes, and interaction patterns is wrong.

**Independent Test**: Read `docs/dashboard.md`, `docs/architecture.md`, `docs/tools/core.md`, `README.md`, and `server.py` docstrings. Zero references to Cytoscape.js. All layout names, counts, edge style descriptions, and interaction patterns match `dashboard.py` code.

**Acceptance Scenarios**:

1. **Given** a user reads `docs/dashboard.md`, **When** they look for the rendering technology, **Then** it says Sigma.js v3 + Graphology (not Cytoscape.js)
2. **Given** a user reads `docs/dashboard.md`, **When** they check available layouts, **Then** 7 layouts are listed: original, force, circular, grid, concentric, breadthfirst, random
3. **Given** a user reads `docs/dashboard.md`, **When** they check edge styling, **Then** it describes color differentiation only (not dashed/solid/dotted styles that don't exist in Sigma.js)
4. **Given** a user reads `docs/dashboard.md`, **When** they check node shapes, **Then** it describes circular nodes with color coding (not hexagonal shapes)
5. **Given** a user reads `docs/dashboard.md`, **When** they check interaction features, **Then** double-click subgraph focus is not listed (it's not implemented)
6. **Given** a developer reads `server.py` `codegiraffe_dashboard` docstring, **When** they check, **Then** it says Sigma.js (not Cytoscape.js)

---

### User Story 3 - Version History and Counts Are Current (Priority: P2)

A user or contributor reads the README, CLAUDE.md, or roadmap to understand the project's current state — version, test count, tool count, and module listing. All numbers and listings must be accurate.

**Why this priority**: Stale numbers erode trust and cause confusion. Contributors may think tests are missing or features don't exist.

**Independent Test**: Compare every numeric claim (test count, tool category counts) and every file listing against actual `pytest --co` output, `@mcp.tool()` count, and `ls` of source files.

**Acceptance Scenarios**:

1. **Given** a user reads `README.md`, **When** they check the test count, **Then** it shows the current count (1452+)
2. **Given** a user reads `README.md`, **When** they check Core tool count, **Then** it says 8 (not 7)
3. **Given** a user reads `CLAUDE.md`, **When** they check test count, **Then** it shows the current count (1452+)
4. **Given** a user reads `docs/roadmap.md`, **When** they look for v0.14.0, **Then** a complete entry exists describing the Sigma.js migration
5. **Given** a user reads `CLAUDE.md` or `docs/architecture.md`, **When** they check the module listing, **Then** `layout.py`, `dashboard_server.py`, and `assets/` are included

---

### User Story 4 - CI Workflows Execute Without Errors (Priority: P2)

A maintainer pushes code and CI runs. The `codegiraffe-pr.yml` workflow must import the correct function names and not depend on unavailable packages.

**Why this priority**: A broken CI workflow means architectural review on PRs silently fails, removing a quality gate.

**Independent Test**: Read `codegiraffe-pr.yml` and verify every Python import matches actual function names in the codebase.

**Acceptance Scenarios**:

1. **Given** a PR is opened, **When** `codegiraffe-pr.yml` runs, **Then** `from codegiraffe.query import suggest_tests` succeeds (not `suggest_tests_for_changes`)

---

### User Story 5 - Optional Extras Are Documented (Priority: P3)

A user wants to install all optional features. The getting-started guide lists all available extras.

**Why this priority**: The `layout` extra exists in pyproject.toml but isn't mentioned anywhere in docs. Users miss out on ForceAtlas2 layout.

**Independent Test**: Every optional dependency group in pyproject.toml is documented in `docs/getting-started.md`.

**Acceptance Scenarios**:

1. **Given** a user reads `docs/getting-started.md`, **When** they check optional extras, **Then** `layout` (`fa2>=0.1`) is listed alongside embeddings, neo4j, and ast

---

### Edge Cases

- What happens when a tool parameter accepts both `str` and `list[str]` in docs vs code? Document the actual wire type (always `str` for MCP tools).
- How do we handle retrieval_strategy docs where the field semantics changed from scoring-backend to intent-classification? Accurately document the actual values.
- What about the `codegiraffe_patterns` output format that changed from multi-cluster to single-cluster? Document actual behavior.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `docs/tools/change-impact.md` MUST list `codegiraffe_coverage` format values as `"coverage_py"`, `"istanbul"`, `"lcov"`, `"auto"` with `"auto"` as default
- **FR-002**: `docs/tools/planning.md` MUST document `codegiraffe_order_tasks` task schema as `name` + `target_files` (not `id`/`description`/`dependencies`)
- **FR-003**: `docs/tools/planning.md` MUST document `codegiraffe_domains` actions as `"list"`, `"infer"`, `"add"`, `"remove"` (not `"create"`/`"update"`)
- **FR-004**: `docs/tools/planning.md` MUST document `codegiraffe_domains` `node_ids` as `str` (comma-separated), not `list[str]`
- **FR-005**: `docs/tools/planning.md` MUST document `codegiraffe_migration_plan` `target_nodes` as `str | None` (JSON array string), not `list[str]`
- **FR-006**: `docs/tools/core.md` MUST document `codegiraffe_sync_files` `file_paths` as `str`, not `list[str]`
- **FR-007**: `docs/tools/change-impact.md` MUST document `codegiraffe_pr_diff` `head_ref` as optional with default `"HEAD"` and undocumented `scanner_mode` param
- **FR-008**: `docs/tools/change-impact.md` MUST document `codegiraffe_coverage` `format` as optional with default `"auto"`
- **FR-009**: `.github/workflows/codegiraffe-pr.yml` MUST import `suggest_tests` (not `suggest_tests_for_changes`)
- **FR-010**: All references to "Cytoscape.js" in `docs/dashboard.md`, `docs/architecture.md`, `docs/tools/core.md`, `README.md`, and `server.py` docstrings MUST be replaced with "Sigma.js v3"
- **FR-011**: `docs/dashboard.md` MUST list 7 layouts: original, force, circular, grid, concentric, breadthfirst, random
- **FR-012**: `docs/dashboard.md` MUST describe edges as color-differentiated only (remove dashed/solid/dotted claims)
- **FR-013**: `docs/dashboard.md` MUST describe nodes as circular with color coding (remove hexagonal shape claims)
- **FR-014**: `docs/dashboard.md` MUST remove "double-click for subgraph focus" feature claim
- **FR-015**: `docs/dashboard.md` MUST document the `layout` optional extra (`fa2>=0.1`) for server-side ForceAtlas2
- **FR-016**: `README.md` test count MUST show current count (1452+)
- **FR-017**: `CLAUDE.md` test count MUST show current count (1452+)
- **FR-018**: `README.md` Core tool category count MUST be 8 (not 7)
- **FR-019**: `docs/roadmap.md` MUST include a v0.14.0 entry documenting Sigma.js v3 migration, layout.py, dashboard_server.py, and layout extra
- **FR-020**: `CLAUDE.md` and `docs/architecture.md` module listings MUST include `layout.py`, `dashboard_server.py`, and `assets/`
- **FR-021**: `docs/getting-started.md` MUST document the `layout` optional extra
- **FR-022**: `docs/embeddings.md` and `docs/tools/context-and-analysis.md` MUST document `_retrieval_strategy` actual values: `create`, `debug`, `refactor`, `delete`, `test`, `modify`
- **FR-023**: `docs/tools/context-and-analysis.md` MUST accurately describe `codegiraffe_blast_radius` return as markdown text (not JSON)
- **FR-024**: `docs/tools/context-and-analysis.md` MUST remove `"coverage"` field from `codegiraffe_risk_assessment` example
- **FR-025**: `docs/tools/context-and-analysis.md` MUST accurately describe `codegiraffe_patterns` output as single-cluster with `naming_pattern`, `exemplar`, `common_attributes`, `outliers`
- **FR-026**: `docs/edge-confidence.md` MUST include `contains=1.0` in the confidence table
- **FR-027**: `server.py` `codegiraffe_dashboard` docstring MUST say "Sigma.js v3" (not "Cytoscape.js")

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Zero discrepancies between documented tool parameters and actual function signatures across all 37 tools
- **SC-002**: Zero references to "Cytoscape.js" in any documentation file or production code docstring
- **SC-003**: All numeric claims (test count, tool category counts) match actual values within a 5% tolerance
- **SC-004**: Every source file in `src/codegiraffe/` is listed in at least one module listing (CLAUDE.md or architecture.md)
- **SC-005**: Every optional dependency group in `pyproject.toml` is documented in getting-started.md
- **SC-006**: `codegiraffe-pr.yml` Python imports resolve against the actual codebase without ImportError
- **SC-007**: `docs/roadmap.md` has an entry for every version from v0.2.0 through the current pyproject.toml version

## Assumptions

- Test count of 1452 is current as of this spec. The exact number may change if tests are added before this fix lands; using "1452+" format accommodates this.
- The double-click subgraph focus feature is intentionally not implemented in Sigma.js (not a bug to fix, just a doc claim to remove).
- The `codegiraffe-pr.yml` workflow's `pip install codegiraffe` step is valid since the package is published to PyPI.
- No code behavior changes are needed — this is purely a documentation and docstring accuracy fix.

# MCP Tool Contracts: Graph Intelligence

**Branch**: `011-graph-intelligence` | **Date**: 2026-02-16

## Modified Tools

### codegiraffe_context_for (enhanced)

**New Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `token_budget` | int | 0 (disabled) | Max estimated tokens for response |
| `detail_level` | str | "standard" | "summary" / "standard" / "detailed" |
| `min_confidence` | float | 0.0 | Filter edges below this confidence |

**New Response Fields (in JSON output):**

| Field | Type | Description |
|-------|------|-------------|
| `_token_estimate` | int | Estimated token count of response |
| `_retrieval_strategy` | str | Intent classified + approach used |

**Behavior Changes:**
- When `token_budget > 0`: greedy fill by relevance, cap at budget
- When both `token_budget` and `max_nodes` set: most restrictive wins
- Intent auto-classified from `task` description, adjusts retrieval
- `_retrieval_strategy` always present in response

### codegiraffe_blast_radius (enhanced)

**New Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `cross_team_impact` | list | Nodes with different `owner` than changed node |
| `domain_groups` | dict | Impact grouped by domain |

**Behavior Changes:**
- Severity weighted by edge confidence
- Cross-team impact flagged when ownership annotations present
- Domain grouping when domains are defined

### codegiraffe_risk_assessment (enhanced)

**Behavior Changes:**
- Risk score incorporates test coverage when `_test_coverage` metadata present
- Uncovered nodes receive elevated risk multiplier (1.5x)

### codegiraffe_suggest_tests (enhanced)

**New Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `coverage_status` | str | "covered" / "uncovered" / "unknown" |

**Behavior Changes:**
- Distinguishes "run existing" vs "write new tests" when coverage data available

## New Tools

### codegiraffe_patterns

**Parameters:**

| Parameter | Type | Default | Required | Description |
|-----------|------|---------|----------|-------------|
| `project_path` | str | — | yes | Project directory |
| `node_type` | str | — | yes | Node type to analyze (e.g., "endpoint", "service") |
| `min_cluster` | int | 3 | no | Minimum nodes required for analysis |

**Returns:** JSON pattern brief with naming conventions, common attributes, outliers, and exemplar.

**Error:** Returns message if fewer than `min_cluster` nodes of the given type exist.

### codegiraffe_annotate

**Parameters:**

| Parameter | Type | Default | Required | Description |
|-----------|------|---------|----------|-------------|
| `project_path` | str | — | yes | Project directory |
| `node_id` | str | — | yes | Node to annotate |
| `owner` | str | None | no | Team/person owner |
| `stability` | str | None | no | "stable" / "experimental" / "deprecated" / "legacy" |
| `notes` | str | None | no | Free-text annotation |

**Returns:** Confirmation message with updated node.

### codegiraffe_sync_files

**Parameters:**

| Parameter | Type | Default | Required | Description |
|-----------|------|---------|----------|-------------|
| `project_path` | str | — | yes | Project directory |
| `file_paths` | list[str] | — | yes | List of changed file paths |
| `scanner_mode` | str | "regex" | no | "regex" or "ast" |

**Returns:** Summary of nodes/edges added, removed, and preserved.

### codegiraffe_coverage

**Parameters:**

| Parameter | Type | Default | Required | Description |
|-----------|------|---------|----------|-------------|
| `project_path` | str | — | yes | Project directory |
| `coverage_path` | str | — | yes | Path to coverage data file |
| `format` | str | "auto" | no | "auto" / "coverage_py" / "istanbul" / "lcov" |

**Returns:** Summary of nodes mapped to coverage data.

### codegiraffe_pr_diff

**Parameters:**

| Parameter | Type | Default | Required | Description |
|-----------|------|---------|----------|-------------|
| `project_path` | str | — | yes | Project directory |
| `base_ref` | str | — | yes | Base git ref (e.g., "main") |
| `head_ref` | str | "HEAD" | no | Head git ref |

**Returns:** Structured architectural diff report (JSON).

### codegiraffe_order_tasks

**Parameters:**

| Parameter | Type | Default | Required | Description |
|-----------|------|---------|----------|-------------|
| `project_path` | str | — | yes | Project directory |
| `tasks` | str | — | yes | JSON array of tasks with `name` and `target_files` fields |

**Returns:** Execution plan with ordered tasks, parallel groups, and conflict zones (JSON).

### codegiraffe_domains

**Parameters:**

| Parameter | Type | Default | Required | Description |
|-----------|------|---------|----------|-------------|
| `project_path` | str | — | yes | Project directory |
| `action` | str | "list" | no | "list" / "infer" / "add" / "remove" |
| `name` | str | None | no | Domain name (for add/remove) |
| `node_ids` | str | None | no | JSON array of node IDs (for add) |

**Returns:** List of domains with member counts, or confirmation of add/remove.

### codegiraffe_migration_plan

**Parameters:**

| Parameter | Type | Default | Required | Description |
|-----------|------|---------|----------|-------------|
| `project_path` | str | — | yes | Project directory |
| `description` | str | — | yes | Migration description (e.g., "move reads from DB to cache") |
| `target_nodes` | str | None | no | JSON array of node IDs to migrate |

**Returns:** Ordered migration plan with steps, checkpoints, and contract implications (JSON).

## Tool Count Summary

| Release | New Tools | Modified Tools | Total |
|---------|-----------|---------------|-------|
| v0.11.0 | 1 (patterns) | 1 (context_for) | 29 |
| v0.12.0 | 2 (annotate, sync_files) | 2 (blast_radius, context_for) | 31 |
| v0.13.0 | 5 (coverage, pr_diff, order_tasks, domains, migration_plan) | 2 (risk_assessment, suggest_tests) | 36 |

# Implementation Plan: Graph Intelligence

**Branch**: `011-graph-intelligence` | **Date**: 2026-02-16 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/011-graph-intelligence/spec.md`

## Summary

Add 13 features to CodeGiraffe across 3 phased releases (v0.11.0, v0.12.0, v0.13.0) that transform the architecture knowledge graph from a static structural map into an intelligent context engine for AI agents. Core enhancements to `context_for` (token budgets, intent-aware retrieval) address the #1 challenge in AI context engineering. Supporting features add confidence scoring, architectural decision records, convention mining, incremental sync, ownership tracking, test coverage mapping, graph diffing, task ordering, domain abstraction, CI/CD integration, and migration planning. Total: 8 new MCP tools, 5 modified tools, ~130+ new tests.

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: FastMCP (mcp[cli] >= 1.2.0), NetworkX >= 3.0, Pydantic v2
**Storage**: JSON + SQLite + Neo4j (all via StorageBackend protocol)
**Testing**: pytest >= 8.0, pytest-asyncio >= 0.23
**Target Platform**: Any OS with Python 3.11+ and MCP client
**Project Type**: Single Python package (src/codegiraffe/)
**Performance Goals**: <50ms overhead for token estimation + intent classification per `context_for` call; <1s incremental sync for single file on 500-node graphs
**Constraints**: DiGraph limitation persists (one edge per source+target pair); no new required dependencies
**Scale/Scope**: 13 features, 59 functional requirements, ~130+ new tests across 3 releases

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. MCP-Native | PASS | All 8 new tools exposed via `@mcp.tool()`. AI agents are primary consumers. |
| II. Graph-First | PASS | All features operate on the directed graph. New node/edge types extend schema. |
| III. Beyond-AST | PASS | ADRs capture reasoning (not derivable from AST). Ownership captures tribal knowledge. Domains capture business context. |
| IV. Context Efficiency | PASS | Token budgets directly optimize context. Intent-aware retrieval reduces irrelevant results. `min_confidence` filters weak signals. |
| V. Incremental & Non-Destructive | PASS | `codegiraffe_sync_files` enables incremental updates. Manual annotations preserved. `confidence` defaults to 1.0 for backward compat. |
| VI. Test-First | PASS | 130+ new tests planned. TDD enforced per Constitution. |
| VII. Simplicity | PASS | No new required dependencies. Keyword heuristics over LLM classification. Character count over tiktoken. Minimal new modules (4 new files). |

**Post-Phase 1 Re-Check:**

| Principle | Status | Notes |
|-----------|--------|-------|
| I. MCP-Native | PASS | 8 new tools + 5 modified tools, all MCP-accessible |
| II. Graph-First | PASS | 2 new node types, 5 new edge types, confidence on edges |
| III. Beyond-AST | PASS | ADRs, ownership, domains — all beyond-AST knowledge |
| IV. Context Efficiency | PASS | Token budgets + intent + confidence filtering |
| V. Incremental & Non-Destructive | PASS | Incremental sync + backward-compatible schema |
| VI. Test-First | PASS | Test files planned per feature |
| VII. Simplicity | PASS | 4 new files, 0 new dependencies |

## Project Structure

### Documentation (this feature)

```text
specs/011-graph-intelligence/
├── plan.md              # This file
├── spec.md              # Feature specification (59 FRs, 13 user stories)
├── research.md          # Phase 0 output (12 research decisions)
├── data-model.md        # Phase 1 output (schema changes, entities)
├── quickstart.md        # Phase 1 output (dev setup, implementation order)
├── contracts/
│   └── mcp-tools.md     # Phase 1 output (tool signatures, parameters)
├── checklists/
│   └── requirements.md  # Spec quality checklist
└── tasks.md             # Phase 2 output (created by /speckit.tasks)
```

### Source Code (repository root)

```text
src/codegiraffe/
├── graph.py              # MODIFIED: Edge.confidence field
├── schema.py             # MODIFIED: DECISION node type, 5 new edge types
├── query.py              # MODIFIED: token budgets, intent classification, confidence filtering, decision inclusion, domain queries, task ordering
├── scanner.py            # MODIFIED: confidence assignment per stage, ADR detection, ownership inference
├── server.py             # MODIFIED: enhanced context_for/blast_radius/risk/suggest_tests; new tools (patterns, annotate, sync_files, coverage, pr_diff, order_tasks, domains, migration_plan)
├── dashboard.py          # MODIFIED: decision node styling, confidence opacity, domain grouping
├── patterns.py           # NEW: convention mining logic
├── ownership.py          # NEW: CODEOWNERS parsing, git blame inference
├── graph_diff.py         # NEW: graph comparison at different git refs
├── coverage_mapper.py    # NEW: coverage.py/Istanbul parsing, node mapping
├── domains.py            # NEW: domain inference and management
└── migration.py          # NEW: migration plan generation

tests/
├── test_confidence.py        # NEW: edge confidence scoring
├── test_token_budget.py      # NEW: token-aware context budgets
├── test_intent_navigation.py # NEW: intent classification + retrieval
├── test_decisions.py         # NEW: ADR detection and context inclusion
├── test_patterns.py          # NEW: convention mining
├── test_ownership.py         # NEW: CODEOWNERS + git blame inference
├── test_incremental_sync.py  # NEW: codegiraffe_sync_files
├── test_graph_diff.py        # NEW: PR diffing
├── test_coverage_mapper.py   # NEW: coverage data mapping
├── test_task_ordering.py     # NEW: dependency-aware task ordering
├── test_domains.py           # NEW: domain inference and queries
├── test_migration.py         # NEW: migration plan generation
└── ... (existing 33 test files)
```

**Structure Decision**: Follows existing flat `src/codegiraffe/` structure. 6 new source modules, 12 new test files. No sub-packages needed — each new module is a focused, single-responsibility file under 500 lines.

## Release Phasing

### v0.11.0 — Intelligent Context (P1 features)

| Feature | Files | New Tests | New Tools |
|---------|-------|-----------|-----------|
| Token-aware context budgets | query.py, server.py | ~15 | 0 (enhances context_for) |
| Intent-aware navigation | query.py, server.py | ~15 | 0 (enhances context_for) |
| ADR detection + context inclusion | schema.py, scanner.py, query.py, server.py, dashboard.py | ~15 | 0 (uses add_relation) |
| Convention mining | patterns.py, server.py | ~12 | 1 (codegiraffe_patterns) |
| **Subtotal** | 7 files modified, 1 new | ~57 | 1 new, 1 modified |

### v0.12.0 — Graph Enrichment (P2 features)

| Feature | Files | New Tests | New Tools |
|---------|-------|-----------|-----------|
| Confidence scoring | graph.py, scanner.py, query.py, server.py, dashboard.py | ~15 | 0 (enhances existing) |
| Ownership layer | ownership.py, scanner.py, server.py, query.py | ~12 | 1 (codegiraffe_annotate) |
| Incremental sync | scanner.py, server.py, graph.py | ~15 | 1 (codegiraffe_sync_files) |
| **Subtotal** | 6 files modified, 1 new | ~42 | 2 new, 3 modified |

### v0.13.0 — Advanced Analysis (P3/P4 features)

| Feature | Files | New Tests | New Tools |
|---------|-------|-----------|-----------|
| Test coverage mapping | coverage_mapper.py, server.py, query.py | ~12 | 1 (codegiraffe_coverage) |
| Graph diffing for PR review | graph_diff.py, server.py | ~12 | 1 (codegiraffe_pr_diff) |
| Dependency-aware task ordering | query.py, server.py | ~10 | 1 (codegiraffe_order_tasks) |
| Domain model abstraction | domains.py, server.py, query.py | ~12 | 1 (codegiraffe_domains) |
| CI/CD integration | .github/workflows/ | ~5 | 0 (workflow file) |
| Migration planner | migration.py, server.py | ~12 | 1 (codegiraffe_migration_plan) |
| **Subtotal** | 4 files modified, 4 new | ~63 | 5 new, 2 modified |

### Totals

| Metric | v0.11.0 | v0.12.0 | v0.13.0 | Total |
|--------|---------|---------|---------|-------|
| New tests | ~57 | ~42 | ~63 | ~162 |
| New tools | 1 | 2 | 5 | 8 |
| Modified tools | 1 | 3 | 2 | 6 |
| New source files | 1 | 1 | 4 | 6 |
| MCP tool total | 29 | 31 | 36 | 36 |

## Complexity Tracking

No constitution violations. No complexity justifications needed.

| Consideration | Decision | Rationale |
|--------------|----------|-----------|
| Token estimation method | char_count / 4 | Avoids tiktoken dependency (Principle VII) |
| Intent classification | Keyword heuristics | No LLM dependency (Principle VII) |
| Confidence storage | Edge model field | First-class property, typed, filterable |
| New modules | 6 flat files | Follows existing structure, no sub-packages |
| Dashboard updates | Incremental per release | Matches existing pattern |

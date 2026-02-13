<!--
  Sync Impact Report
  Version change: 0.0.0 → 1.0.0
  Added sections: All (initial constitution)
  Templates requiring updates: ✅ spec-template.md (no changes needed), ✅ plan-template.md (no changes needed), ✅ tasks-template.md (no changes needed)
  Follow-up TODOs: None
-->

# Code Giraffe Constitution

## Core Principles

### I. MCP-Native

Code Giraffe is an MCP (Model Context Protocol) server. Every capability MUST be
exposed as an MCP tool callable by AI agents. The primary consumer of the
architecture knowledge graph is AI, not humans. Human-readable output (e.g.,
visualizations) is secondary and MUST NOT drive architectural decisions.

### II. Graph-First

All architecture knowledge MUST be modeled as a directed graph with typed nodes
and typed edges. Nodes represent architectural entities (services, endpoints,
tables, queues, env vars, etc.). Edges represent relationships (calls, reads,
writes, publishes, consumes, depends-on, etc.). The graph schema MUST be
extensible — users can define custom node and edge types without modifying core
code.

### III. Beyond-AST Knowledge

Code Giraffe MUST capture relationships that static code analysis (AST, imports,
type systems) cannot see. This includes but is not limited to: runtime coupling
(DI, reflection, dynamic imports, plugin registries), data flow and side effects
(DB reads/writes, cache dependencies, idempotency), cross-system contracts (API
endpoints to frontend components, event schemas across services), and operational
context (env vars, secrets, permissions, feature flags, ownership). If a
relationship can already be derived by an IDE or language server, Code Giraffe
SHOULD NOT duplicate it unless doing so adds architectural context.

### IV. Context Efficiency

Every MCP tool MUST return the minimal relevant context for the task at hand. The
graph exists to reduce token usage, not increase it. Tools MUST support scoped
queries (e.g., "give me only the subgraph relevant to this endpoint") and MUST
NOT return the full graph when a subset suffices. Ranked hotspot scoring MUST
allow agents to focus on the most impactful areas first.

### V. Incremental & Non-Destructive

The graph MUST support incremental updates — adding, modifying, or removing
nodes and edges without requiring a full rescan. All mutations MUST be
non-destructive by default (soft deletes, versioned edges). The graph MUST be
rebuildable from source at any time via a full scan, but day-to-day operation
MUST NOT require it.

### VI. Test-First (NON-NEGOTIABLE)

TDD is mandatory. Tests MUST be written before implementation. The Red-Green-
Refactor cycle MUST be strictly enforced. Every MCP tool MUST have contract tests
verifying its input/output schema. Integration tests MUST validate graph
consistency after mutations.

### VII. Simplicity

Start simple. Use JSON files for graph storage in v1. Use Python as the
implementation language. No external databases, no complex infrastructure. Follow
YAGNI — do not build for hypothetical future requirements. Complexity MUST be
justified against this constitution before introduction.

## Technology Stack

- **Language**: Python 3.11+
- **MCP Framework**: Official MCP Python SDK
- **Storage**: JSON files (v1), with a clean storage abstraction layer for future
  backends (SQLite, Neo4j)
- **Testing**: pytest with contract and integration test suites
- **Package Management**: uv
- **Graph Analysis**: NetworkX for in-memory graph operations
- **Target Platform**: Any OS that supports Python and MCP clients

## Development Workflow

- Feature branches from main, never commit directly to main
- Git worktrees for parallel feature development
- Atomic commits with conventional commit messages
- All PRs MUST pass tests and lint before merge
- Code review via spec-kit analyze + checklist before merge

## Governance

This constitution supersedes all other development practices for the Code
Giraffe project. Amendments require: (1) documented rationale, (2) user
approval, (3) a migration plan for existing code if the change is breaking.
All code changes MUST be verified against these principles before commit.
Complexity MUST be justified. When in doubt, choose the simpler approach.

**Version**: 1.0.0 | **Ratified**: 2026-02-12 | **Last Amended**: 2026-02-12

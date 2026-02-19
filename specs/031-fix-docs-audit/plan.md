# Implementation Plan: Fix Documentation Audit Findings

**Branch**: `031-fix-docs-audit` | **Date**: 2026-02-18 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/031-fix-docs-audit/spec.md`

## Summary

Fix 30 documentation inaccuracies found during a comprehensive audit. The v0.14.0 Sigma.js migration left stale Cytoscape.js references across 6+ files. Multiple tool parameter docs have wrong types, action names, schemas, and return value descriptions. Test counts and module listings are stale. One CI workflow has a broken Python import.

## Technical Context

**Language/Version**: Python 3.11+ (docstring fix in server.py), Markdown (all doc files)
**Primary Dependencies**: N/A (documentation-only changes)
**Storage**: N/A
**Testing**: pytest >= 8.0 (verify existing tests still pass after docstring change)
**Target Platform**: N/A
**Project Type**: single
**Performance Goals**: N/A
**Constraints**: No code behavior changes — only docs, docstrings, and CI workflow fixes
**Scale/Scope**: 15 files across docs/, root, .github/, and 1 source file (server.py docstring)

## Constitution Check

- I. MCP-Native: N/A (no tool behavior changes)
- II. Graph-First: N/A
- III. Beyond-AST: N/A
- IV. Context Efficiency: N/A
- V. Incremental & Non-Destructive: Satisfied — no code changes, only accuracy fixes
- VI. Test-First: Satisfied — existing tests must still pass after server.py docstring change
- VII. Simplicity: Satisfied — minimal targeted edits, no new abstractions

## Project Structure

### Documentation (this feature)

```text
specs/031-fix-docs-audit/
├── spec.md              # Feature specification (27 functional requirements)
├── plan.md              # This file
├── tasks.md             # Task list
└── checklists/
    └── requirements.md  # Spec quality checklist
```

### Files to Modify

```text
# Critical (wrong parameter docs causing runtime errors)
docs/tools/change-impact.md     # FR-001, FR-007, FR-008
docs/tools/planning.md          # FR-002, FR-003, FR-004, FR-005
docs/tools/core.md              # FR-006, FR-010
.github/workflows/codegiraffe-pr.yml  # FR-009

# High (wrong technology references)
docs/dashboard.md               # FR-010, FR-011, FR-012, FR-013, FR-014, FR-015
docs/architecture.md            # FR-010, FR-020
docs/tools/context-and-analysis.md  # FR-022, FR-023, FR-024, FR-025
docs/embeddings.md              # FR-022
src/codegiraffe/server.py       # FR-027 (docstring only)

# Medium (stale counts and missing content)
README.md                       # FR-010, FR-016, FR-018
CLAUDE.md                       # FR-017, FR-020
docs/roadmap.md                 # FR-019
docs/getting-started.md         # FR-021
docs/edge-confidence.md         # FR-026
```

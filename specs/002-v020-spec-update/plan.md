# Implementation Plan: Code Giraffe v0.2.0

**Branch**: `002-v020-spec-update` | **Date**: 2026-02-13 | **Spec**: `specs/002-v020-spec-update/spec.md`
**Input**: Feature specification from `/specs/002-v020-spec-update/spec.md`

## Summary

Code Giraffe v0.2.0 extends the core MCP architecture knowledge graph server with:
multi-language scanning (Python, TypeScript, Go, Rust, Java) via a pluggable recognizer
registry, SQLite storage backend, graph visualization export (Mermaid + D3.js),
embedding-based context scoring via sentence-transformers, enhanced drift detection
with rename tracking and edge drift analysis, and multi-agent coordination tools
for concurrent AI-assisted development. All features are implemented and passing
231 tests.

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: mcp[cli] (FastMCP), NetworkX ≥3.0, Pydantic ≥2.0
**Optional Dependencies**: sentence-transformers ≥2.0 (for embedding-based scoring)
**Storage**: JSON files (.codegiraffe/graph.json) + SQLite (.codegiraffe/graph.db)
**Testing**: pytest ≥8.0, pytest-asyncio ≥0.23 — 231 tests passing
**Target Platform**: Any OS with Python 3.11+ and MCP-compatible client
**Project Type**: Single Python package (src/codegiraffe/)
**Performance Goals**: <2s graph queries on 500-node graphs, <5s init scans
**Constraints**: No external databases required, optional deps degrade gracefully
**Scale/Scope**: Single-repo graphs, 5 language recognizers, 11 MCP tools

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. MCP-Native | PASS | All 11 features exposed as @mcp.tool() decorators |
| II. Graph-First | PASS | NetworkX DiGraph with typed nodes/edges, extensible types |
| III. Beyond-AST | PASS | Core purpose — runtime coupling, data flows, cross-system contracts, operational context |
| IV. Context Efficiency | PASS | Scoped queries, depth limits, hotspot ranking, embedding-based scoring |
| V. Incremental & Non-Destructive | PASS | Sync preserves manual=True annotations, soft merge on rescan |
| VI. Test-First | PASS | 231 tests: contract tests for all tools, integration tests, unit tests per module |
| VII. Simplicity | PASS | JSON default storage, regex scanning (not AST), SQLite as optional upgrade, YAGNI |

**Complexity Justification for v0.2.0 additions:**
- SQLite backend: Justified — large graphs (1000+ nodes) need indexed queries. StorageBackend protocol keeps it optional.
- Embedding scoring: Justified — keyword matching misses semantic relationships. Optional dependency with graceful fallback.
- Multi-agent coordination: Justified — core use case involves orchestrator + subagents. File-based (no external deps).

## Project Structure

### Documentation (this feature)

```text
specs/002-v020-spec-update/
├── plan.md              # This file
├── spec.md              # Feature specification (v0.2.0)
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
└── contracts/           # Phase 1 output (MCP tool contracts)
```

### Source Code (repository root)

```text
src/codegiraffe/
├── __init__.py            # Package init with version
├── server.py              # FastMCP server + 11 tool definitions
├── graph.py               # Pydantic models (Node, Edge, GraphData) + NetworkX ArchGraph engine
├── storage.py             # StorageBackend protocol + JSONStorage implementation
├── sqlite_storage.py      # SQLiteStorage implementation (v0.2.0)
├── scanner.py             # Scanner pipeline + PythonRecognizer
├── registry.py            # RecognizerRegistry plugin system (v0.2.0)
├── query.py               # Subgraph extraction, keyword scoring, drift detection (enhanced v0.2.0)
├── schema.py              # Node/edge type enums (extensible)
├── export.py              # Mermaid + D3.js graph export (v0.2.0)
├── embeddings.py          # Embedding-based scoring + cache (v0.2.0)
├── coordination.py        # Multi-agent coordination store (v0.2.0)
└── recognizers/           # Language-specific pattern recognizers (v0.2.0)
    ├── __init__.py
    ├── typescript.py      # TypeScript/JavaScript recognizer
    ├── go.py              # Go recognizer
    ├── rust.py            # Rust recognizer
    └── java.py            # Java recognizer

tests/
├── conftest.py            # Shared fixtures
├── test_graph.py          # Graph data model tests
├── test_storage.py        # JSON storage tests
├── test_scanner.py        # Scanner + Python recognizer tests
├── test_query.py          # Query engine tests
├── test_tools.py          # MCP tool contract tests
├── test_integration.py    # End-to-end tests
├── test_registry.py       # Plugin registry tests (v0.2.0)
├── test_recognizers.py    # Multi-language recognizer tests (v0.2.0)
├── test_sqlite.py         # SQLite storage tests (v0.2.0)
├── test_export.py         # Export format tests (v0.2.0)
├── test_embeddings.py     # Embedding scoring tests (v0.2.0)
└── test_coordination.py   # Multi-agent coordination tests (v0.2.0)
```

**Structure Decision**: Single Python package under `src/codegiraffe/` with flat module layout. Language recognizers isolated in `recognizers/` subpackage for clean separation. All new v0.2.0 modules are top-level within the package — no unnecessary nesting.

## MCP Tool Definitions (11 total)

### Core Tools (v0.1.0)

| Tool | Inputs | Output |
|------|--------|--------|
| `codegiraffe_init` | `project_path: str`, `rescan: bool = false`, `backend: str = "json"` | Summary of discovered nodes/edges |
| `codegiraffe_query` | `project_path: str`, `node_id: str \| None`, `node_type: str \| None`, `depth: int = 2` | Subgraph JSON |
| `codegiraffe_add_relation` | `project_path: str`, `source: str`, `target: str`, `relation_type: str`, `source_type: str = "service"`, `target_type: str = "service"`, `metadata: str = "{}"` | Confirmation string |
| `codegiraffe_context_for` | `project_path: str`, `task: str`, `max_nodes: int = 20`, `use_embeddings: bool = true` | Ranked subgraph JSON |
| `codegiraffe_detect_drift` | `project_path: str` | JSON array of drift records (missing, added, renamed, edge drift) |
| `codegiraffe_hotspots` | `project_path: str`, `top_n: int = 10` | JSON array of {node_id, label, type, score} |
| `codegiraffe_sync` | `project_path: str` | Summary with before/after counts and deltas |

### New Tools (v0.2.0)

| Tool | Inputs | Output |
|------|--------|--------|
| `codegiraffe_export` | `project_path: str`, `format: str = "mermaid"`, `direction: str = "TD"`, `subgraph_by_type: bool = true`, `node_id: str \| None`, `depth: int = 2` | Mermaid diagram or D3 JSON |
| `codegiraffe_claim` | `project_path: str`, `agent_id: str`, `node_ids: list[str]`, `task: str`, `ttl: int = 1800` | JSON with success/conflict info |
| `codegiraffe_status` | `project_path: str`, `agent_id: str`, `status: str`, `task: str \| None` | JSON with success/error info |
| `codegiraffe_agents` | `project_path: str` | JSON array of active agent claims |

## Key Design Decisions

1. **StorageBackend protocol**: Abstracts storage so JSON and SQLite are interchangeable. Future backends (Neo4j) implement the same 3-method protocol (load, save, exists).

2. **RecognizerRegistry**: Maps file extensions to PatternRecognizer instances. get_default_registry() lazily initializes all built-in recognizers. Custom recognizers register via register_recognizer().

3. **Scanner uses regex, not AST**: Keeps scanning fast and language-agnostic. Each recognizer is ~150 lines of regex patterns. Trades precision for simplicity and broad framework coverage.

4. **manual=True flag**: Nodes and edges created via codegiraffe_add_relation survive rescans. This is the mechanism for preserving human/agent knowledge that automated scanning can't discover.

5. **Embedding scoring is optional**: Falls back to keyword-based scoring (tokenize + overlap) when sentence-transformers isn't installed. EmbeddingCache persists vectors to disk to avoid re-computation.

6. **File-based coordination**: Multi-agent claims stored in .codegiraffe/agents.json with TTL expiration. No external services required. Conflict detection is pessimistic (claim fails if any node overlaps).

7. **Mermaid node shapes**: Each node type maps to a distinct Mermaid shape for visual differentiation. Sanitization ensures special characters in IDs/labels don't break Mermaid syntax.

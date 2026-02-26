# Code Giraffe Development Guidelines

## Active Technologies
- **Version**: 0.14.0
- **Language**: Python 3.11+
- **Framework**: FastMCP (mcp[cli] >= 1.2.0), NetworkX >= 3.0, Pydantic v2
- **MCP Tools**: 40 tools in server.py
- **Storage**: JSON files + SQLite + Neo4j (optional, all via StorageBackend protocol)
- **Testing**: pytest >= 8.0, pytest-asyncio >= 0.23 (1452+ tests)
- **Package Management**: uv
- **Optional**: sentence-transformers >= 2.0 (embeddings), neo4j >= 6.0, tree-sitter >= 0.23 (AST scanning)
- Python 3.11+ + NetworkX >= 3.0, Pydantic v2, FastMCP (mcp[cli] >= 1.2.0) (032-graph-correctness)
- JSON files (primary), SQLite (secondary), Neo4j (optional) (032-graph-correctness)

## Project Structure

```text
src/codegiraffe/          # Main package
├── server.py             # FastMCP server + 37 MCP tool definitions
├── graph.py              # Pydantic models (Node, Edge, GraphData) + NetworkX ArchGraph
├── storage.py            # StorageBackend protocol + JSONStorage
├── sqlite_storage.py     # SQLiteStorage implementation
├── scanner.py            # Scanner pipeline + PythonRecognizer
├── registry.py           # RecognizerRegistry plugin system
├── query.py              # Subgraph extraction, scoring, drift detection, blast radius, risk, cycles, change validation
├── diff_parser.py        # Unified diff parsing + data models for change impact
├── git_utils.py          # Git CLI subprocess wrappers for change detection
├── patterns.py           # Convention mining and anti-pattern detection
├── ownership.py          # Node annotation layer (owner, stability, notes)
├── coverage_mapper.py    # Test coverage mapping (coverage.py, Istanbul, LCOV)
├── graph_diff.py         # PR-level architecture diffing between git refs
├── domains.py            # Domain inference and management
├── migration.py          # Migration plan generation for large refactors
├── schema.py             # Node/edge type enums
├── export.py             # Mermaid + D3.js graph export
├── embeddings.py         # Embedding-based scoring + cache
├── coordination.py       # Multi-agent coordination store
├── versioning.py         # Schema evolution and version history
├── federation.py         # Cross-repo graph federation
├── neo4j_storage.py      # Neo4j storage backend (optional)
├── ast_scanner.py        # tree-sitter AST scanning (optional)
├── dashboard.py          # Web dashboard (Sigma.js v3, HTTP routes)
├── layout.py             # Server-side ForceAtlas2 layout computation
├── dashboard_server.py   # Standalone Starlette/uvicorn dashboard server
├── assets/               # Logo and static assets
└── recognizers/          # Language-specific pattern recognizers
    ├── typescript.py
    ├── go.py
    ├── rust.py
    ├── java.py
    ├── cpp.py
    ├── csharp.py
    ├── php.py
    └── ruby.py

tests/                    # 1452+ tests
specs/                    # Spec-kit artifacts (spec.md, plan.md, research.md, data-model.md)
```

## Commands

```bash
# Create virtual environment
uv venv .venv

# Activate virtual environment
# Linux / macOS:  source .venv/bin/activate
# Windows (PowerShell):  .venv\Scripts\Activate.ps1
# Windows (cmd):  .venv\Scripts\activate.bat
# Windows (Git Bash):  source .venv/Scripts/activate

# Install for development
uv pip install -e ".[dev]"

# Install with embedding support
uv pip install -e ".[dev,embeddings]"

# Run tests
python -m pytest tests/ -v

# Run the MCP server directly (for testing)
python src/codegiraffe/server.py
```

## Code Style

- All MCP tools use `@mcp.tool()` decorators in `server.py`
- Data models are Pydantic v2 classes in `graph.py`
- Storage backends implement the `StorageBackend` protocol (load, save, exists)
- Pattern recognizers implement the `PatternRecognizer` protocol (recognize method)
- `manual=True` flag on nodes/edges means they survive rescans
- `schema.py` (not types.py) to avoid stdlib shadow
- Node types include `module` (v0.4.0); edge types include `imports`, `implements`, `contains` (v0.4.0)
- Recognizers return `ScanResult` with `ImportInfo` and `ImplementationInfo` data classes for language-agnostic import/implementation detection (v0.6.0)
- `contract` node type with `produces`, `consumes_contract`, `validates`, `violates` edge types for cross-system contract modeling (v0.8.0)
- `CallInfo`, `InterfaceInfo`, `MethodSetEntry` data classes on `ScanResult` for call-graph and interface detection (v0.9.0)
- `calls` edge type populated via `_infer_call_edges()` and `_infer_interface_satisfaction()` pipeline steps (v0.9.0)

## Key Patterns

- Scanner defaults to `scanner_mode="hybrid"` (regex + AST recognizers with deduplication), falling back to regex automatically if tree-sitter is unavailable; use `scanner_mode="ast"` to require tree-sitter exclusively
- Scanner excludes test files by default; pass `include_tests=True` to include them (tagged with `source: test` metadata)
- Scanner detects imports (absolute and relative), creates `imports` edges between `module` nodes
- Scanner detects inheritance, creates `implements` edges from child to parent class
- Scanner detects function/method calls in Go, Python, TypeScript (regex + AST), creates `calls` edges
- Scanner detects Go interface satisfaction via duck-type method set matching, creates cross-file `implements` edges
- Each Python file produces a `module` node with `contains` edges to its entities
- RecognizerRegistry maps file extensions to recognizer instances
- Embedding scoring is optional with graceful fallback to keywords
- Coordination uses file-based JSON store with TTL expiration
- All queries return scoped subgraphs, never the full graph
- `ArchGraph` uses `nx.MultiDiGraph` with `edge.type` as the edge key — multiple edge types between the same node pair coexist (e.g., `contains` + `imports` between the same modules)
- Edge helpers on `ArchGraph`: `get_edge_between(src, tgt)`, `get_typed_edge(src, tgt, type)`, `get_all_edges_between(src, tgt)`, `iter_edges()` — prefer these over raw `graph.graph` access
- When iterating edges directly on the NetworkX graph, always use `edges(data=True, keys=False)` to get 3-tuples
- `codegiraffe_cypher` rejects write operations (CREATE, MERGE, DELETE, SET, REMOVE, DROP, DETACH, CALL) before execution
- Thread safety: `_graph_lock` (RLock) in `server.py` protects all `_graph` and `_storage` access across MCP tools and the dashboard thread

## Constitution

See `.specify/memory/constitution.md` for the 7 governing principles:
I. MCP-Native, II. Graph-First, III. Beyond-AST, IV. Context Efficiency,
V. Incremental & Non-Destructive, VI. Test-First (NON-NEGOTIABLE), VII. Simplicity

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->

## Recent Changes
- v0.16.0: API & DX Improvements — split `codegiraffe_domains` into 4 focused tools (`codegiraffe_list_domains`, `codegiraffe_infer_domains`, `codegiraffe_add_domain`, `codegiraffe_remove_domain`); removed `codegiraffe_restore` stub; added `codegiraffe_release`; renamed `codegiraffe_status` → `codegiraffe_update_agent_status`; 40 MCP tools total; 1646+ tests
- v0.15.0: Graph Correctness — `nx.MultiDiGraph` migration (multi-edges preserved), Cypher write-rejection, `threading.RLock` concurrency protection; 4 new `ArchGraph` helpers; 1600+ tests
- v0.14.0: Sigma.js v3 dashboard — WebGL renderer, server-side ForceAtlas2 layout, 33k-node interactive visualization
- v0.13.0: Advanced Analysis -- `codegiraffe_coverage`, `codegiraffe_pr_diff`, `codegiraffe_order_tasks`, `codegiraffe_domains`, `codegiraffe_migration_plan`; `codegiraffe_dashboard` tool for one-click web dashboard launch; 37 MCP tools total; 1339+ tests

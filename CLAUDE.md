# Code Giraffe Development Guidelines

## Active Technologies
- **Version**: 0.10.0
- **Language**: Python 3.11+
- **Framework**: FastMCP (mcp[cli] >= 1.2.0), NetworkX >= 3.0, Pydantic v2
- **Storage**: JSON files + SQLite + Neo4j (optional)
- **Testing**: pytest >= 8.0, pytest-asyncio >= 0.23 (979+ tests)
- **Package Management**: uv
- **Optional**: sentence-transformers >= 2.0 (embeddings), neo4j >= 6.0, tree-sitter >= 0.23 (AST scanning)
- Python 3.11+ + FastMCP (mcp[cli] >= 1.2.0), NetworkX >= 3.0, Pydantic v2 (011-graph-intelligence)
- JSON + SQLite + Neo4j (all via StorageBackend protocol) (011-graph-intelligence)

## Project Structure

```text
src/codegiraffe/          # Main package
├── server.py             # FastMCP server + 28 MCP tool definitions
├── graph.py              # Pydantic models (Node, Edge, GraphData) + NetworkX ArchGraph
├── storage.py            # StorageBackend protocol + JSONStorage
├── sqlite_storage.py     # SQLiteStorage implementation
├── scanner.py            # Scanner pipeline + PythonRecognizer
├── registry.py           # RecognizerRegistry plugin system
├── query.py              # Subgraph extraction, scoring, drift detection, blast radius, risk, cycles, change validation
├── diff_parser.py        # Unified diff parsing + data models for change impact
├── git_utils.py          # Git CLI subprocess wrappers for change detection
├── schema.py             # Node/edge type enums
├── export.py             # Mermaid + D3.js graph export
├── embeddings.py         # Embedding-based scoring + cache
├── coordination.py       # Multi-agent coordination store
├── versioning.py         # Schema evolution and version history
├── federation.py         # Cross-repo graph federation
├── neo4j_storage.py      # Neo4j storage backend (optional)
├── ast_scanner.py        # tree-sitter AST scanning (optional)
├── dashboard.py          # Web dashboard (Cytoscape.js)
└── recognizers/          # Language-specific pattern recognizers
    ├── typescript.py
    ├── go.py
    ├── rust.py
    ├── java.py
    ├── cpp.py
    ├── csharp.py
    ├── php.py
    └── ruby.py

tests/                    # 979+ tests
specs/                    # Spec-kit artifacts (spec.md, plan.md, research.md, data-model.md)
```

## Commands

```bash
# Run tests
source .venv/bin/activate && python -m pytest tests/ -v

# Install for development
uv venv .venv && source .venv/bin/activate && uv pip install -e ".[dev]"

# Install with embedding support
uv pip install -e ".[dev,embeddings]"

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

- Scanner uses regex by default; AST scanning via tree-sitter available with `scanner_mode="ast"`
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
- **Known limitation**: `ArchGraph` uses `nx.DiGraph` (one edge per source+target pair). When multiple edge types exist between the same pair (e.g., `contains` + `calls`), the last one wins. Consider migrating to `nx.MultiDiGraph` in a future version.

## Constitution

See `.specify/memory/constitution.md` for the 7 governing principles:
I. MCP-Native, II. Graph-First, III. Beyond-AST, IV. Context Efficiency,
V. Incremental & Non-Destructive, VI. Test-First (NON-NEGOTIABLE), VII. Simplicity

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->

## Recent Changes
- 011-graph-intelligence: Added Python 3.11+ + FastMCP (mcp[cli] >= 1.2.0), NetworkX >= 3.0, Pydantic v2
- v0.10.0: Change impact validation -- `codegiraffe_validate_changes` (detect incomplete modifications from git diff), `codegiraffe_suggest_tests` (recommend test files for changes), `codegiraffe_file_coupling` (mine git co-change history); enhanced `codegiraffe_context_for` with `include_changes` parameter for change-aware scoring; new modules `diff_parser.py` and `git_utils.py`; 28 MCP tools total; 979+ tests
- v0.9.0: Scanner depth -- call-graph edges (`calls`) for Go/Python/TypeScript via regex and tree-sitter AST; cross-file Go interface satisfaction (duck-type method set matching); demand-driven method nodes (`service:{Parent}.{Method}`); `CallInfo`/`InterfaceInfo`/`MethodSetEntry` data classes; `_infer_call_edges()` and `_infer_interface_satisfaction()` pipeline steps; improved TypeScript `implements` multi-interface and generic handling; 874+ tests

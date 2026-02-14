# Code Giraffe Development Guidelines

## Active Technologies
- **Version**: 0.9.0
- **Language**: Python 3.11+
- **Framework**: FastMCP (mcp[cli] >= 1.2.0), NetworkX >= 3.0, Pydantic v2
- **Storage**: JSON files + SQLite + Neo4j (optional)
- **Testing**: pytest >= 8.0, pytest-asyncio >= 0.23 (874+ tests)
- **Package Management**: uv
- **Optional**: sentence-transformers >= 2.0 (embeddings), neo4j >= 6.0, tree-sitter >= 0.23 (AST scanning)

## Project Structure

```text
src/codegiraffe/          # Main package
├── server.py             # FastMCP server + 25 MCP tool definitions
├── graph.py              # Pydantic models (Node, Edge, GraphData) + NetworkX ArchGraph
├── storage.py            # StorageBackend protocol + JSONStorage
├── sqlite_storage.py     # SQLiteStorage implementation
├── scanner.py            # Scanner pipeline + PythonRecognizer
├── registry.py           # RecognizerRegistry plugin system
├── query.py              # Subgraph extraction, scoring, drift detection, blast radius, risk, cycles
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

tests/                    # 874+ tests
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
- v0.9.0: Scanner depth -- call-graph edges (`calls`) for Go/Python/TypeScript via regex and tree-sitter AST; cross-file Go interface satisfaction (duck-type method set matching); demand-driven method nodes (`service:{Parent}.{Method}`); `CallInfo`/`InterfaceInfo`/`MethodSetEntry` data classes; `_infer_call_edges()` and `_infer_interface_satisfaction()` pipeline steps; improved TypeScript `implements` multi-interface and generic handling; 874+ tests
- v0.8.0: Cross-system contracts -- `codegiraffe_contracts` (list/filter), `codegiraffe_validate_contracts` (integrity check), `codegiraffe_add_contract` (manual creation); contract inference for API, event, config, and data contracts; contract-aware blast radius with critical severity for contract consumers; dashboard contract styling (hexagonal purple nodes); 25 MCP tools total; 791+ tests
- v0.7.0: Impact analysis tools -- `codegiraffe_blast_radius` (downstream impact by severity), `codegiraffe_risk_assessment` (composite risk scoring), `codegiraffe_cycles` (circular dependency detection); enhanced `codegiraffe_context_for` with `include_impact` parameter; enhanced `codegiraffe_hotspots` with `metrics` parameter; 22 MCP tools total; 754+ tests
- v0.6.0 (006-language-agnostic-intelligence): Language-agnostic scanner intelligence -- universal module nodes, `contains` edges, import detection, and implementation/inheritance detection for all 9 languages; `ImportInfo` and `ImplementationInfo` data classes on `ScanResult` for structured recognizer output; Go `go.mod`-aware import parsing and interface implementation detection; test file exclusion extended to all languages; 698+ tests
- v0.5.0: 4 new language recognizers (C#, C/C++, PHP, Ruby — now 9 languages); 3 new dashboard layouts (grid, concentric, breadthfirst); dashboard improvements (legend, stats, edge tooltips, refined colors); 566+ tests
- v0.4.0 (005-scanner-intelligence): Scanner intelligence -- test file exclusion, import detection, inheritance detection, module nodes; new schema types (`module`, `imports`, `implements`, `contains`); `include_tests` parameter on `codegiraffe_init` and `codegiraffe_sync`; 505+ tests

# Code Giraffe Development Guidelines

## Active Technologies

- **Language**: Python 3.11+
- **Framework**: FastMCP (mcp[cli] >= 1.2.0), NetworkX >= 3.0, Pydantic v2
- **Storage**: JSON files + SQLite
- **Testing**: pytest >= 8.0, pytest-asyncio >= 0.23
- **Package Management**: uv
- **Optional**: sentence-transformers >= 2.0 (for embedding-based scoring)

## Project Structure

```text
src/codegiraffe/          # Main package
├── server.py             # FastMCP server + 11 MCP tool definitions
├── graph.py              # Pydantic models (Node, Edge, GraphData) + NetworkX ArchGraph
├── storage.py            # StorageBackend protocol + JSONStorage
├── sqlite_storage.py     # SQLiteStorage implementation
├── scanner.py            # Scanner pipeline + PythonRecognizer
├── registry.py           # RecognizerRegistry plugin system
├── query.py              # Subgraph extraction, scoring, drift detection
├── schema.py             # Node/edge type enums
├── export.py             # Mermaid + D3.js graph export
├── embeddings.py         # Embedding-based scoring + cache
├── coordination.py       # Multi-agent coordination store
└── recognizers/          # Language-specific pattern recognizers
    ├── typescript.py
    ├── go.py
    ├── rust.py
    └── java.py

tests/                    # 231 tests
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

## Key Patterns

- Scanner uses regex, NOT AST parsing
- RecognizerRegistry maps file extensions to recognizer instances
- Embedding scoring is optional with graceful fallback to keywords
- Coordination uses file-based JSON store with TTL expiration
- All queries return scoped subgraphs, never the full graph

## Constitution

See `.specify/memory/constitution.md` for the 7 governing principles:
I. MCP-Native, II. Graph-First, III. Beyond-AST, IV. Context Efficiency,
V. Incremental & Non-Destructive, VI. Test-First (NON-NEGOTIABLE), VII. Simplicity

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->

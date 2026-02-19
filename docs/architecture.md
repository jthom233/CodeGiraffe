[← Back to Documentation](README.md)

# Architecture

This page covers the internal module layout of Code Giraffe, the graph data model (nodes and edges), and the complete set of built-in node and edge types.

---

## Module Layout

```
src/codegiraffe/
├── server.py            # FastMCP server + 37 MCP tool definitions
├── graph.py             # Pydantic models (Node, Edge, GraphData) + NetworkX ArchGraph engine
├── storage.py           # StorageBackend protocol + JSON file implementation
├── sqlite_storage.py    # SQLite storage backend for larger graphs
├── scanner.py           # Multi-language codebase scanner (dispatches to recognizers)
├── registry.py          # RecognizerRegistry plugin system with extension mapping
├── query.py             # Subgraph extraction, scoring, drift, blast radius, risk, cycles, change validation
├── diff_parser.py       # Unified diff parsing + data models for change impact analysis
├── git_utils.py         # Git CLI subprocess wrappers for change detection
├── patterns.py          # Convention mining and anti-pattern detection
├── ownership.py         # Node annotation layer (owner, stability, notes)
├── coverage_mapper.py   # Test coverage mapping (coverage.py, Istanbul, LCOV)
├── graph_diff.py        # PR-level architecture diffing between git refs
├── domains.py           # Domain inference and management
├── migration.py         # Migration plan generation for large refactors
├── embeddings.py        # Optional embedding-based semantic scoring (sentence-transformers)
├── export.py            # Graph visualization export (Mermaid + D3.js JSON)
├── coordination.py      # Multi-agent claim/status coordination with TTL
├── versioning.py        # Schema evolution, diffs, version history
├── federation.py        # Cross-repo graph federation
├── neo4j_storage.py     # Neo4j storage backend (optional)
├── ast_scanner.py       # tree-sitter AST-based scanning (optional)
├── dashboard.py         # Web dashboard (Sigma.js v3, served via HTTP)
├── layout.py            # Server-side ForceAtlas2 layout computation (fa2 optional dep)
├── dashboard_server.py  # Standalone Starlette/uvicorn background HTTP server for dashboard
├── schema.py            # Node/edge type enums (extensible)
└── recognizers/         # Language-specific pattern recognizers
    ├── __init__.py
    ├── typescript.py    # TypeScript/TSX recognizer
    ├── go.py            # Go recognizer
    ├── rust.py          # Rust recognizer
    ├── java.py          # Java recognizer
    ├── cpp.py           # C/C++ recognizer
    ├── csharp.py        # C# recognizer
    ├── php.py           # PHP recognizer
    └── ruby.py          # Ruby recognizer
```

---

## Data Model

The architecture graph is a directed graph of typed nodes connected by typed edges.

### Nodes

**Nodes** represent architectural entities — services, endpoints, database tables, queues, environment variables, and more:

```json
{
  "id": "endpoint:/api/users",
  "type": "endpoint",
  "label": "GET /api/users",
  "metadata": {"method": "GET", "framework": "flask"},
  "file_path": "app.py",
  "manual": false
}
```

The `manual` flag marks nodes that were created via `codegiraffe_add_relation` or `codegiraffe_add_contract`. Manual nodes survive re-scans and are never overwritten by the scanner.

### Edges

**Edges** represent relationships between nodes:

```json
{
  "source": "endpoint:/api/users",
  "target": "table:users",
  "type": "reads",
  "metadata": {},
  "manual": false
}
```

All edges carry a `confidence` value (0.0–1.0) reflecting detection reliability. See [Edge Confidence Scoring](edge-confidence.md) for the full confidence table.

---

## Built-in Types

### Node Types

| Type | What It Represents |
|---|---|
| `service` | Application service or class |
| `endpoint` | HTTP route or API handler |
| `database_table` | Database table or ORM model |
| `queue` | Message queue or topic |
| `env_var` | Environment variable |
| `config` | Configuration value or file |
| `worker` | Background worker or job |
| `frontend_component` | UI component (React, Vue, etc.) |
| `event` | Domain event or message |
| `external_api` | Third-party API call |
| `module` | Source file (added in v0.4.0) |
| `contract` | Cross-system contract (added in v0.8.0) |

### Edge Types

| Type | What It Represents |
|---|---|
| `calls` | Function/method call |
| `reads` | Data read from a node |
| `writes` | Data written to a node |
| `publishes` | Event or message published |
| `consumes` | Event or message consumed |
| `depends_on` | Generic dependency |
| `configures` | Configuration relationship |
| `owns` | Ownership or responsibility |
| `triggers` | Trigger relationship |
| `imports` | Module import (between `module` nodes) |
| `implements` | Inheritance or interface implementation |
| `contains` | Module-to-entity containment |
| `produces` | Contract producer relationship |
| `consumes_contract` | Contract consumer relationship |
| `validates` | Contract validation |
| `violates` | Contract violation |
| `cross_repo_calls` | Call across federated repos |
| `cross_repo_depends_on` | Dependency across federated repos |
| `cross_repo_publishes` | Publish across federated repos |
| `cross_repo_consumes` | Consume across federated repos |

### Custom Types

Custom types are fully supported — any string works as a node or edge type. Use `codegiraffe_add_relation` with a custom `relation_type` to model domain-specific relationships not covered by the built-in set.

---

## See Also

- [Multi-Language Scanner](scanner.md) — How the scanner produces nodes and edges for each language
- [Storage Backends](storage.md) — JSON, SQLite, and Neo4j storage options

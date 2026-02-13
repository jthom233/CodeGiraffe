# Code Giraffe

**Architecture knowledge graph MCP server for AI-assisted development.**

Code Giraffe captures the relationships that static code analysis can't see — runtime coupling, data flows, cross-system contracts, and operational context — and exposes them as an MCP (Model Context Protocol) server that AI agents can query directly.

## Why Code Giraffe?

Modern AI coding tools understand code structure (imports, ASTs, type systems) really well. But they're blind to the relationships that actually cause production breaks:

| What IDEs See | What Code Giraffe Sees |
|---|---|
| Import graphs, function signatures | Runtime coupling (DI, reflection, dynamic imports, plugin registries) |
| File-level dependencies | Data flow and side effects (DB reads/writes, cache invalidation, idempotency) |
| Type hierarchies | Cross-system contracts (API endpoints ↔ frontend components, event schemas) |
| Syntax trees | Operational context (env vars, secrets, permissions, feature flags, ownership) |

Code Giraffe fills this gap by maintaining an **architecture knowledge graph** that AI agents can query before making changes, ensuring they understand the full impact of their work.

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip
- An MCP-compatible client (Claude Code, Claude Desktop, Cursor, etc.)

### Installation

```bash
git clone https://github.com/jthom233/CodeGiraffe.git
cd CodeGiraffe
uv venv .venv && source .venv/bin/activate
uv pip install -e ".[dev]"
```

### Add to Claude Code

```bash
claude mcp add codegiraffe -- /path/to/CodeGiraffe/.venv/bin/python /path/to/CodeGiraffe/src/codegiraffe/server.py
```

Or add manually to your `~/.claude.json`:

```json
{
  "mcpServers": {
    "codegiraffe": {
      "type": "stdio",
      "command": "/path/to/CodeGiraffe/.venv/bin/python",
      "args": ["/path/to/CodeGiraffe/src/codegiraffe/server.py"],
      "env": {}
    }
  }
}
```

### Add to Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "codegiraffe": {
      "command": "/path/to/CodeGiraffe/.venv/bin/python",
      "args": ["/path/to/CodeGiraffe/src/codegiraffe/server.py"]
    }
  }
}
```

## MCP Tools

Code Giraffe exposes 7 tools that any MCP client can call:

### `codegiraffe_init`

Scan a project and bootstrap the architecture knowledge graph.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `project_path` | `str` | required | Root directory of the project to scan |
| `rescan` | `bool` | `false` | Re-scan while preserving manual annotations |

**Example:**
```
codegiraffe_init(project_path="/home/user/my-project")
→ "Initialized graph with 47 nodes and 63 edges"
```

**Supported language: Python only (v0.1.0).** Multi-language support (TypeScript, Go, Rust, Java) is on the [roadmap](#roadmap).

The scanner automatically detects:
- Flask / FastAPI route decorators → `endpoint` nodes
- SQLAlchemy model classes → `database_table` nodes
- Celery task decorators → `worker` nodes
- `os.environ` / `os.getenv` calls → `env_var` nodes
- `requests.*` HTTP calls → `external_api` nodes
- Class definitions → `service` nodes

---

### `codegiraffe_query`

Query the graph by node ID or type. Returns a scoped subgraph — not the full graph — to conserve tokens.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `project_path` | `str` | required | Root directory of the project |
| `node_id` | `str \| None` | `None` | Node ID for subgraph extraction |
| `node_type` | `str \| None` | `None` | Node type for type-based filtering |
| `depth` | `int` | `2` | Maximum hops from the queried node |

**Example:**
```
codegiraffe_query(project_path="/home/user/my-project", node_id="endpoint:/api/users", depth=2)
→ JSON subgraph with the endpoint, its DB tables, services, and env vars within 2 hops
```

---

### `codegiraffe_add_relation`

Manually annotate a relationship that automated scanning missed. Manual annotations survive re-scans.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `project_path` | `str` | required | Root directory of the project |
| `source` | `str` | required | Source node ID |
| `target` | `str` | required | Target node ID |
| `relation_type` | `str` | required | Relationship type (e.g., `"publishes_to"`) |
| `source_type` | `str` | `"service"` | Node type if source needs to be auto-created |
| `target_type` | `str` | `"service"` | Node type if target needs to be auto-created |
| `metadata` | `str` | `"{}"` | JSON string of extra key-value pairs |

**Example:**
```
codegiraffe_add_relation(
  project_path="/home/user/my-project",
  source="service:OrderService",
  target="queue:payment-events",
  relation_type="publishes",
  source_type="service",
  target_type="queue"
)
→ "Added manual relation: service:OrderService --[publishes]--> queue:payment-events"
```

---

### `codegiraffe_context_for`

The killer tool. Given a natural-language task description, returns the minimal relevant subgraph ranked by impact — so agents get exactly the context they need without wasting tokens on irrelevant code.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `project_path` | `str` | required | Root directory of the project |
| `task` | `str` | required | Natural language task description |
| `max_nodes` | `int` | `20` | Maximum nodes to return |

**Example:**
```
codegiraffe_context_for(
  project_path="/home/user/my-project",
  task="add rate limiting to the payments endpoint"
)
→ JSON subgraph with payments endpoint, its middleware, DB tables, env vars, ranked by relevance
```

---

### `codegiraffe_detect_drift`

Check if the graph still matches the actual codebase. Reports mismatches after code changes.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `project_path` | `str` | required | Root directory of the project |

**Example:**
```
codegiraffe_detect_drift(project_path="/home/user/my-project")
→ [{"type": "missing_in_code", "node_id": "endpoint:/api/legacy", "details": "..."}]
```

---

### `codegiraffe_hotspots`

Identify the most coupled, change-prone areas of the architecture. Ranks nodes by degree centrality.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `project_path` | `str` | required | Root directory of the project |
| `top_n` | `int` | `10` | Number of hotspots to return |

**Example:**
```
codegiraffe_hotspots(project_path="/home/user/my-project", top_n=5)
→ [{"node_id": "service:AuthService", "label": "Auth Service", "type": "service", "score": 0.4231}]
```

---

### `codegiraffe_sync`

Incrementally update the graph after code changes. Re-scans only what changed while preserving manual annotations.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `project_path` | `str` | required | Root directory of the project |

**Example:**
```
codegiraffe_sync(project_path="/home/user/my-project")
→ "Sync complete. Nodes: 47 -> 52 (delta +5). Edges: 63 -> 71 (delta +8)."
```

## Architecture

```
src/codegiraffe/
├── server.py      # FastMCP server + 7 tool definitions
├── graph.py       # Pydantic models (Node, Edge, GraphData) + NetworkX ArchGraph engine
├── storage.py     # StorageBackend protocol + JSON file implementation
├── scanner.py     # Regex-based Python codebase scanner
├── query.py       # Subgraph extraction, keyword scoring, drift detection
└── schema.py      # Node/edge type enums (extensible)
```

### Data Model

**Nodes** represent architectural entities:

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

**Edges** represent relationships:

```json
{
  "source": "endpoint:/api/users",
  "target": "table:users",
  "type": "reads",
  "metadata": {},
  "manual": false
}
```

### Built-in Types

**Node types:** `service`, `endpoint`, `database_table`, `queue`, `env_var`, `config`, `worker`, `frontend_component`, `event`, `external_api`

**Edge types:** `calls`, `reads`, `writes`, `publishes`, `consumes`, `depends_on`, `configures`, `owns`, `triggers`

Custom types are fully supported — any string works as a node or edge type.

### Storage

Graphs are stored as JSON at `{project_path}/.codegiraffe/graph.json`. The storage layer uses a protocol-based abstraction, making it straightforward to add SQLite or Neo4j backends in the future.

### Scanner

> **Note:** The v0.1.0 scanner supports **Python only**. The scanner uses a pluggable `PatternRecognizer` protocol, so adding new languages (TypeScript, Go, Rust, Java) is a matter of writing a new recognizer class — no changes to the core graph or query engine required.

The v1 scanner uses regex pattern matching (not AST parsing) to keep things simple and fast. It recognizes common Python framework patterns:

- **Flask/FastAPI**: `@app.route()`, `@router.get()`, etc.
- **SQLAlchemy**: Classes inheriting from `Base` or `db.Model` with `__tablename__`
- **Celery**: `@app.task`, `@shared_task`, `@celery.task`
- **Environment**: `os.environ["KEY"]`, `os.getenv("KEY")`
- **HTTP clients**: `requests.get()`, `requests.post()`, etc.

Cross-file edge inference connects endpoints to database tables when a file references model class names from other files.

## Usage Patterns

### Orchestrator + Subagent Workflow

The most powerful pattern is using Code Giraffe as context for an orchestrator that delegates to subagents:

1. **Orchestrator** calls `codegiraffe_context_for(task="add rate limiting to payments")`
2. **Code Giraffe** returns the relevant subgraph (payments endpoint, its DB tables, middleware, env vars)
3. **Orchestrator** includes this context in the subagent's prompt
4. **Subagent** has exactly the architectural knowledge it needs — no wasted tokens

### Continuous Graph Maintenance

```
1. codegiraffe_init()          → Bootstrap on first use
2. codegiraffe_add_relation()  → Annotate what the scanner missed
3. codegiraffe_sync()          → Update after code changes
4. codegiraffe_detect_drift()  → Catch stale graph entries
```

### Pre-Change Impact Analysis

Before modifying any code:

```
1. codegiraffe_query(node_id="endpoint:/api/payments", depth=3)
   → See everything connected to the endpoint within 3 hops
2. codegiraffe_hotspots(top_n=5)
   → Know which areas are most coupled and risky to change
```

## Development

### Running Tests

```bash
uv pip install -e ".[dev]"
python -m pytest tests/ -v
```

76 tests covering graph operations, storage, scanner, and query engine.

### Project Constitution

The project follows a formal constitution at `.specify/memory/constitution.md` with 7 core principles:

1. **MCP-Native** — Everything exposed as MCP tools
2. **Graph-First** — Directed graph with typed nodes and edges
3. **Beyond-AST** — Capture what static analysis can't see
4. **Context Efficiency** — Minimal relevant context, always
5. **Incremental** — Non-destructive updates, manual annotations survive
6. **Test-First** — TDD mandatory
7. **Simplicity** — JSON storage, regex scanning, YAGNI

## Roadmap

- [ ] Multi-language scanner support (TypeScript, Go, Rust, Java)
- [ ] SQLite storage backend for larger graphs
- [ ] Graph visualization export (Mermaid, D3.js)
- [ ] Richer drift detection with rename tracking
- [ ] Embedding-based context scoring (replace keyword matching)
- [ ] Multi-agent status coordination tools
- [ ] Plugin system for custom recognizers

## License

MIT

## Contributing

Contributions welcome. Please follow the project constitution and ensure all tests pass before submitting PRs.

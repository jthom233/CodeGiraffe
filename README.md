# Code Giraffe

**Architecture knowledge graph MCP server for AI-assisted development.**

Code Giraffe captures the relationships that static code analysis can't see -- runtime coupling, data flows, cross-system contracts, and operational context -- and exposes them as an MCP (Model Context Protocol) server that AI agents can query directly.

## Why Code Giraffe?

Modern AI coding tools understand code structure (imports, ASTs, type systems) really well. But they're blind to the relationships that actually cause production breaks:

| What IDEs See | What Code Giraffe Sees |
|---|---|
| Import graphs, function signatures | Runtime coupling (DI, reflection, dynamic imports, plugin registries) |
| File-level dependencies | Data flow and side effects (DB reads/writes, cache invalidation, idempotency) |
| Type hierarchies | Cross-system contracts (API endpoints <-> frontend components, event schemas) |
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

For embedding-based context scoring (optional, falls back to keyword matching if not installed):

```bash
uv pip install -e ".[dev,embeddings]"
```

Or with pip:

```bash
pip install -e ".[embeddings]"
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

Code Giraffe exposes 11 tools that any MCP client can call:

### `codegiraffe_init`

Scan a project and bootstrap the architecture knowledge graph.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `project_path` | `str` | required | Root directory of the project to scan |
| `rescan` | `bool` | `false` | Re-scan while preserving manual annotations |
| `backend` | `str` | `"json"` | Storage backend: `"json"` or `"sqlite"` |

**Example:**
```
codegiraffe_init(project_path="/home/user/my-project")
--> "Initialized graph with 47 nodes and 63 edges"

codegiraffe_init(project_path="/home/user/large-project", backend="sqlite")
--> "Initialized graph with 312 nodes and 487 edges"
```

The scanner automatically detects architectural patterns across 5 languages. See the [Multi-Language Scanner](#multi-language-scanner) section for details on what each language recognizer detects.

---

### `codegiraffe_query`

Query the graph by node ID or type. Returns a scoped subgraph -- not the full graph -- to conserve tokens.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `project_path` | `str` | required | Root directory of the project |
| `node_id` | `str \| None` | `None` | Node ID for subgraph extraction |
| `node_type` | `str \| None` | `None` | Node type for type-based filtering |
| `depth` | `int` | `2` | Maximum hops from the queried node |

**Example:**
```
codegiraffe_query(project_path="/home/user/my-project", node_id="endpoint:/api/users", depth=2)
--> JSON subgraph with the endpoint, its DB tables, services, and env vars within 2 hops
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
--> "Added manual relation: service:OrderService --[publishes]--> queue:payment-events"
```

---

### `codegiraffe_context_for`

The killer tool. Given a natural-language task description, returns the minimal relevant subgraph ranked by impact -- so agents get exactly the context they need without wasting tokens on irrelevant code.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `project_path` | `str` | required | Root directory of the project |
| `task` | `str` | required | Natural language task description |
| `max_nodes` | `int` | `20` | Maximum nodes to return |
| `use_embeddings` | `bool` | `true` | Use embedding-based semantic scoring when available |

When `sentence-transformers` is installed and `use_embeddings` is `true`, scoring uses embedding-based semantic similarity for significantly better relevance ranking. Otherwise, it falls back to keyword overlap scoring. See the [Embedding-Based Scoring](#embedding-based-scoring) section for details.

**Example:**
```
codegiraffe_context_for(
  project_path="/home/user/my-project",
  task="add rate limiting to the payments endpoint"
)
--> JSON subgraph with payments endpoint, its middleware, DB tables, env vars, ranked by relevance
```

---

### `codegiraffe_detect_drift`

Check if the graph still matches the actual codebase. Re-scans the project and compares results against the stored graph.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `project_path` | `str` | required | Root directory of the project |

Reports three kinds of drift:

- **missing_in_code** -- Nodes in the graph that no longer exist in the codebase
- **missing_in_graph** -- Patterns found in code that are not in the graph
- **rename_candidate** -- Nodes that appear to have been renamed (based on similarity matching)
- **edge_drift** -- Edges where either the source or target node has drifted

**Example:**
```
codegiraffe_detect_drift(project_path="/home/user/my-project")
--> [
      {"type": "missing_in_code", "node_id": "endpoint:/api/legacy", "details": "..."},
      {"type": "rename_candidate", "old_id": "service:UserSvc", "new_id": "service:UserService", "similarity": 0.85},
      {"type": "edge_drift", "source": "endpoint:/api/old", "target": "table:users", "reason": "source missing"}
    ]
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
--> [{"node_id": "service:AuthService", "label": "Auth Service", "type": "service", "score": 0.4231}]
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
--> "Sync complete. Nodes: 47 -> 52 (delta +5). Edges: 63 -> 71 (delta +8)."
```

---

### `codegiraffe_export`

Export the architecture graph as a visualization format for documentation or dashboards.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `project_path` | `str` | required | Root directory of the project |
| `format` | `str` | `"mermaid"` | Export format: `"mermaid"` or `"d3"` |
| `direction` | `str` | `"TD"` | Mermaid direction: `"TD"`, `"LR"`, `"BT"`, `"RL"` |
| `subgraph_by_type` | `bool` | `true` | Group nodes by type in Mermaid output |
| `node_id` | `str \| None` | `None` | Scope export to subgraph around this node |
| `depth` | `int` | `2` | Subgraph depth when `node_id` is provided |

**Mermaid format** generates a flowchart diagram that can be rendered in GitHub, GitLab, Notion, and other Markdown renderers. Nodes are mapped to Mermaid shapes based on their type:

| Node Type | Mermaid Shape |
|---|---|
| `endpoint` | Parallelogram |
| `database_table` | Cylinder |
| `queue` | Subroutine |
| `worker` | Hexagon |
| `service` | Rectangle |
| `env_var` | Rounded |
| `config` | Rounded |
| `frontend_component` | Asymmetric |
| `event` | Stadium |
| `external_api` | Circle |

**D3 format** generates a JSON structure compatible with D3.js force-directed graph visualizations, suitable for embedding in web dashboards.

**Example:**
```
codegiraffe_export(project_path="/home/user/my-project", format="mermaid", direction="LR")
--> Mermaid flowchart source string

codegiraffe_export(project_path="/home/user/my-project", format="d3", node_id="service:AuthService", depth=3)
--> D3.js-compatible JSON scoped to AuthService and its neighbors within 3 hops
```

---

### `codegiraffe_claim`

Claim graph nodes for an agent to prevent conflicts during concurrent multi-agent development.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `project_path` | `str` | required | Root directory of the project |
| `agent_id` | `str` | required | Unique agent identifier |
| `node_ids` | `list[str]` | required | Node IDs to claim |
| `task` | `str` | required | Description of the agent's task |
| `ttl` | `int` | `1800` | Claim expiration in seconds (default: 30 min) |

Claims automatically expire after `ttl` seconds. If another agent has already claimed overlapping nodes, the claim fails with conflict details.

**Example:**
```
codegiraffe_claim(
  project_path="/home/user/my-project",
  agent_id="agent-1",
  node_ids=["endpoint:/api/payments", "service:PaymentService"],
  task="Add Stripe webhook handler"
)
--> {"status": "claimed", "agent_id": "agent-1", "nodes": [...], "expires_at": "..."}
```

---

### `codegiraffe_status`

Update an agent's status and refresh its claim TTL.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `project_path` | `str` | required | Root directory of the project |
| `agent_id` | `str` | required | Agent identifier |
| `status` | `str` | required | `"active"`, `"done"`, or `"blocked"` |
| `task` | `str \| None` | `None` | Updated task description |

Setting status to `"done"` releases the agent's claimed nodes. Setting status to `"active"` refreshes the TTL so claims don't expire during long-running work.

**Example:**
```
codegiraffe_status(
  project_path="/home/user/my-project",
  agent_id="agent-1",
  status="done"
)
--> {"agent_id": "agent-1", "status": "done", "released_nodes": [...]}
```

---

### `codegiraffe_agents`

List all active agents and their claimed nodes, enabling coordination and conflict avoidance.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `project_path` | `str` | required | Root directory of the project |

**Example:**
```
codegiraffe_agents(project_path="/home/user/my-project")
--> [
      {"agent_id": "agent-1", "status": "active", "task": "Add Stripe webhook", "nodes": ["endpoint:/api/payments"], "expires_at": "..."},
      {"agent_id": "agent-2", "status": "blocked", "task": "Update user schema", "nodes": ["table:users"], "expires_at": "..."}
    ]
```

## Architecture

```
src/codegiraffe/
├── server.py            # FastMCP server + 11 tool definitions
├── graph.py             # Pydantic models (Node, Edge, GraphData) + NetworkX ArchGraph engine
├── storage.py           # StorageBackend protocol + JSON file implementation
├── sqlite_storage.py    # SQLite storage backend for larger graphs
├── scanner.py           # Multi-language codebase scanner (dispatches to recognizers)
├── registry.py          # RecognizerRegistry plugin system with extension mapping
├── query.py             # Subgraph extraction, keyword scoring, drift detection
├── embeddings.py        # Optional embedding-based semantic scoring (sentence-transformers)
├── export.py            # Graph visualization export (Mermaid + D3.js JSON)
├── coordination.py      # Multi-agent claim/status coordination with TTL
├── schema.py            # Node/edge type enums (extensible)
└── recognizers/         # Language-specific pattern recognizers
    ├── __init__.py
    ├── typescript.py    # TypeScript/TSX recognizer
    ├── go.py            # Go recognizer
    ├── rust.py          # Rust recognizer
    └── java.py          # Java recognizer
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

Custom types are fully supported -- any string works as a node or edge type.

## Storage Backends

Code Giraffe supports two storage backends, selectable via the `backend` parameter on `codegiraffe_init`:

### JSON (default)

Graphs are stored as a single JSON file at `{project_path}/.codegiraffe/graph.json`. Best for small to medium projects. Human-readable, easy to version control, and requires no additional dependencies.

```
codegiraffe_init(project_path="/home/user/my-project", backend="json")
```

### SQLite

Graphs are stored in a SQLite database at `{project_path}/.codegiraffe/graph.db`. Better for larger projects where JSON serialization becomes a bottleneck. Supports concurrent reads and uses less memory for large graphs.

```
codegiraffe_init(project_path="/home/user/large-project", backend="sqlite")
```

Both backends implement the `StorageBackend` protocol, so switching between them is transparent to the rest of the system. Manual annotations and graph structure are preserved identically regardless of backend.

## Multi-Language Scanner

Code Giraffe uses a plugin-based scanner architecture built on the `RecognizerRegistry`. Each language has a dedicated recognizer that detects framework-specific patterns using regex matching (not AST parsing) for speed and simplicity. The Python recognizer is built into the core scanner; additional languages are provided by recognizer plugins registered by file extension.

### Python (.py, .pyi)

- **Flask / FastAPI**: `@app.route()`, `@router.get()`, `@router.post()`, etc. --> `endpoint` nodes
- **SQLAlchemy**: Classes inheriting from `Base` or `db.Model` with `__tablename__` --> `database_table` nodes
- **Celery**: `@app.task`, `@shared_task`, `@celery.task` --> `worker` nodes
- **Environment**: `os.environ["KEY"]`, `os.getenv("KEY")` --> `env_var` nodes
- **HTTP clients**: `requests.get()`, `requests.post()`, etc. --> `external_api` nodes
- **Class definitions** --> `service` nodes

### TypeScript (.ts, .tsx, .mts, .cts)

- **Express / Fastify / Koa**: Route handler patterns --> `endpoint` nodes
- **NestJS**: `@Get()`, `@Post()`, `@Controller()` decorators --> `endpoint` nodes
- **TypeORM**: `@Entity()` decorators --> `database_table` nodes
- **Prisma**: `prisma.model.find*`, `prisma.model.create`, etc. --> `database_table` nodes
- **Environment**: `process.env.KEY` --> `env_var` nodes
- **HTTP clients**: `fetch()`, `axios.*` calls --> `external_api` nodes
- **Event emitters**: `emit()`, `on()` patterns --> `event` nodes
- **React / Vue**: Component definitions --> `frontend_component` nodes
- **Bull / BullMQ**: Queue patterns --> `queue` / `worker` nodes

### Go (.go)

- **net/http**: `http.HandleFunc()`, `http.Handle()` --> `endpoint` nodes
- **Gin / Echo / Chi**: Router method patterns --> `endpoint` nodes
- **GORM**: Model struct patterns --> `database_table` nodes
- **db.Table**: Direct table references --> `database_table` nodes
- **Environment**: `os.Getenv()` --> `env_var` nodes
- **HTTP clients**: `http.Get()`, `http.Post()` --> `external_api` nodes

### Rust (.rs)

- **Actix / Rocket**: Route attribute macros (`#[get()]`, `#[post()]`) --> `endpoint` nodes
- **Axum**: Router method patterns --> `endpoint` nodes
- **Diesel**: `table!` macro, `#[derive(Queryable)]` --> `database_table` nodes
- **Environment**: `env::var()`, `env!()` --> `env_var` nodes
- **HTTP clients**: `reqwest::get()`, `reqwest::Client` --> `external_api` nodes

### Java (.java)

- **Spring**: `@GetMapping`, `@PostMapping`, `@RequestMapping` --> `endpoint` nodes
- **JPA**: `@Entity`, `@Table` annotations --> `database_table` nodes
- **Environment**: `System.getenv()`, `@Value("${...}")` --> `env_var` nodes
- **HTTP clients**: `RestTemplate`, `WebClient` --> `external_api` nodes
- **Messaging**: `@RabbitListener`, `@KafkaListener` --> `worker` nodes

### Plugin System

The `RecognizerRegistry` maps file extensions to recognizer classes. The registry is pre-populated with all built-in recognizers, but custom recognizers can be added by implementing the `PatternRecognizer` protocol and registering them for the appropriate file extensions.

Cross-file edge inference connects endpoints to database tables when a file references model class names from other files, regardless of language.

## Embedding-Based Scoring

The `codegiraffe_context_for` tool supports two scoring modes for ranking node relevance:

### Keyword Scoring (default fallback)

Uses keyword overlap between the task description and node labels, IDs, and metadata. Always available, requires no extra dependencies.

### Embedding-Based Scoring (optional)

When `sentence-transformers` is installed, scoring uses semantic embeddings to find relevant nodes even when exact keywords don't match. For example, a query about "authentication" will correctly surface nodes labeled "login", "JWT", and "session" even without keyword overlap.

**Install embedding support:**

```bash
uv pip install -e ".[embeddings]"
# or
pip install codegiraffe[embeddings]
```

Embedding scoring is enabled by default when the dependency is available. To force keyword-only scoring, pass `use_embeddings=false`:

```
codegiraffe_context_for(
  project_path="/home/user/my-project",
  task="refactor the authentication flow",
  use_embeddings=false
)
```

## Multi-Agent Coordination

When multiple AI agents work on the same codebase simultaneously, Code Giraffe provides coordination tools to prevent conflicts.

### How It Works

1. **Claim** -- Before modifying part of the architecture, an agent claims the relevant nodes using `codegiraffe_claim`. If another agent already holds a conflicting claim, the request fails with details about the conflict.
2. **Status** -- While working, agents update their status (`"active"`, `"blocked"`, `"done"`) using `codegiraffe_status`. Active updates refresh the claim TTL so it doesn't expire during long-running tasks.
3. **Visibility** -- Any agent can call `codegiraffe_agents` to see who is working on what, enabling informed coordination decisions.
4. **Expiration** -- Claims automatically expire after their TTL (default: 30 minutes) to prevent deadlocks from crashed or abandoned agents.

### Example Workflow

```
# Agent 1 claims the payments subsystem
codegiraffe_claim(project_path="...", agent_id="agent-1",
  node_ids=["endpoint:/api/payments", "service:PaymentService"],
  task="Add Stripe webhook handler", ttl=1800)

# Agent 2 tries to claim an overlapping node -- gets a conflict
codegiraffe_claim(project_path="...", agent_id="agent-2",
  node_ids=["service:PaymentService"],
  task="Refactor payment validation")
--> {"status": "conflict", "conflicting_agent": "agent-1", ...}

# Agent 2 checks who is working where
codegiraffe_agents(project_path="...")
--> Shows agent-1 is active on PaymentService

# Agent 1 finishes and releases its claims
codegiraffe_status(project_path="...", agent_id="agent-1", status="done")

# Agent 2 can now claim successfully
codegiraffe_claim(project_path="...", agent_id="agent-2",
  node_ids=["service:PaymentService"],
  task="Refactor payment validation")
--> {"status": "claimed", ...}
```

## Usage Patterns

### Orchestrator + Subagent Workflow

The most powerful pattern is using Code Giraffe as context for an orchestrator that delegates to subagents:

1. **Orchestrator** calls `codegiraffe_context_for(task="add rate limiting to payments")`
2. **Code Giraffe** returns the relevant subgraph (payments endpoint, its DB tables, middleware, env vars)
3. **Orchestrator** includes this context in the subagent's prompt
4. **Subagent** has exactly the architectural knowledge it needs -- no wasted tokens

### Continuous Graph Maintenance

```
1. codegiraffe_init()          --> Bootstrap on first use
2. codegiraffe_add_relation()  --> Annotate what the scanner missed
3. codegiraffe_sync()          --> Update after code changes
4. codegiraffe_detect_drift()  --> Catch stale graph entries
5. codegiraffe_export()        --> Generate diagrams for documentation
```

### Pre-Change Impact Analysis

Before modifying any code:

```
1. codegiraffe_query(node_id="endpoint:/api/payments", depth=3)
   --> See everything connected to the endpoint within 3 hops
2. codegiraffe_hotspots(top_n=5)
   --> Know which areas are most coupled and risky to change
3. codegiraffe_export(format="mermaid", node_id="endpoint:/api/payments", depth=2)
   --> Visualize the subgraph for documentation or review
```

### Multi-Agent Development

When running multiple agents in parallel:

```
1. codegiraffe_agents()            --> See who is working where
2. codegiraffe_claim(...)          --> Claim nodes before modifying them
3. codegiraffe_status(..., "active") --> Keep claim alive while working
4. codegiraffe_status(..., "done")   --> Release claims when finished
```

## Development

### Running Tests

```bash
uv pip install -e ".[dev]"
python -m pytest tests/ -v
```

231 tests covering graph operations, storage backends, scanner, recognizers, query engine, export, embeddings, coordination, and drift detection.

### Project Constitution

The project follows a formal constitution at `.specify/memory/constitution.md` with 7 core principles:

1. **MCP-Native** -- Everything exposed as MCP tools
2. **Graph-First** -- Directed graph with typed nodes and edges
3. **Beyond-AST** -- Capture what static analysis can't see
4. **Context Efficiency** -- Minimal relevant context, always
5. **Incremental** -- Non-destructive updates, manual annotations survive
6. **Test-First** -- TDD mandatory
7. **Simplicity** -- JSON storage, regex scanning, YAGNI

## Roadmap

### v0.2.0 (completed)

- [x] Multi-language scanner support (TypeScript, Go, Rust, Java)
- [x] SQLite storage backend for larger graphs
- [x] Graph visualization export (Mermaid, D3.js)
- [x] Richer drift detection with rename tracking
- [x] Embedding-based context scoring (replace keyword matching)
- [x] Multi-agent status coordination tools
- [x] Plugin system for custom recognizers

### Future

- [ ] Publish to PyPI
- [ ] CI/CD pipeline (GitHub Actions)
- [ ] Neo4j storage backend
- [ ] AST-aware scanning (tree-sitter)
- [ ] Cross-repo graph federation
- [ ] Web dashboard
- [ ] Schema evolution/versioning

## License

MIT

## Contributing

Contributions welcome. Please follow the project constitution and ensure all tests pass before submitting PRs.

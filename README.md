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

For Neo4j storage backend (optional):

```bash
uv pip install -e ".[neo4j]"
```

For AST-aware scanning (optional):

```bash
uv pip install -e ".[ast]"
```

Or install optional features with pip:

```bash
pip install -e ".[embeddings]"   # Embedding-based scoring
pip install -e ".[neo4j]"        # Neo4j storage backend
pip install -e ".[ast]"          # AST-aware scanning
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

Code Giraffe exposes 25 tools that any MCP client can call:

### `codegiraffe_init`

Scan a project and bootstrap the architecture knowledge graph.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `project_path` | `str` | required | Root directory of the project to scan |
| `rescan` | `bool` | `false` | Re-scan while preserving manual annotations |
| `backend` | `str` | `"json"` | Storage backend: `"json"`, `"sqlite"`, or `"neo4j"` |
| `scanner_mode` | `str` | `"regex"` | Scanner mode: `"regex"` (default) or `"ast"` (tree-sitter) |
| `include_tests` | `bool` | `false` | Include test files in the scan (excluded by default) |

**Example:**
```
codegiraffe_init(project_path="/home/user/my-project")
--> "Initialized graph with 47 nodes and 63 edges"

codegiraffe_init(project_path="/home/user/large-project", backend="sqlite")
--> "Initialized graph with 312 nodes and 487 edges"
```

The scanner automatically detects architectural patterns across 9 languages. See the [Multi-Language Scanner](#multi-language-scanner) section for details on what each language recognizer detects.

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
| `include_impact` | `bool` | `false` | Include blast radius and risk assessment for top nodes |

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

Reports four kinds of drift:

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
| `metrics` | `list[str] \| None` | `None` | Metrics to include: `"degree"`, `"betweenness"`, `"risk"` (None = degree only) |

**Example:**
```
codegiraffe_hotspots(project_path="/home/user/my-project", top_n=5)
--> [{"node_id": "service:AuthService", "label": "Auth Service", "type": "service", "score": 0.4231}]
```

---

### `codegiraffe_sync`

Re-scan the project and synchronize the architecture graph, preserving manual annotations.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `project_path` | `str` | required | Root directory of the project |
| `include_tests` | `bool` | `false` | Include test files in the scan (excluded by default) |

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
| `module` | Rectangle |
| `contract` | Hexagon |

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

---

### `codegiraffe_history`

List version history for a project's architecture graph. Returns timestamped entries with diff summaries.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `project_path` | `str` | required | Root directory of the project |
| `limit` | `int` | `20` | Maximum number of versions to return |

**Example:**
```
codegiraffe_history(project_path="/home/user/my-project")
--> [{"version_id": 3, "timestamp": "...", "message": "Sync", "nodes_added": 2, "nodes_removed": 0, ...}]
```

---

### `codegiraffe_diff`

Compare two versions of the architecture graph, or view a specific version's diff.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `project_path` | `str` | required | Root directory of the project |
| `version_a` | `int` | required | Version ID to inspect or compare |
| `version_b` | `int \| None` | `None` | Second version ID for comparison |

**Example:**
```
codegiraffe_diff(project_path="/home/user/my-project", version_a=3)
--> {"nodes_added": ["service:NewSvc"], "nodes_removed": [], "edges_added": [...], ...}
```

---

### `codegiraffe_snapshot`

Create a named snapshot of the current graph state for bookmarking before changes.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `project_path` | `str` | required | Root directory of the project |
| `message` | `str` | `"Manual snapshot"` | Descriptive message for this snapshot |

**Example:**
```
codegiraffe_snapshot(project_path="/home/user/my-project", message="Before auth refactor")
--> {"version_id": 4, "message": "Before auth refactor", "timestamp": "..."}
```

---

### `codegiraffe_restore`

Restore the architecture graph to a specific version. Automatically creates a backup snapshot first.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `project_path` | `str` | required | Root directory of the project |
| `version_id` | `int` | required | Version ID to restore to |

Note: Currently supports diff-based history only. Full snapshot restore is planned.

---

### `codegiraffe_federate`

Register multiple repositories into a federated view, combining their architecture graphs.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `project_paths` | `list[str]` | required | List of project root directories to federate |

**Example:**
```
codegiraffe_federate(project_paths=["/home/user/api", "/home/user/frontend"])
--> {"repos": ["api", "frontend"], "total_nodes": 285, "total_edges": 412}
```

---

### `codegiraffe_cross_query`

Query across federated graphs using repo-namespaced node IDs.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `node_id` | `str` | required | Namespaced node ID (e.g., `"repo:api::endpoint:/users"`) |
| `depth` | `int` | `2` | Maximum hops from the queried node |

**Example:**
```
codegiraffe_cross_query(node_id="repo:api::endpoint:/api/users", depth=2)
--> JSON subgraph spanning both repos
```

---

### `codegiraffe_cross_edges`

List all edges that cross repository boundaries in the federated graph.

**Example:**
```
codegiraffe_cross_edges()
--> [{"source": "repo:api::endpoint:/users", "target": "repo:frontend::component:UserList", "type": "cross_repo_calls"}]
```

---

### `codegiraffe_cypher`

Run a read-only Cypher query against a Neo4j-backed graph. Requires `neo4j` backend.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `project_path` | `str` | required | Root directory of the project |
| `query` | `str` | required | Read-only Cypher query |

**Example:**
```
codegiraffe_cypher(project_path="/home/user/my-project", query="MATCH (n:endpoint) RETURN n.label, n.id LIMIT 10")
--> [{"n.label": "GET /api/users", "n.id": "endpoint:/api/users"}, ...]
```

### `codegiraffe_blast_radius`

Analyze the blast radius of changing a specific node. Returns what breaks downstream, ranked by severity (direct, transitive, indirect), plus any circular dependencies and hotspots.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `project_path` | `str` | required | Root directory of the project |
| `node_id` | `str` | required | Node to analyze blast radius for |
| `include_upstream` | `bool` | `false` | Include upstream dependencies |
| `max_depth` | `int \| None` | `None` | Limit analysis to N hops |

**Example:**
```
codegiraffe_blast_radius(
  project_path="/home/user/my-project",
  node_id="service:AuthService",
  include_upstream=true
)
--> {"node_id": "service:AuthService", "direct": [...], "transitive": [...], "indirect": [...], "hotspots": [...], "cycles": [...]}
```

---

### `codegiraffe_risk_assessment`

Assess architectural risk for nodes. Risk = (degree * 0.4) + (betweenness * 0.4) + (descendants/total * 0.2).

| Parameter | Type | Default | Description |
|---|---|---|---|
| `project_path` | `str` | required | Root directory of the project |
| `node_ids` | `list[str] \| None` | `None` | Specific nodes to assess (None = top 10) |

**Example:**
```
codegiraffe_risk_assessment(project_path="/home/user/my-project")
--> [{"node_id": "service:AuthService", "risk_score": 0.82, "degree": 12, "betweenness": 0.45, "descendants": 8}, ...]
```

---

### `codegiraffe_cycles`

Detect circular dependencies in the architecture graph.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `project_path` | `str` | required | Root directory of the project |
| `max_cycles` | `int` | `20` | Maximum number of cycles to detect |

**Example:**
```
codegiraffe_cycles(project_path="/home/user/my-project", max_cycles=10)
--> [{"cycle": ["service:A", "service:B", "service:C", "service:A"], "length": 3}, ...]
```

---

### `codegiraffe_contracts`

List and filter cross-system contracts in the architecture graph. Contracts represent API schemas, event schemas, configuration contracts, and data contracts that couple different parts of the system.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `project_path` | `str` | required | Root directory of the project |
| `contract_type` | `str \| None` | `None` | Filter by contract type: `"api"`, `"event"`, `"config"`, `"data"` |
| `status` | `str \| None` | `None` | Filter by validation status |

**Example:**
```
codegiraffe_contracts(project_path="/home/user/my-project", contract_type="api")
--> [{"id": "contract:api:/api/users", "type": "api", "producers": [...], "consumers": [...], "status": "valid"}]
```

---

### `codegiraffe_validate_contracts`

Validate the integrity of cross-system contracts. Checks that all contract producers and consumers exist, that contracts have at least one producer, and detects orphaned or broken contracts.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `project_path` | `str` | required | Root directory of the project |

**Example:**
```
codegiraffe_validate_contracts(project_path="/home/user/my-project")
--> {"valid": 12, "warnings": 2, "errors": 1, "details": [...]}
```

---

### `codegiraffe_add_contract`

Manually create a cross-system contract node with its producer and consumer relationships. The contract node and its edges are marked as manual so they survive re-scans.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `project_path` | `str` | required | Root directory of the project |
| `contract_id` | `str` | required | Unique contract identifier |
| `contract_type` | `str` | required | Contract type: `"api"`, `"event"`, `"config"`, `"data"` |
| `producers` | `list[str]` | `[]` | Node IDs that produce/define this contract |
| `consumers` | `list[str]` | `[]` | Node IDs that consume/depend on this contract |
| `metadata` | `str` | `"{}"` | JSON string of extra key-value pairs |

**Example:**
```
codegiraffe_add_contract(
  project_path="/home/user/my-project",
  contract_id="contract:api:user-schema",
  contract_type="api",
  producers=["endpoint:/api/users"],
  consumers=["component:UserList", "service:UserSync"]
)
--> "Created contract contract:api:user-schema with 1 producer(s) and 2 consumer(s)"
```

---

## Architecture

```
src/codegiraffe/
├── server.py            # FastMCP server + 25 tool definitions
├── graph.py             # Pydantic models (Node, Edge, GraphData) + NetworkX ArchGraph engine
├── storage.py           # StorageBackend protocol + JSON file implementation
├── sqlite_storage.py    # SQLite storage backend for larger graphs
├── scanner.py           # Multi-language codebase scanner (dispatches to recognizers)
├── registry.py          # RecognizerRegistry plugin system with extension mapping
├── query.py             # Subgraph extraction, keyword scoring, drift detection
├── embeddings.py        # Optional embedding-based semantic scoring (sentence-transformers)
├── export.py            # Graph visualization export (Mermaid + D3.js JSON)
├── coordination.py      # Multi-agent claim/status coordination with TTL
├── versioning.py        # Schema evolution, diffs, version history
├── federation.py        # Cross-repo graph federation
├── neo4j_storage.py     # Neo4j storage backend (optional)
├── ast_scanner.py       # tree-sitter AST-based scanning (optional)
├── dashboard.py         # Web dashboard (Cytoscape.js, served via HTTP)
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

**Node types:** `service`, `endpoint`, `database_table`, `queue`, `env_var`, `config`, `worker`, `frontend_component`, `event`, `external_api`, `module`, `contract`

**Edge types:** `calls`, `reads`, `writes`, `publishes`, `consumes`, `depends_on`, `configures`, `owns`, `triggers`, `imports`, `implements`, `contains`, `produces`, `consumes_contract`, `validates`, `violates`, `cross_repo_calls`, `cross_repo_depends_on`, `cross_repo_publishes`, `cross_repo_consumes`

Custom types are fully supported -- any string works as a node or edge type.

## Storage Backends

Code Giraffe supports three storage backends, selectable via the `backend` parameter on `codegiraffe_init`:

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

### Neo4j (optional)

For enterprise-scale graphs, Code Giraffe supports Neo4j as a storage backend. Requires a running Neo4j instance and the `neo4j` Python driver.

```bash
uv pip install -e ".[neo4j]"
```

Configure via environment variables:
- `NEO4J_URI` -- Connection URI (default: `neo4j://localhost:7687`)
- `NEO4J_USER` -- Database user (default: `neo4j`)
- `NEO4J_PASSWORD` -- Database password (required for authenticated access)

```
codegiraffe_init(project_path="/home/user/enterprise-project", backend="neo4j")
```

Use `codegiraffe_cypher` to run read-only Cypher queries directly against the graph for advanced analysis.

All backends implement the `StorageBackend` protocol, so switching between them is transparent to the rest of the system. Manual annotations and graph structure are preserved identically regardless of backend.

## Multi-Language Scanner

Code Giraffe uses a plugin-based scanner architecture built on the `RecognizerRegistry`. Each language has a dedicated recognizer that detects framework-specific patterns using regex matching (not AST parsing) for speed and simplicity. The Python recognizer is built into the core scanner; additional languages are provided by recognizer plugins registered by file extension.

### Scanner Intelligence (v0.4.0 -- v0.6.0)

The scanner includes several intelligence features that produce a richer, more accurate architecture graph. Originally introduced for Python in v0.4.0, these capabilities were extended to all 9 supported languages in v0.6.0 via the `ImportInfo` and `ImplementationInfo` data classes on `ScanResult`.

- **Test file exclusion** -- Test files are excluded by default across all languages (Python: `test_*.py`, `*_test.py`, `conftest.py`; Go: `*_test.go`; Java: `*Test.java`; Rust: test modules; TypeScript: `*.spec.ts`, `*.test.ts`; etc.). Pass `include_tests=true` to include them; test-sourced nodes are tagged with `"source": "test"` metadata.
- **Module nodes** -- Each source file produces a `module` node (e.g., `mod:codegiraffe.scanner` for Python, `mod:github.com/user/pkg` for Go) with `contains` edges to every entity defined in that file.
- **Import detection** -- The scanner detects import statements in all 9 languages, resolves them to project-internal modules (skipping standard library and third-party dependencies), and creates `imports` edges between `module` nodes with metadata listing the imported symbols. Go uses `go.mod`-aware module path resolution.
- **Inheritance / implementation detection** -- Class definitions with base classes (or interface implementations in Go) produce `implements` edges from child to parent when both are defined within the project. External base classes are silently skipped.

| Language | Module Nodes | Import Detection | Implementation Detection | Test Exclusion |
|---|---|---|---|---|
| Python | Yes | Yes (absolute + relative) | Yes (class inheritance) | Yes |
| TypeScript | Yes | Yes (`import`/`require`) | Yes (`extends`/`implements`) | Yes |
| Go | Yes | Yes (`go.mod`-aware) | Yes (interface implementation) | Yes |
| Rust | Yes | Yes (`use`/`mod`) | Yes (`impl Trait for`) | Yes |
| Java | Yes | Yes (`import`) | Yes (`extends`/`implements`) | Yes |
| C/C++ | Yes | Yes (`#include`) | Yes (class inheritance) | Yes |
| C# | Yes | Yes (`using`) | Yes (class/interface inheritance) | Yes |
| PHP | Yes | Yes (`use`/`namespace`) | Yes (`extends`/`implements`) | Yes |
| Ruby | Yes | Yes (`require`/`require_relative`) | Yes (class inheritance, module `include`) | Yes |

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

### C/C++ (.c, .cpp, .h, .hpp)

- **Endpoints**: HTTP server handler patterns --> `endpoint` nodes
- **Database**: SQL query patterns, database connection strings --> `database_table` nodes
- **Environment**: `getenv()`, `std::getenv()` --> `env_var` nodes
- **HTTP clients**: `curl_easy_*`, `httplib::Client` --> `external_api` nodes

### C# (.cs)

- **ASP.NET**: `[HttpGet]`, `[HttpPost]`, `[Route]` attributes --> `endpoint` nodes
- **Entity Framework**: `DbSet<>`, `[Table]` attributes --> `database_table` nodes
- **Environment**: `Environment.GetEnvironmentVariable()`, `IConfiguration` --> `env_var` nodes
- **HTTP clients**: `HttpClient`, `RestClient` --> `external_api` nodes
- **Messaging**: `[ServiceBusListener]`, RabbitMQ patterns --> `worker` nodes

### PHP (.php)

- **Laravel / Symfony**: Route definitions, controller annotations --> `endpoint` nodes
- **Eloquent / Doctrine**: Model and entity patterns --> `database_table` nodes
- **Environment**: `getenv()`, `$_ENV`, `env()` --> `env_var` nodes
- **HTTP clients**: `Guzzle`, `curl_*`, `file_get_contents` --> `external_api` nodes
- **Queues**: Laravel queue worker patterns --> `worker` nodes

### Ruby (.rb)

- **Rails**: Route definitions, controller actions --> `endpoint` nodes
- **ActiveRecord**: Model class patterns, `create_table` migrations --> `database_table` nodes
- **Environment**: `ENV["KEY"]`, `ENV.fetch` --> `env_var` nodes
- **HTTP clients**: `Net::HTTP`, `Faraday`, `HTTParty` --> `external_api` nodes
- **Sidekiq / ActiveJob**: Worker and job class patterns --> `worker` nodes

### Plugin System

The `RecognizerRegistry` maps file extensions to recognizer classes. The registry is pre-populated with all built-in recognizers, but custom recognizers can be added by implementing the `PatternRecognizer` protocol and registering them for the appropriate file extensions.

Cross-file edge inference connects endpoints to database tables when a file references model class names from other files, regardless of language.

### AST-Aware Scanning (optional)

For more accurate pattern detection, install tree-sitter support:

```bash
uv pip install -e ".[ast]"
```

Then use `scanner_mode="ast"` when initializing:

```
codegiraffe_init(project_path="/home/user/my-project", scanner_mode="ast")
```

AST scanning detects the same patterns as regex scanning but with higher accuracy -- it understands actual syntax trees rather than pattern matching raw text. Particularly useful for complex nested patterns and avoiding false positives.

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

## Schema Evolution & Versioning

Code Giraffe tracks how your architecture graph changes over time. Every `codegiraffe_sync` and `codegiraffe_init(rescan=True)` automatically creates a version.

### Automatic Versioning

Version history is stored at `{project_path}/.codegiraffe/versions.json` as diffs (not full snapshots) for storage efficiency. Maximum 100 versions are retained by default.

### Manual Snapshots

Create named bookmarks before making significant changes:

```
codegiraffe_snapshot(project_path="...", message="Before payment refactor")
```

### Viewing History

```
codegiraffe_history(project_path="...")
--> [{version_id: 1, message: "Init", timestamp: "...", nodes_added: 47, ...}, ...]

codegiraffe_diff(project_path="...", version_a=3)
--> {nodes_added: [...], nodes_removed: [...], edges_added: [...], attrs_changed: [...]}
```

## Cross-Repo Federation

Link architecture graphs from multiple repositories into a unified federated view.

### How It Works

1. **Register** repos using `codegiraffe_federate` with a list of project paths
2. Nodes are namespaced with `repo:{name}::` prefixes to avoid collisions
3. Cross-repo edges use types like `cross_repo_calls`, `cross_repo_depends_on`, `cross_repo_publishes`, `cross_repo_consumes`
4. Query across repos using `codegiraffe_cross_query` with namespaced IDs

### Example

```
# Register two repos
codegiraffe_federate(project_paths=["/home/user/api", "/home/user/frontend"])

# Add a cross-repo relationship
codegiraffe_add_relation(
  project_path="/home/user/api",
  source="repo:api::endpoint:/api/users",
  target="repo:frontend::component:UserList",
  relation_type="cross_repo_calls"
)

# Find all cross-repo edges
codegiraffe_cross_edges()
--> Shows all edges crossing repo boundaries
```

Federation metadata is stored globally at `~/.codegiraffe/federation.json`.

## Web Dashboard

Code Giraffe includes a built-in web dashboard for interactive graph exploration. No additional dependencies required — it uses Cytoscape.js loaded from CDN and is served via FastMCP's HTTP routes.

### Launching the Dashboard

Start the server with HTTP transport:

```bash
python src/codegiraffe/server.py --transport streamable-http --port 8000
```

Then open `http://localhost:8000/dashboard` in your browser.

### Features

- **Interactive graph visualization** — Pan, zoom, click nodes for details
- **Node type filtering** — Toggle visibility by type (endpoint, service, database_table, etc.)
- **Search** — Filter nodes by label or ID in real-time
- **Node detail panel** — Click any node to see its properties, metadata, and connected edges
- **Subgraph focus** — Double-click a node to zoom into its neighborhood
- **5 layout algorithms** — Force-directed (cose), circular, grid, concentric, and breadthfirst layouts
- **Legend & stats** — Visual legend of node types and real-time graph statistics
- **Edge tooltips** — Hover edges to see relationship type and metadata
- **PNG export** — Download the current view as an image
- **Dark theme** — Developer-friendly dark interface with refined color palette

### API Endpoints

The dashboard also exposes JSON API endpoints for programmatic access:

| Endpoint | Description |
|---|---|
| `POST /api/init` | Initialize/scan a project (body: `{"project_path": "..."}`) |
| `GET /api/graph?project_path=...` | Full graph as D3.js-compatible JSON |
| `GET /api/node?project_path=...&node_id=...` | Node detail with connected edges |
| `GET /api/subgraph?project_path=...&node_id=...&depth=2` | Subgraph centered on a node |

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

### Cross-System Contracts

Code Giraffe models cross-system contracts -- API schemas, event schemas, configuration contracts, and data contracts -- as first-class `contract` nodes in the architecture graph. Contracts capture the coupling between producers (who define the contract) and consumers (who depend on it), making it possible to understand the full impact of schema changes, API modifications, and event format updates.

The scanner automatically infers contracts from detected patterns (e.g., API endpoints become API contracts, event emitters become event contracts). You can also create contracts manually:

```
1. codegiraffe_add_contract(contract_id="contract:api:user-schema", contract_type="api",
     producers=["endpoint:/api/users"], consumers=["component:UserList"])
   --> Create a contract with explicit producer/consumer relationships

2. codegiraffe_contracts(contract_type="api")
   --> List all API contracts with their producers and consumers

3. codegiraffe_validate_contracts()
   --> Check contract integrity (orphaned consumers, missing producers, etc.)
```

Contract-aware blast radius analysis automatically flags contract consumers as **critical** severity, ensuring that changes to shared contracts surface all downstream impact.

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

791+ tests covering graph operations, storage backends (JSON, SQLite, Neo4j), scanner (regex, AST, and intelligence features), recognizers (all 9 languages with import/implementation detection), query engine, schema types, export, embeddings, coordination, drift detection, versioning, federation, web dashboard, blast radius analysis, risk assessment, cycle detection, and cross-system contracts.

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

### v0.2.1 (completed)

- [x] CI/CD pipeline (GitHub Actions — Python 3.11/3.12/3.13 matrix)
- [x] Enhanced Go recognizer (imports, interfaces, events, IPC, SQL)

### v0.3.0 (completed)

- [x] Neo4j storage backend (optional `neo4j` dependency)
- [x] AST-aware scanning via tree-sitter (optional `ast` dependency)
- [x] Cross-repo graph federation with namespace isolation
- [x] Schema evolution and versioning with auto-versioning on sync/init
- [x] 8 new MCP tools (19 total)

### v0.3.1 (completed)

- [x] Interactive web dashboard with Cytoscape.js graph visualization

### v0.4.0 (completed)

- [x] Scanner intelligence: test file exclusion (default), import detection, inheritance detection, module nodes
- [x] New node type: `module` with `contains` edges to file-level entities
- [x] New edge types: `imports` (inter-module), `implements` (inheritance), `contains` (module-to-entity)
- [x] `include_tests` parameter for `codegiraffe_init` and `codegiraffe_sync`
- [x] 505+ tests

### v0.5.0 (completed)

- [x] 4 new language recognizers: C#, C/C++, PHP, Ruby (now 9 languages)
- [x] 3 new dashboard layouts: grid, concentric, breadthfirst (now 5 total)
- [x] Dashboard improvements: legend, stats panel, edge tooltips, refined color palette
- [x] 566+ tests

### v0.6.0 (completed)

- [x] Language-agnostic scanner intelligence: universal module nodes, `contains` edges, import detection, and implementation/inheritance detection for all 9 languages
- [x] `ImportInfo` and `ImplementationInfo` data classes on `ScanResult` for structured recognizer output
- [x] Go `go.mod`-aware import path resolution and interface implementation detection
- [x] Test file exclusion extended to all 9 languages
- [x] 698+ tests

### v0.7.0 (completed)

- [x] 3 new MCP tools: `codegiraffe_blast_radius`, `codegiraffe_risk_assessment`, `codegiraffe_cycles` (22 tools total)
- [x] Blast radius analysis: downstream impact ranked by severity (direct, transitive, indirect)
- [x] Risk assessment: composite score from degree centrality, betweenness centrality, and descendant count
- [x] Cycle detection: find circular dependencies in the architecture graph
- [x] Enhanced `codegiraffe_context_for` with `include_impact` parameter for blast radius + risk on top nodes
- [x] Enhanced `codegiraffe_hotspots` with `metrics` parameter for multi-metric analysis
- [x] 754+ tests

### v0.8.0 (completed)

- [x] 3 new MCP tools: `codegiraffe_contracts`, `codegiraffe_validate_contracts`, `codegiraffe_add_contract` (25 tools total)
- [x] Cross-system contract modeling: `contract` node type with `produces`, `consumes_contract`, `validates`, `violates` edge types
- [x] Contract inference: automatic detection of API, event, config, and data contracts from scanned patterns
- [x] Contract-aware blast radius: contract consumers receive critical severity in impact analysis
- [x] Contract validation: integrity checks for producer/consumer relationships
- [x] Dashboard contract styling: hexagonal purple nodes for contract visualization
- [x] 791+ tests

### Future

- [ ] Publish to PyPI

## License

MIT

## Contributing

Contributions welcome. Please follow the project constitution and ensure all tests pass before submitting PRs.

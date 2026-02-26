[← Back to Documentation](../README.md) | [Tool Index](README.md)

# Core Tools

The core tools handle the fundamental lifecycle of the architecture graph: initializing from a scan, querying the stored data, manually annotating relationships, keeping the graph in sync, exporting it, and detecting drift from the real codebase.

---

### `codegiraffe_init`

Scan a project and bootstrap the architecture knowledge graph.

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_path` | `str` | — | yes | Root directory of the project to scan |
| `rescan` | `bool` | `false` | no | Re-scan while preserving manual annotations |
| `backend` | `str` | `"json"` | no | Storage backend: `"json"`, `"sqlite"`, or `"neo4j"` |
| `scanner_mode` | `str` | `"hybrid"` | no | Scanner mode: `"hybrid"` (default, regex + AST with fallback), `"regex"`, or `"ast"` (tree-sitter only) |
| `include_tests` | `bool` | `false` | no | Include test files in the scan (excluded by default) |

**Example:**
```
codegiraffe_init(project_path="/home/user/my-project")
--> "Initialized graph with 47 nodes and 63 edges"

codegiraffe_init(project_path="/home/user/large-project", backend="sqlite")
--> "Initialized graph with 312 nodes and 487 edges"
```

The scanner automatically detects architectural patterns across 9 languages.

---

### `codegiraffe_query`

Query the graph by node ID or type. Returns a scoped subgraph — not the full graph — to conserve tokens.

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_path` | `str` | — | yes | Root directory of the project |
| `node_id` | `str \| None` | `None` | no | Node ID for subgraph extraction |
| `node_type` | `str \| None` | `None` | no | Node type for type-based filtering |
| `depth` | `int` | `2` | no | Maximum hops from the queried node |

**Example:**
```
codegiraffe_query(project_path="/home/user/my-project", node_id="endpoint:/api/users", depth=2)
--> JSON subgraph with the endpoint, its DB tables, services, and env vars within 2 hops
```

---

### `codegiraffe_add_relation`

Manually annotate a relationship that automated scanning missed. Manual annotations survive re-scans.

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_path` | `str` | — | yes | Root directory of the project |
| `source` | `str` | — | yes | Source node ID |
| `target` | `str` | — | yes | Target node ID |
| `relation_type` | `str` | — | yes | Relationship type (e.g., `"publishes_to"`) |
| `source_type` | `str` | `"service"` | no | Node type if source needs to be auto-created |
| `target_type` | `str` | `"service"` | no | Node type if target needs to be auto-created |
| `metadata` | `str` | `"{}"` | no | JSON string of extra key-value pairs |

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

### `codegiraffe_sync`

Re-scan the project and synchronize the architecture graph, preserving manual annotations.

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_path` | `str` | — | yes | Root directory of the project |
| `include_tests` | `bool` | `false` | no | Include test files in the scan (excluded by default) |

**Example:**
```
codegiraffe_sync(project_path="/home/user/my-project")
--> "Sync complete. Nodes: 47 -> 52 (delta +5). Edges: 63 -> 71 (delta +8)."
```

---

### `codegiraffe_sync_files`

Incrementally sync specific changed files without a full rescan. Faster than `codegiraffe_sync` for small changes.

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_path` | `str` | — | yes | Root directory of the project |
| `file_paths` | `str` | — | yes | Comma-separated or JSON array string of absolute or relative file paths to sync |
| `scanner_mode` | `str` | `"hybrid"` | no | Scanner mode: `"hybrid"` (default, regex + AST with fallback), `"regex"`, or `"ast"` (tree-sitter only) |

**Example:**
```
codegiraffe_sync_files(
  project_path="/home/user/my-project",
  file_paths=["src/auth.py", "src/users.py"]
)
--> "Synced 2 files. Nodes: 47 -> 49 (delta +2). Edges: 63 -> 66 (delta +3)."
```

---

### `codegiraffe_export`

Export the architecture graph as a visualization format for documentation or dashboards.

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_path` | `str` | — | yes | Root directory of the project |
| `format` | `str` | `"mermaid"` | no | Export format: `"mermaid"` or `"d3"` |
| `direction` | `str` | `"TD"` | no | Mermaid direction: `"TD"`, `"LR"`, `"BT"`, `"RL"` |
| `subgraph_by_type` | `bool` | `true` | no | Group nodes by type in Mermaid output |
| `node_id` | `str \| None` | `None` | no | Scope export to subgraph around this node |
| `depth` | `int` | `2` | no | Subgraph depth when `node_id` is provided |

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

### `codegiraffe_detect_drift`

Check if the graph still matches the actual codebase. Re-scans the project and compares results against the stored graph.

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_path` | `str` | — | yes | Root directory of the project |

Reports four kinds of drift:

- **missing_in_code** — Nodes in the graph that no longer exist in the codebase
- **missing_in_graph** — Patterns found in code that are not in the graph
- **rename_candidate** — Nodes that appear to have been renamed (based on similarity matching)
- **edge_drift** — Edges where either the source or target node has drifted

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

### `codegiraffe_dashboard`

Launch the interactive Sigma.js v3 web dashboard for a project. Spawns a background HTTP server and opens the user's default browser. If a server is already running on the requested port, the existing URL is returned and the browser is opened to it without spawning a second process.

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_path` | `str` | — | yes | Absolute path to the project root whose graph should be displayed |
| `port` | `int` | `8251` | no | Local port to bind the dashboard HTTP server on |

The project must be initialized first — run `codegiraffe_init` if no graph exists yet.

**Example:**
```
codegiraffe_dashboard(project_path="/home/user/my-project")
--> "Dashboard launched at http://localhost:8251/dashboard?project_path=...
     Browser will open automatically. The server will stop when this terminal session ends."

codegiraffe_dashboard(project_path="/home/user/my-project", port=9000)
--> "Dashboard already running at http://localhost:9000/dashboard?project_path=...
     Opened browser to existing dashboard."
```

---

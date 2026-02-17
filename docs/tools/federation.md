[← Back to Documentation](../README.md) | [Tool Index](README.md)

# Cross-Repo Federation

Link architecture graphs from multiple repositories into a unified federated view.

## How It Works

1. **Register** repos using `codegiraffe_federate` with a list of project paths
2. Nodes are namespaced with `repo:{name}::` prefixes to avoid collisions
3. Cross-repo edges use types like `cross_repo_calls`, `cross_repo_depends_on`, `cross_repo_publishes`, `cross_repo_consumes`
4. Query across repos using `codegiraffe_cross_query` with namespaced IDs

## Example

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

---

### `codegiraffe_federate`

Register multiple repositories into a federated view, combining their architecture graphs.

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_paths` | `list[str]` | — | yes | List of project root directories to federate |

**Example:**
```
codegiraffe_federate(project_paths=["/home/user/api", "/home/user/frontend"])
--> {"repos": ["api", "frontend"], "total_nodes": 285, "total_edges": 412}
```

---

### `codegiraffe_cross_query`

Query across federated graphs using repo-namespaced node IDs.

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `node_id` | `str` | — | yes | Namespaced node ID (e.g., `"repo:api::endpoint:/users"`) |
| `depth` | `int` | `2` | no | Maximum hops from the queried node |

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

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_path` | `str` | — | yes | Root directory of the project |
| `query` | `str` | — | yes | Read-only Cypher query |

**Example:**
```
codegiraffe_cypher(project_path="/home/user/my-project", query="MATCH (n:endpoint) RETURN n.label, n.id LIMIT 10")
--> [{"n.label": "GET /api/users", "n.id": "endpoint:/api/users"}, ...]
```

---

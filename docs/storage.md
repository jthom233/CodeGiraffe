[← Back to Documentation](README.md)

# Storage Backends

Code Giraffe supports three storage backends, selectable via the `backend` parameter on `codegiraffe_init`. All backends implement the `StorageBackend` protocol, so switching between them is transparent to the rest of the system. Manual annotations and graph structure are preserved identically regardless of backend.

---

## JSON (default)

Graphs are stored as a single JSON file at `{project_path}/.codegiraffe/graph.json`. Best for small to medium projects. Human-readable, easy to version control, and requires no additional dependencies.

```
codegiraffe_init(project_path="/home/user/my-project", backend="json")
```

This is the default when no `backend` is specified.

---

## SQLite

Graphs are stored in a SQLite database at `{project_path}/.codegiraffe/graph.db`. Better for larger projects where JSON serialization becomes a bottleneck. Supports concurrent reads and uses less memory for large graphs.

```
codegiraffe_init(project_path="/home/user/large-project", backend="sqlite")
```

No additional dependencies required — SQLite is part of the Python standard library.

---

## Neo4j (optional)

For enterprise-scale graphs, Code Giraffe supports Neo4j as a storage backend. Requires a running Neo4j instance and the `neo4j` Python driver.

**Install the Neo4j extra:**

```bash
uv pip install -e ".[neo4j]"
```

**Configure via environment variables:**

| Variable | Default | Description |
|---|---|---|
| `NEO4J_URI` | `neo4j://localhost:7687` | Connection URI |
| `NEO4J_USER` | `neo4j` | Database user |
| `NEO4J_PASSWORD` | (none) | Database password (required for authenticated access) |

**Initialize with Neo4j backend:**

```
codegiraffe_init(project_path="/home/user/enterprise-project", backend="neo4j")
```

When using Neo4j, you can also run read-only Cypher queries directly against the graph using `codegiraffe_cypher`:

```
codegiraffe_cypher(
  project_path="/home/user/my-project",
  query="MATCH (n:endpoint) RETURN n.label, n.id LIMIT 10"
)
```

---

## StorageBackend Protocol

All backends implement a common `StorageBackend` protocol with three operations: `load`, `save`, and `exists`. This means the scanner, query engine, and all MCP tools are backend-agnostic — they interact only with the protocol, not with specific file formats or databases.

To implement a custom storage backend, implement the `StorageBackend` protocol and register it in the server initialization.

---

## Choosing a Backend

| Project Size | Recommended Backend |
|---|---|
| Small to medium (< 500 nodes) | JSON (default) |
| Large (500–10,000 nodes) | SQLite |
| Enterprise (10,000+ nodes) | Neo4j |

---

## See Also

- [Federation](tools/federation.md) — Cross-repo federation for querying across multiple backends

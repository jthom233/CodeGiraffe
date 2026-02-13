# Implementation Plan: Code Giraffe v0.3.0

**Branch**: `003-v030-features` | **Date**: 2026-02-13 | **Spec**: `specs/003-v030-features/spec.md`

## Summary

v0.3.0 adds four major features: Neo4j storage backend, tree-sitter AST scanning,
cross-repo graph federation, and schema evolution/versioning. All features are implemented
as optional capabilities with graceful degradation. 8 new MCP tools bring the total to 19.

## Constitution Check

| Principle | Status | Notes |
|-----------|--------|-------|
| I. MCP-Native | PASS | 8 new tools exposed via @mcp.tool() |
| II. Graph-First | PASS | All data remains graph-modeled; federation composes graphs |
| III. Beyond-AST | PASS | tree-sitter enhances detection; federation captures cross-repo relationships |
| IV. Context Efficiency | PASS | Cypher queries for targeted Neo4j access; federated queries scope by repo |
| V. Incremental & Non-Destructive | PASS | Versioning tracks all changes; federation is additive |
| VI. Test-First | PASS | Tests written before implementation for each feature |
| VII. Simplicity | JUSTIFIED | Neo4j: optional dep behind StorageBackend protocol. tree-sitter: optional behind PatternRecognizer protocol. Federation: NetworkX compose, file-based. Versioning: diff-based, file-based. |

## Project Structure

### New Files

```text
src/codegiraffe/
├── neo4j_storage.py          # Neo4jStorage implementing StorageBackend
├── ast_scanner.py            # AST-based recognizers using tree-sitter
├── federation.py             # Cross-repo graph federation
└── versioning.py             # Schema evolution & graph versioning

tests/
├── test_neo4j_storage.py     # Neo4j storage tests (mocked driver)
├── test_ast_scanner.py       # AST scanner tests + regex comparison
├── test_federation.py        # Federation tests
└── test_versioning.py        # Versioning tests
```

### Modified Files

```text
src/codegiraffe/
├── server.py                 # +8 new MCP tool definitions
├── registry.py               # +set_mode() method for AST/regex switching
└── __init__.py               # Version bump to 0.3.0

pyproject.toml                # +optional deps: neo4j, tree-sitter-languages
```

## Feature 1: Neo4j Storage Backend

### Design

`Neo4jStorage` implements the 3-method `StorageBackend` protocol:
- `load()`: Cypher `MATCH (n) OPTIONAL MATCH (n)-[r]->(m) RETURN n, r, m` → GraphData
- `save()`: Transaction: `MATCH (n) DETACH DELETE n` then `CREATE` all nodes/edges
- `exists()`: `MATCH (n) RETURN count(n) > 0`

Connection config via env vars: `NEO4J_URI` (default: `neo4j://localhost:7687`),
`NEO4J_USER` (default: `neo4j`), `NEO4J_PASSWORD`.

New tool `codegiraffe_cypher`: accepts read-only Cypher query string, returns JSON results.

### Dependencies

- `neo4j>=6.0` as optional dependency in `[neo4j]` extra
- All tests mock `neo4j.GraphDatabase.driver` — no running Neo4j required

## Feature 2: AST-Aware Scanning

### Design

One `ASTRecognizer` per language, each implementing `PatternRecognizer.recognize()`.
Internally uses tree-sitter S-expression queries to find patterns.

`RecognizerRegistry.set_mode(mode: str)` switches between "regex" (default) and "ast".
When set to "ast", `get_default_registry()` returns AST recognizers instead of regex.
Falls back to regex if `tree-sitter-languages` not installed.

Language queries target the same patterns as regex but with structural awareness:
- Python: `(decorated_definition)` for Flask/FastAPI routes, `(class_definition)` for SQLAlchemy
- Go: `(function_declaration)` for handlers, `(type_declaration (struct_type))` for models
- TypeScript: `(call_expression)` for Express routes, `(class_declaration)` for components
- Rust: `(attribute_item)` for Actix/Rocket, `(struct_item)` for Diesel
- Java: `(annotation)` for Spring mappings, `(class_declaration)` for JPA entities

### Dependencies

- `tree-sitter-languages` as optional dependency in `[ast]` extra

## Feature 3: Cross-Repo Federation

### Design

`GraphFederation` manages a registry of repo paths. When federated, each repo's graph
is loaded, nodes are namespaced as `repo:{name}::{original_id}`, and all graphs are
composed via `nx.compose_all()`.

Federation metadata (list of repo paths) persisted at `~/.codegiraffe/federation.json`.

New edge types for cross-repo relationships: `cross_repo_calls`, `cross_repo_depends_on`,
`cross_repo_publishes`, `cross_repo_consumes`.

Three new tools:
- `codegiraffe_federate(repo_paths: list[str])` — build federated view
- `codegiraffe_cross_query(node_id, depth)` — query in federated graph
- `codegiraffe_cross_edges()` — list cross-boundary edges

### Dependencies

None beyond existing (NetworkX, JSON storage).

## Feature 4: Schema Evolution & Versioning

### Design

`GraphDiff` dataclass stores: nodes_added, nodes_removed, edges_added, edges_removed,
attrs_changed (dict of node_id → {field: {old, new}}).

`GraphVersion` stores: version_id (int), timestamp (ISO), message (str), diff (GraphDiff).

`VersionStore` manages a list of versions persisted at `.codegiraffe/versions.json`.
Each sync/rescan auto-creates a version. Manual snapshots via `codegiraffe_snapshot`.

Diff computation compares two GraphData instances by node/edge ID sets and attribute values.

Four new tools:
- `codegiraffe_history(project_path)` — list versions
- `codegiraffe_diff(project_path, version_a, version_b)` — compute diff
- `codegiraffe_snapshot(project_path, message)` — manual snapshot
- `codegiraffe_restore(project_path, version_id)` — restore to version

### Dependencies

None beyond existing.

## Implementation Order

1. **Versioning** (no external deps, foundational for tracking changes)
2. **Federation** (no external deps, builds on graph.py)
3. **Neo4j storage** (optional dep, isolated behind protocol)
4. **AST scanning** (optional dep, isolated behind protocol)

Tasks 1-2 can be parallelized. Tasks 3-4 can be parallelized after 1-2.

## New MCP Tools Summary (8 total)

| Tool | Feature | Inputs |
|------|---------|--------|
| `codegiraffe_cypher` | Neo4j | project_path, query |
| `codegiraffe_federate` | Federation | repo_paths |
| `codegiraffe_cross_query` | Federation | node_id, depth |
| `codegiraffe_cross_edges` | Federation | (none beyond federation) |
| `codegiraffe_history` | Versioning | project_path |
| `codegiraffe_diff` | Versioning | project_path, version_a, version_b |
| `codegiraffe_snapshot` | Versioning | project_path, message |
| `codegiraffe_restore` | Versioning | project_path, version_id |

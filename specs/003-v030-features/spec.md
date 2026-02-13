# Specification

## Requirements

Code Giraffe v0.3.0 — Advanced Features

Code Giraffe is an MCP (Model Context Protocol) server that exposes an architecture knowledge graph for AI-assisted development. v0.2.0 is complete with 11 MCP tools, 5 language recognizers, 241 tests. This spec covers v0.3.0 features.

## Feature 1: Neo4j Storage Backend (neo4j_storage.py)

Add Neo4j as a third storage backend alongside JSON and SQLite, implementing the existing StorageBackend protocol (load, save, exists methods).

Requirements:
- Neo4jStorage class implementing StorageBackend protocol
- Uses `neo4j` Python driver v6.1+ (optional dependency like sentence-transformers)
- Connection via URI + auth credentials, configurable via env vars (NEO4J_URI, NEO4J_AUTH)
- Cypher-based node/edge CRUD operations
- Schema: Node labels map to node types, relationship types map to edge types
- Each save replaces graph data in a transaction (consistent with JSON/SQLite behavior)
- Graceful degradation: if neo4j not installed, backend="neo4j" raises clear error
- `codegiraffe_init` updated: backend parameter accepts "neo4j" in addition to "json"/"sqlite"
- Connection pooling with configurable pool size
- New MCP tool: `codegiraffe_cypher` — run arbitrary read-only Cypher queries against the graph
- Tests: mock the neo4j driver (don't require running Neo4j instance)

## Feature 2: AST-Aware Scanning via tree-sitter (ast_scanner.py)

Add tree-sitter-based scanning as an alternative to regex scanning, providing more accurate pattern detection.

Requirements:
- Uses `tree-sitter-languages` package (optional dependency)
- ASTRecognizer class implementing PatternRecognizer protocol
- Language support: Python, Go, TypeScript, Rust, Java (same 5 as regex)
- tree-sitter query patterns (S-expressions) for each language to detect:
  - Function/method definitions with decorators
  - Class/struct/interface definitions
  - Import statements and dependencies
  - String literals matching env var patterns
  - HTTP handler patterns per framework
- RecognizerRegistry updated: `set_mode("ast")` switches all recognizers to AST-based
- Fallback: if tree-sitter-languages not installed, falls back to regex recognizers
- `codegiraffe_init` updated: `scanner_mode` parameter ("regex" default, "ast" option)
- AST scanner MUST detect at least everything regex scanner detects (superset)
- Tests: compare AST vs regex output on same test fixtures, verify AST finds more

## Feature 3: Cross-Repo Graph Federation (federation.py)

Enable linking architecture graphs across multiple repositories into a unified federated view.

Requirements:
- GraphFederation class managing multiple repo graphs
- Namespace isolation: nodes prefixed with `repo:{repo_name}::` to avoid collisions
- Uses NetworkX compose() for merging
- Cross-repo edge types: `cross_repo_calls`, `cross_repo_depends_on`, `cross_repo_publishes`, `cross_repo_consumes`
- New MCP tools:
  - `codegiraffe_federate` — register repos into a federation, returns unified graph summary
  - `codegiraffe_cross_query` — query across federated graphs (node_id with repo prefix)
  - `codegiraffe_cross_edges` — list all edges that cross repo boundaries
- Federation metadata stored at `~/.codegiraffe/federation.json` (global, not per-repo)
- Manual cross-repo edges via `codegiraffe_add_relation` with repo-prefixed node IDs
- Support adding cross-repo edges manually: `source="repo:api::endpoint:/users"`, `target="repo:frontend::component:UserList"`

## Feature 4: Schema Evolution and Versioning (versioning.py)

Track how the architecture graph changes over time with git-like versioning.

Requirements:
- GraphVersion dataclass: version_id (auto-increment), timestamp, message, diff (GraphDiff)
- GraphDiff dataclass: nodes_added, nodes_removed, edges_added, edges_removed, attrs_changed
- VersionStore class with file-based persistence at `.codegiraffe/versions.json`
- Auto-versioning: every `codegiraffe_sync` and `codegiraffe_init --rescan` creates a version
- New MCP tools:
  - `codegiraffe_history` — list version history with timestamps, messages, and diff summaries
  - `codegiraffe_diff` — compare two versions (or current vs specific version), returns GraphDiff
  - `codegiraffe_snapshot` — manually create a named snapshot of current graph state
  - `codegiraffe_restore` — restore graph to a specific version (with confirmation)
- Diff computation: nodes added/removed, edges added/removed, attribute changes on existing nodes
- Storage: diffs are stored (not full snapshots) to keep storage efficient
- Maximum 100 versions retained by default (configurable), oldest pruned automatically

## Non-Functional Requirements
- All new features are optional dependencies (neo4j, tree-sitter-languages)
- Core functionality (JSON storage, regex scanning) MUST NOT be affected
- All new MCP tools MUST have contract tests
- Test count target: 300+ tests
- Constitution compliance: all 7 principles must be satisfied
- Backward compatible: existing .codegiraffe/ directories work without migration

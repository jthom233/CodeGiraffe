# Data Model: Code Giraffe v0.2.0

**Date**: 2026-02-13 | **Spec**: `specs/002-v020-spec-update/spec.md`

## Core Entities

### Node

An architectural entity in the knowledge graph.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `str` | Yes | Unique identifier (format: `{type}:{name}`, e.g., `endpoint:/api/users`) |
| `type` | `str` | Yes | Node type (built-in or custom) |
| `label` | `str` | Yes | Human-readable display label |
| `metadata` | `dict[str, Any]` | No | Arbitrary key-value pairs (framework, method, ORM, etc.) |
| `file_path` | `str \| None` | No | Source file where the entity was discovered |
| `manual` | `bool` | No | `True` if added via `codegiraffe_add_relation`, survives rescans |

**Built-in Node Types**: `service`, `endpoint`, `database_table`, `queue`, `env_var`, `config`, `worker`, `frontend_component`, `event`, `external_api`

### Edge

A directed relationship between two nodes.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `source` | `str` | Yes | Source node ID |
| `target` | `str` | Yes | Target node ID |
| `type` | `str` | Yes | Relationship type (built-in or custom) |
| `metadata` | `dict[str, Any]` | No | Arbitrary key-value pairs |
| `manual` | `bool` | No | `True` if manually annotated, survives rescans |

**Built-in Edge Types**: `calls`, `reads`, `writes`, `publishes`, `consumes`, `depends_on`, `configures`, `owns`, `triggers`

### GraphData

The complete graph with project metadata.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `nodes` | `list[Node]` | Yes | All nodes in the graph |
| `edges` | `list[Edge]` | Yes | All edges in the graph |
| `project_path` | `str` | Yes | Absolute path to the scanned project |
| `last_scan` | `str` | Yes | ISO timestamp of last scan |
| `schema_version` | `str` | Yes | Data schema version (currently "1") |

### ScanResult

Output from a single file scan by a PatternRecognizer.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `nodes` | `list[Node]` | Yes | Nodes discovered in the file |
| `edges` | `list[Edge]` | Yes | Edges discovered in the file |

**Method**: `merge(other: ScanResult) -> ScanResult` — Combine results from multiple recognizers.

### AgentClaim

A coordination claim for multi-agent work.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `agent_id` | `str` | Yes | — | Unique agent identifier |
| `node_ids` | `list[str]` | Yes | — | Graph nodes being worked on |
| `task` | `str` | Yes | — | Description of the agent's task |
| `status` | `str` | Yes | `"active"` | One of: `active`, `done`, `blocked` |
| `claimed_at` | `float` | No | `time.time()` | Unix timestamp of claim creation |
| `ttl` | `int` | No | `1800` | Seconds until claim expires |
| `metadata` | `dict[str, Any]` | No | `{}` | Arbitrary extra data |

**Property**: `is_expired -> bool` — Check if `time.time() > claimed_at + ttl`

### EmbeddingCache

File-based cache for embedding vectors.

| Field | Type | Description |
|-------|------|-------------|
| `project_path` | `str` | Project directory (cache stored at `.codegiraffe/embeddings.json`) |
| `_cache` | `dict[str, list[float]]` | SHA256-keyed embedding vectors |

## Protocols / Interfaces

### StorageBackend (Protocol)

| Method | Signature | Description |
|--------|-----------|-------------|
| `load` | `(project_path: str) -> GraphData \| None` | Load graph from storage |
| `save` | `(project_path: str, data: GraphData) -> None` | Save graph to storage |
| `exists` | `(project_path: str) -> bool` | Check if stored graph exists |

**Implementations**: `JSONStorage`, `SQLiteStorage`

### PatternRecognizer (Protocol)

| Method | Signature | Description |
|--------|-----------|-------------|
| `recognize` | `(file_path: Path, content: str) -> ScanResult` | Scan file content for architectural patterns |

**Implementations**: `PythonRecognizer`, `TypeScriptRecognizer`, `GoRecognizer`, `RustRecognizer`, `JavaRecognizer`

### RecognizerRegistry

| Method | Signature | Description |
|--------|-----------|-------------|
| `register` | `(recognizer: PatternRecognizer, extensions: list[str] \| None) -> None` | Register recognizer for file extensions |
| `get_recognizers` | `(file_path: Path) -> list[PatternRecognizer]` | Get applicable recognizers for a file |
| `registered_extensions` | `-> set[str]` (property) | All registered file extensions |

## State Transitions

### AgentClaim Status

```
active → done      (agent completed work)
active → blocked   (agent hit a blocker)
blocked → active   (blocker resolved)
active → [expired] (TTL exceeded, auto-removed)
```

### Graph Lifecycle

```
[empty] → codegiraffe_init → [populated]
[populated] → codegiraffe_sync → [updated, manual preserved]
[populated] → codegiraffe_init(rescan=true) → [rebuilt, manual preserved]
[any] → codegiraffe_add_relation → [enriched with manual edge]
```

## Storage Layout

```
{project_path}/.codegiraffe/
├── graph.json         # JSON storage (default)
├── graph.db           # SQLite storage (when backend="sqlite")
├── embeddings.json    # Cached embedding vectors
└── agents.json        # Active agent claims
```

## SQLite Schema

```sql
CREATE TABLE graph_meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE nodes (
    id TEXT PRIMARY KEY, type TEXT, label TEXT,
    file_path TEXT, metadata TEXT, manual INTEGER DEFAULT 0
);
CREATE TABLE edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT, target TEXT, type TEXT,
    metadata TEXT, manual INTEGER DEFAULT 0,
    UNIQUE(source, target, type)
);
CREATE INDEX idx_nodes_type ON nodes(type);
CREATE INDEX idx_nodes_file ON nodes(file_path);
CREATE INDEX idx_edges_source ON edges(source);
CREATE INDEX idx_edges_target ON edges(target);
CREATE INDEX idx_edges_type ON edges(type);
```

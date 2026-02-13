# Research: Code Giraffe v0.2.0

**Date**: 2026-02-13 | **Status**: Complete (all features implemented)

## Decision Log

### 1. Multi-Language Scanner Architecture

**Decision**: Pluggable RecognizerRegistry with file-extension mapping
**Rationale**: Allows adding new languages without modifying core scanner code. Each recognizer is a self-contained class implementing PatternRecognizer protocol.
**Alternatives Considered**:
- Tree-sitter AST parsing: More accurate but adds heavy native dependencies, defeats Simplicity principle
- Language Server Protocol: Too heavyweight, requires running separate processes per language
- Single monolithic scanner with language flags: Violates open/closed principle, hard to extend

### 2. SQLite Storage Schema

**Decision**: Flat tables (nodes, edges, graph_meta) with WAL mode and indexed columns
**Rationale**: Simple schema that maps 1:1 to the JSON structure. WAL enables concurrent reads during scan operations. Indexes on type, file_path, source, target, edge type cover all query patterns.
**Alternatives Considered**:
- SQLite with FTS5 for full-text search on labels: Premature — keyword scoring handles this for now
- Graph-specific schema (adjacency list table): Unnecessary complexity, NetworkX handles graph ops in memory

### 3. Embedding Model Selection

**Decision**: all-MiniLM-L6-v2 via sentence-transformers
**Rationale**: Small (80MB), fast inference, good semantic similarity quality. Well-tested in production. Pure Python, works on CPU.
**Alternatives Considered**:
- OpenAI embeddings API: Requires network, API key, cost — violates offline/simplicity principle
- TF-IDF: Too simple, misses semantic relationships
- Larger models (all-mpnet-base-v2): Better quality but 3x larger, slower for marginal improvement

### 4. Multi-Agent Coordination Mechanism

**Decision**: File-based JSON store with TTL expiration
**Rationale**: No external dependencies (Redis, etcd). TTL prevents stale locks from blocking work. Optimistic concurrency is acceptable since agent conflicts are rare in practice.
**Alternatives Considered**:
- Redis-based locking: External dependency, overkill for single-machine use case
- Database-backed (SQLite): Could work but adds coupling to storage choice
- In-memory only: Claims lost on server restart, which defeats the purpose

### 5. Drift Detection Enhancement

**Decision**: String similarity (Levenshtein-like) for rename detection + edge validation
**Rationale**: Renames are the most common source of drift. Simple string similarity catches >80% of rename cases. Edge drift (referencing deleted nodes) catches cascading issues.
**Alternatives Considered**:
- Git rename detection: Requires git history access, adds complexity
- AST-based rename tracking: Contradicts regex-only scanning principle
- No rename detection: Misses the most actionable drift information

### 6. Export Format Selection

**Decision**: Mermaid + D3.js JSON
**Rationale**: Mermaid renders natively in GitHub, docs, and many tools. D3.js JSON is the standard for web-based graph visualization. Both are text-based and version-controllable.
**Alternatives Considered**:
- DOT/Graphviz: Less widely supported in web contexts
- Cytoscape.js: Good but less mainstream than D3
- SVG export: Lossy — can't re-import or interact with the graph

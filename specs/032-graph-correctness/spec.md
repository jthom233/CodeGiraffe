# Feature Specification: Graph Correctness

**Feature Branch**: `032-graph-correctness`
**Created**: 2026-02-25
**Status**: Draft
**Input**: User description: "Phase 1: Graph Correctness — Migrate nx.DiGraph to nx.MultiDiGraph, enforce read-only Cypher execution, and add threading.RLock around _graph access."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Multi-Edge Relationships Are Preserved (Priority: P1)

When an AI agent scans a codebase, the architecture graph must accurately represent all relationships between components. Today, if module A both contains and imports module B, only one of those relationships survives. The graph silently drops edges, producing an incomplete and misleading architecture picture. After this change, all relationship types between any pair of components are preserved and queryable.

**Why this priority**: This is a data correctness issue affecting every scan. Every graph built today is silently incomplete. All downstream analysis (blast radius, drift detection, context retrieval, risk assessment) operates on corrupted data. Fixing this is the foundation for all other improvements.

**Independent Test**: Can be fully tested by scanning a project where files have multiple relationship types (e.g., a module that both contains entities and imports from another module), then verifying all edge types are present in the resulting graph.

**Acceptance Scenarios**:

1. **Given** a Python project where `models.py` contains a class and also imports from `base.py`, **When** the project is scanned, **Then** both the `contains` edge and the `imports` edge between the two module nodes exist in the graph simultaneously.
2. **Given** a graph with a `contains` edge from A to B, **When** a `calls` edge from A to B is added, **Then** both edges coexist — the `contains` edge is not overwritten.
3. **Given** a graph with multiple edge types between the same node pair, **When** the graph is saved and reloaded from any storage backend, **Then** all edge types are preserved on round-trip.
4. **Given** a graph with multiple edge types between nodes A and B, **When** `blast_radius` or `context_for` queries traverse the graph, **Then** all edge types are considered in the analysis, not just the last one added.

---

### User Story 2 - Read-Only Graph Database Queries (Priority: P2)

When an AI agent executes a raw query against the optional Neo4j graph database backend, the system must prevent destructive operations. Today, the Cypher query tool accepts and executes arbitrary queries including writes and deletes. After this change, only read operations are permitted through the query tool, protecting data integrity.

**Why this priority**: This is a security vulnerability. Any agent with MCP tool access can destroy the entire Neo4j database with a single query. While Neo4j is optional, users who adopt it for production use are exposed to catastrophic data loss.

**Independent Test**: Can be tested by attempting write/delete Cypher queries through the tool and verifying they are rejected with a clear error message, while read queries succeed normally.

**Acceptance Scenarios**:

1. **Given** a Neo4j backend with graph data, **When** an agent submits a read-only Cypher query (e.g., `MATCH (n) RETURN n LIMIT 10`), **Then** the query executes successfully and returns results.
2. **Given** a Neo4j backend, **When** an agent submits a destructive query (e.g., `MATCH (n) DETACH DELETE n`), **Then** the query is rejected before execution with an error message explaining that only read operations are permitted.
3. **Given** a Neo4j backend, **When** an agent submits a query containing `CREATE`, `MERGE`, `DELETE`, `SET`, `REMOVE`, or `DROP` keywords, **Then** the query is rejected regardless of casing or whitespace.

---

### User Story 3 - Safe Concurrent Access (Priority: P3)

When multiple consumers access the architecture graph simultaneously (e.g., an MCP tool call and the web dashboard), the system must not corrupt data or crash. Today, the shared in-memory graph has no concurrency protection. After this change, concurrent reads and writes are serialized to prevent data races.

**Why this priority**: The dashboard runs in a background thread and shares the same in-memory graph as MCP tool calls. While single-agent usage may not trigger races frequently, multi-agent workflows and dashboard usage create real concurrency scenarios that can silently corrupt the graph.

**Independent Test**: Can be tested by issuing concurrent graph reads and writes from multiple threads and verifying no data corruption, crashes, or inconsistent states occur.

**Acceptance Scenarios**:

1. **Given** a loaded architecture graph, **When** one thread is writing (e.g., adding annotations) while another is reading (e.g., running a query), **Then** neither operation crashes or produces corrupted results.
2. **Given** a loaded graph with the dashboard running, **When** an MCP tool triggers a full rescan that replaces the graph, **Then** a concurrent dashboard request either sees the old graph or the new graph — never a partially-replaced state.
3. **Given** two concurrent MCP tool calls that both modify the graph, **When** both complete, **Then** the graph is in a consistent state reflecting both modifications without lost updates.

---

### Edge Cases

- What happens when the same edge type is added twice between the same node pair? (Should be idempotent — update, not duplicate.)
- How does the system handle legacy graph files saved with the old single-edge format? (Must load correctly — old format is a subset of the new format.)
- What happens when a Cypher query uses write keywords inside string literals or comments? (Should still be rejected — conservative enforcement is preferred over perfect parsing.)
- What happens when a storage backend save fails mid-write while another thread is reading? (The read should see a consistent pre-write or post-write state, never partial.)
- How does the graph handle edges where confidence differs between two edges of the same type between the same pair? (Each edge is independently stored with its own confidence.)

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The in-memory graph MUST support multiple edges between the same source and target nodes, distinguished by edge type.
- **FR-002**: Adding an edge with the same source, target, and type as an existing edge MUST update the existing edge rather than creating a duplicate.
- **FR-003**: Adding an edge with the same source and target but a different type MUST create a new edge alongside existing edges.
- **FR-004**: All graph traversal and query operations MUST consider all edge types between a node pair, not just one.
- **FR-005**: All storage backends (JSON, SQLite, Neo4j) MUST preserve all edge types on save/load round-trips.
- **FR-006**: The raw Cypher query tool MUST reject queries containing write or destructive operations before they reach the database.
- **FR-007**: The Cypher query rejection MUST cover: `CREATE`, `MERGE`, `DELETE`, `SET`, `REMOVE`, `DROP`, `DETACH`, and `CALL` (for write procedures).
- **FR-008**: Read/write access to the shared in-memory graph MUST be serialized to prevent data races from concurrent access.
- **FR-009**: The concurrency mechanism MUST allow multiple concurrent readers OR one exclusive writer (not block all reads during reads).
- **FR-010**: Graph files saved in the previous single-edge format MUST load correctly into the new multi-edge representation.

### Key Entities

- **Edge**: A directed relationship between two nodes, uniquely identified by the triple (source, target, type). Each edge carries its own metadata, confidence score, and manual flag.
- **ArchGraph**: The in-memory graph representation wrapping the graph data structure. Owns the concurrency lock and all mutation/query methods.
- **StorageBackend**: The persistence layer that must faithfully round-trip all edges including multi-edges between the same node pair.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All existing tests pass after migration with no regressions.
- **SC-002**: A scan of a real codebase with known multi-edge relationships produces a graph where 100% of expected edge types are present (zero silent drops).
- **SC-003**: Graphs saved and reloaded through each storage backend retain all edges — edge count before save equals edge count after load.
- **SC-004**: 100% of destructive Cypher queries are rejected; 100% of read-only queries execute successfully.
- **SC-005**: Concurrent read/write stress tests complete without crashes, data corruption, or assertion failures.
- **SC-006**: No performance regression greater than 10% on graph construction, query, or save/load operations compared to the current implementation.

## Assumptions

- The multi-edge migration is internal — the MCP tool interface does not change. Agents should not need to modify their usage patterns.
- Cypher write-rejection uses keyword-based filtering, not full query parsing. This is intentionally conservative — a legitimate read query that happens to contain a write keyword in a string literal will be rejected. This is acceptable for a safety-first approach.
- The concurrency lock is at the graph level, not per-node. Fine-grained locking is unnecessary for the current single-project-at-a-time architecture.
- Backward compatibility with existing saved graph files is required. Old files with single edges per pair will load correctly since they are a valid subset of the multi-edge format.

## Scope Boundaries

**In scope**:
- Migrating the in-memory graph to support multiple edges per node pair
- Updating all edge access patterns across the codebase
- Adding Cypher write-rejection
- Adding concurrency protection for the shared graph
- Updating storage backends to handle multi-edges
- Backward-compatible loading of old graph files

**Out of scope**:
- Performance optimizations (Phase 3)
- New MCP tools or API changes (Phase 4)
- Scanner pipeline fixes (Phase 2)
- Dashboard security hardening (Phase 5)

# Feature Specification: Code Giraffe Core MCP Server

**Feature Branch**: `001-core-mcp-server`
**Created**: 2026-02-12
**Status**: Draft

## User Scenarios & Testing

### User Story 1 - Initialize Architecture Graph (Priority: P1)

An AI agent working on a new codebase calls `codegiraffe_init` to scan the
project and bootstrap an architecture knowledge graph. The graph captures
services, endpoints, data stores, queues, env vars, and the relationships
between them. The agent receives a summary of what was discovered.

**Why this priority**: Without initialization, no other tool works. This is the
foundation of the entire system.

**Independent Test**: Call `codegiraffe_init` on a sample Python project with
Flask endpoints, SQLAlchemy models, and Celery tasks. Verify the graph JSON
contains nodes for each and edges for their relationships.

**Acceptance Scenarios**:

1. **Given** a Python project directory, **When** `codegiraffe_init` is called,
   **Then** a `.codegiraffe/graph.json` file is created containing typed nodes
   and edges discovered from the codebase.
2. **Given** a project with no recognizable patterns, **When** `codegiraffe_init`
   is called, **Then** an empty graph is created with project metadata and the
   agent is informed that manual annotation may be needed.
3. **Given** an existing `.codegiraffe/graph.json`, **When** `codegiraffe_init`
   is called with `rescan=true`, **Then** the graph is rebuilt from scratch
   while preserving any manually-added annotations.

---

### User Story 2 - Query the Graph (Priority: P1)

An AI agent needs to understand what a specific endpoint depends on before
modifying it. The agent calls `codegiraffe_query` with a node identifier and
receives the relevant subgraph — upstream dependencies, downstream consumers,
data stores accessed, env vars required — all scoped to minimize token usage.

**Why this priority**: Querying is the primary value proposition. Agents need to
retrieve targeted architectural context to work efficiently on complex codebases.

**Independent Test**: Given a graph with 50+ nodes, query a single endpoint and
verify the response contains only the relevant subgraph (not the full graph),
with configurable depth.

**Acceptance Scenarios**:

1. **Given** an initialized graph, **When** `codegiraffe_query` is called with
   `node_id="endpoint:/api/users"` and `depth=2`, **Then** the response contains
   only nodes within 2 hops of that endpoint and their connecting edges.
2. **Given** an initialized graph, **When** `codegiraffe_query` is called with
   `node_type="database_table"`, **Then** all database table nodes and their
   direct relationships are returned.
3. **Given** a node_id that doesn't exist, **When** `codegiraffe_query` is
   called, **Then** an error message is returned indicating the node was not
   found, with suggestions for similar nodes.

---

### User Story 3 - Add/Update Relations Manually (Priority: P1)

An AI agent (or human) discovers a runtime relationship that automated scanning
missed — e.g., a service calls another via a message queue using string-based
routing keys. The agent calls `codegiraffe_add_relation` to annotate this in
the graph so future queries include it.

**Why this priority**: Automated scanning will never catch everything. The ability
to manually annotate is what makes the graph capture "beyond-AST" knowledge.

**Independent Test**: Add a custom edge between two existing nodes, then query
one of them and verify the new edge appears in results.

**Acceptance Scenarios**:

1. **Given** an initialized graph with nodes A and B, **When**
   `codegiraffe_add_relation` is called with `source="A"`, `target="B"`,
   `relation_type="publishes_to"`, **Then** the edge is persisted and appears
   in subsequent queries.
2. **Given** an edge already exists between A and B, **When** the same relation
   is added again, **Then** the existing edge is updated (not duplicated) with
   any new metadata merged.
3. **Given** a source node that doesn't exist, **When** `codegiraffe_add_relation`
   is called, **Then** the node is auto-created with the provided id and a
   default type, and the edge is added.

---

### User Story 4 - Get Context for a Task (Priority: P2)

An orchestrator agent has a coding task (e.g., "add rate limiting to the /api/payments
endpoint"). Before delegating to a subagent, it calls `codegiraffe_context_for`
with a description of the task. The tool returns the minimal relevant subgraph
plus ranked hotspots — the files and components most likely to need attention.

**Why this priority**: This is the "killer feature" that directly reduces token
waste and improves agent accuracy, but it builds on US1-3 being solid first.

**Independent Test**: Given a graph and a task description, verify the returned
subgraph is smaller than the full graph and contains the most relevant nodes
ranked by impact score.

**Acceptance Scenarios**:

1. **Given** an initialized graph, **When** `codegiraffe_context_for` is called
   with `task="add rate limiting to /api/payments"`, **Then** the response
   includes the endpoint node, its upstream/downstream dependencies, related
   middleware, and env vars, ranked by relevance.
2. **Given** an initialized graph, **When** `codegiraffe_context_for` is called
   with a task that matches no nodes, **Then** a helpful message is returned
   suggesting the user add relevant nodes or providing the closest matches.

---

### User Story 5 - Detect Drift (Priority: P2)

After code changes, an agent calls `codegiraffe_detect_drift` to check if the
graph still matches reality. The tool compares the graph against the current
codebase and reports mismatches — endpoints that were renamed, tables that were
dropped, consumers still referencing old event names.

**Why this priority**: Drift detection keeps the graph useful over time. Without
it, the graph becomes stale and misleading.

**Independent Test**: Modify a sample project (rename an endpoint), run drift
detection, and verify it reports the mismatch.

**Acceptance Scenarios**:

1. **Given** a graph created from a codebase, **When** an endpoint is renamed
   in the code and `codegiraffe_detect_drift` is called, **Then** the response
   lists the missing endpoint and the new untracked endpoint as a potential
   rename.
2. **Given** a graph that matches the codebase perfectly, **When**
   `codegiraffe_detect_drift` is called, **Then** the response confirms no
   drift detected.

---

### User Story 6 - Hotspot Analysis (Priority: P3)

An agent calls `codegiraffe_hotspots` to identify the most coupled, risky, or
change-prone areas of the codebase. Nodes are ranked by coupling density (number
of edges), criticality annotations, and change frequency. This helps agents
prioritize where to focus attention.

**Why this priority**: Nice-to-have for v1 but not blocking core functionality.

**Independent Test**: Given a graph, verify hotspots returns nodes sorted by
coupling score with the most-connected nodes first.

**Acceptance Scenarios**:

1. **Given** an initialized graph, **When** `codegiraffe_hotspots` is called
   with `top_n=10`, **Then** the 10 most coupled nodes are returned, sorted by
   coupling score descending, with their edge counts and types.

---

### User Story 7 - Sync/Update Graph (Priority: P3)

After making code changes, an agent calls `codegiraffe_sync` to incrementally
update the graph. Only changed files are re-scanned. Manual annotations are
preserved.

**Why this priority**: Important for long-term usage but the init + manual
annotation flow covers the MVP.

**Independent Test**: Add a new endpoint to the codebase, call sync, and verify
only the new endpoint appears as an addition without losing existing annotations.

**Acceptance Scenarios**:

1. **Given** an initialized graph and a new file added to the project, **When**
   `codegiraffe_sync` is called, **Then** nodes from the new file are added to
   the graph and existing nodes/edges are unchanged.
2. **Given** a manually annotated edge, **When** `codegiraffe_sync` is called
   after code changes, **Then** the manual annotation is preserved.

---

### Edge Cases

- What happens when the graph JSON is corrupted or malformed?
- How does the system handle very large codebases (10k+ files)?
- What happens when two agents try to modify the graph simultaneously?
- How are circular dependencies represented and queried?
- What happens when a node type is not recognized by built-in scanners?

## Requirements

### Functional Requirements

- **FR-001**: System MUST expose all functionality as MCP tools using the
  FastMCP Python SDK with `@mcp.tool()` decorators.
- **FR-002**: System MUST store the architecture graph as JSON in a
  `.codegiraffe/graph.json` file within the target project.
- **FR-003**: System MUST support typed nodes with at minimum: `service`,
  `endpoint`, `database_table`, `queue`, `env_var`, `config`, `worker`,
  `frontend_component`, `event`, `external_api`.
- **FR-004**: System MUST support typed edges with at minimum: `calls`,
  `reads`, `writes`, `publishes`, `consumes`, `depends_on`, `configures`,
  `owns`, `triggers`.
- **FR-005**: System MUST support custom node and edge types beyond the
  built-in set.
- **FR-006**: System MUST use NetworkX for in-memory graph operations.
- **FR-007**: System MUST support scoped queries with configurable depth to
  limit response size.
- **FR-008**: System MUST preserve manually-added annotations during rescan
  and sync operations.
- **FR-009**: System MUST run via stdio transport for local MCP client
  integration.
- **FR-010**: System MUST provide a storage abstraction layer so the JSON
  backend can be swapped for SQLite or Neo4j in the future without changing
  tool interfaces.

### Key Entities

- **Node**: An architectural entity with `id`, `type`, `label`, `metadata`
  (arbitrary key-value), `file_path` (optional source location), `manual`
  (boolean, whether it was added by human/agent vs automated scan).
- **Edge**: A relationship with `source` (node id), `target` (node id), `type`,
  `metadata`, `manual` (boolean).
- **Graph**: A collection of nodes and edges with project-level metadata
  (project path, last scan timestamp, schema version).

## Success Criteria

### Measurable Outcomes

- **SC-001**: An agent can initialize a graph on a sample project and query it
  within a single conversation turn (< 5 seconds total).
- **SC-002**: `codegiraffe_query` returns < 20% of the total graph nodes for a
  single-node depth-2 query on a 100-node graph.
- **SC-003**: All 7 MCP tools pass contract tests verifying input/output schemas.
- **SC-004**: Graph survives a full rescan cycle without losing manual
  annotations.
- **SC-005**: The MCP server can be added to a Claude Code config and used
  immediately with `claude mcp add`.

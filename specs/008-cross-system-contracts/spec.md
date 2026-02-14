# Specification

## Requirements

## Code Giraffe v0.8.0 — Cross-System Contracts

### Problem Statement
CodeGiraffe detects architectural entities (endpoints, services, tables, env vars) and their relationships (imports, contains, implements) within a single codebase. However, it cannot express or analyze **cross-system contracts** — the agreements between components about how they communicate. An AI agent can see that service A has endpoint `/api/users` and service B makes HTTP calls, but there's no way to express "B calls A's `/api/users` endpoint" or to detect when a contract is violated (e.g., A removes the endpoint that B depends on).

This is the core differentiator vs LSP: CodeGiraffe should be the tool that answers "what are the agreements between components, and are they being honored?"

### Goal
Add contract-aware scanning, new schema types, a contract management MCP tool, and contract validation capabilities. Contracts represent explicit or inferred agreements between architectural nodes — API contracts (producer/consumer), data contracts (schema expectations), event contracts (publisher/subscriber), and configuration contracts (env var dependencies).

### Requirements

#### R1: New Schema Types
Add to schema.py:
- **Node types:** `contract` — represents a formal agreement between components
- **Edge types:** `produces`, `consumes_contract`, `validates`, `violates`
- These extend existing enums without changing existing values

#### R2: Contract Node Model
A contract node represents an agreement between a producer and one or more consumers:
- Node ID format: `contract:{name}` (e.g., `contract:api/users`, `contract:user.created.event`)
- Required metadata fields:
  - `contract_type`: "api" | "event" | "data" | "config"
  - `producer`: node_id of the producing component
  - `consumers`: list of node_ids of consuming components
  - `version`: optional version string
  - `status`: "active" | "deprecated" | "broken"
- Contract nodes are created by the scanner (inferred) or manually via MCP tool

#### R3: Contract Inference in Scanner Pipeline
Extend `_infer_edges` in scanner.py to detect implicit contracts:

**API Contracts:**
- When file A defines endpoint `/api/users` (endpoint node) AND file B makes HTTP call to a URL containing `/api/users` (external_api node) within the SAME project → infer contract
- Create contract node + `produces` edge from endpoint → contract + `consumes_contract` edge from caller service → contract
- Match by URL path suffix (strip host/scheme, match path segments)

**Event Contracts:**
- When file A publishes event "user.created" AND file B subscribes to "user.created" → infer contract
- Match by event name (exact match on event node labels)
- Create contract node + produces/consumes_contract edges

**Config Contracts:**
- When file A sets/writes env var "DB_URL" AND file B reads env var "DB_URL" → infer contract
- Already have env_var nodes; create contract linking writer to readers
- Only infer when BOTH writer and reader exist in the same project

**Data Contracts:**
- When file A defines database table "users" AND file B queries/references "users" → infer contract
- Match by table name (exact match on database_table node labels)

#### R4: MCP Tool — codegiraffe_contracts
New MCP tool in server.py:
- Signature: `codegiraffe_contracts(project_path: str, contract_type: str | None = None, status: str | None = None, node_id: str | None = None) -> str`
- Lists all contracts in the graph, optionally filtered by:
  - `contract_type`: filter by "api", "event", "data", "config"
  - `status`: filter by "active", "deprecated", "broken"
  - `node_id`: show only contracts involving this node (as producer or consumer)
- Returns markdown-formatted contract inventory with:
  - Contract name, type, status
  - Producer node (with file path)
  - Consumer nodes (with file paths)
  - Edge types connecting them
- If no contracts exist, return helpful message explaining how to add them

#### R5: MCP Tool — codegiraffe_validate_contracts
New MCP tool in server.py:
- Signature: `codegiraffe_validate_contracts(project_path: str) -> str`
- Validates all contracts in the graph:
  - Check that producer node still exists in the graph
  - Check that all consumer nodes still exist
  - Check for "orphaned" contracts (producer or all consumers missing)
  - Flag contracts where the endpoint/event/table has been removed but consumers remain
- Returns markdown validation report with:
  - Valid contracts (producer + all consumers present)
  - Broken contracts (producer or consumer missing) with details
  - Deprecated contracts (marked deprecated but still have active consumers)
  - Recommendations for fixing broken contracts

#### R6: MCP Tool — codegiraffe_add_contract
New MCP tool for explicit contract creation:
- Signature: `codegiraffe_add_contract(project_path: str, name: str, contract_type: str, producer: str, consumers: str, version: str = "", metadata: str = "{}") -> str`
- `consumers` is comma-separated list of node IDs
- Creates the contract node + produces/consumes_contract edges
- Contract is marked `manual=True` (survives rescans)
- Validates that producer and consumer node IDs exist (warn if not, but still create)
- Returns confirmation with contract details

#### R7: Enhanced codegiraffe_blast_radius for Contracts
Enhance the existing blast_radius tool:
- When computing blast radius for a node that is a contract producer, highlight all consumers
- When computing blast radius for a contract node, show both producer and all consumers
- Add contract-aware severity: breaking a contract producer is "critical" severity for all consumers
- No new parameters needed — just richer output when contracts are present

#### R8: Contract-Aware Dashboard
Enhance the web dashboard to visualize contracts:
- Contract nodes styled distinctly (e.g., hexagonal shape, purple/violet color)
- `produces` edges styled with solid thick line
- `consumes_contract` edges styled with dashed line
- `violates` edges styled with red color
- Contract tooltip shows: type, version, status, producer, consumer count
- No new routes needed — contracts are just nodes/edges rendered by existing graph

#### R9: Test Coverage
- Contract inference tests: test each contract type (API, event, config, data) with synthetic code snippets
- Contract MCP tool tests: codegiraffe_contracts, codegiraffe_validate_contracts, codegiraffe_add_contract
- Contract + blast radius integration tests
- Dashboard contract styling tests (if dashboard has render tests)
- Edge cases: no contracts, orphaned contracts, self-referencing contracts, duplicate contracts
- Backward compatibility: all 754 existing tests pass unchanged
- Target: 40+ new tests, 794+ total

#### R10: Backward Compatibility
- All changes MUST be backward compatible
- Existing 754 tests MUST continue to pass unchanged
- New schema types extend enums, don't modify existing values
- Contract inference is additive — it creates new nodes/edges, never removes existing ones
- Projects without detectable contracts work identically to v0.7.0
- No new required dependencies

### Non-Goals
- Cross-repository contract detection (already have federation for that)
- OpenAPI/Swagger spec file parsing (deferred — would require reading non-code files)
- Protocol Buffer / gRPC contract detection (deferred)
- GraphQL schema detection (deferred)
- Contract versioning/migration tracking (deferred)
- Contract test generation (deferred)

### Success Metrics
- Self-scan of CodeGiraffe: detects at least the internal contracts between scanner→recognizers
- Nexus (Go) project: detects API contracts (HTTP handlers + HTTP clients within same project)
- Contract validation correctly flags broken contracts when producer is removed
- Blast radius for contract producers shows critical severity for all consumers
- Zero regression in existing 754 tests
- 40+ new tests

## User Stories

As an AI coding agent, I want to see which components have contracts with each other so that I understand the communication agreements before modifying either side.

As an AI coding agent, I want to know when a code change would break a contract (e.g., removing an endpoint that another service calls) so that I can warn the developer.

As a developer, I want to validate that all my architecture's contracts are still honored after refactoring so that I catch breaking changes early.

As an AI coding agent, I want blast radius analysis to highlight contract violations with critical severity so that I prioritize testing contract boundaries.

As a developer, I want to manually declare contracts between components that the scanner can't detect so that the architecture graph captures all real-world agreements.

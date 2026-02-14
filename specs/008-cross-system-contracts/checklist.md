# Implementation & Validation Checklist

Based on: ./specs/008-cross-system-contracts/spec.md

## Requirements Validation

- [ ] **Node types:** `contract` — represents a formal agreement between components
- [ ] **Edge types:** `produces`, `consumes_contract`, `validates`, `violates`
- [ ] These extend existing enums without changing existing values
- [ ] Node ID format: `contract:{name}` (e.g., `contract:api/users`, `contract:user.created.event`)
- [ ] Required metadata fields:
- [ ] `contract_type`: "api" | "event" | "data" | "config"
- [ ] `producer`: node_id of the producing component
- [ ] `consumers`: list of node_ids of consuming components
- [ ] `version`: optional version string
- [ ] `status`: "active" | "deprecated" | "broken"
- [ ] Contract nodes are created by the scanner (inferred) or manually via MCP tool
- [ ] API Contracts:**
- [ ] Match by URL path suffix (strip host/scheme, match path segments)
- [ ] Event Contracts:**
- [ ] Match by event name (exact match on event node labels)
- [ ] Create contract node + produces/consumes_contract edges
- [ ] Config Contracts:**
- [ ] When file A sets/writes env var "DB_URL" AND file B reads env var "DB_URL" → infer contract
- [ ] Already have env_var nodes; create contract linking writer to readers
- [ ] Only infer when BOTH writer and reader exist in the same project
- [ ] Data Contracts:**
- [ ] When file A defines database table "users" AND file B queries/references "users" → infer contract
- [ ] Match by table name (exact match on database_table node labels)
- [ ] Lists all contracts in the graph, optionally filtered by:
- [ ] `contract_type`: filter by "api", "event", "data", "config"
- [ ] `status`: filter by "active", "deprecated", "broken"
- [ ] `node_id`: show only contracts involving this node (as producer or consumer)
- [ ] Returns markdown-formatted contract inventory with:
- [ ] Contract name, type, status
- [ ] Producer node (with file path)
- [ ] Consumer nodes (with file paths)
- [ ] Edge types connecting them
- [ ] If no contracts exist, return helpful message explaining how to add them
- [ ] Signature: `codegiraffe_validate_contracts(project_path: str) -> str`
- [ ] Validates all contracts in the graph:
- [ ] Check that producer node still exists in the graph
- [ ] Check that all consumer nodes still exist
- [ ] Check for "orphaned" contracts (producer or all consumers missing)
- [ ] Flag contracts where the endpoint/event/table has been removed but consumers remain
- [ ] Returns markdown validation report with:
- [ ] Valid contracts (producer + all consumers present)
- [ ] Broken contracts (producer or consumer missing) with details
- [ ] Deprecated contracts (marked deprecated but still have active consumers)
- [ ] Recommendations for fixing broken contracts
- [ ] `consumers` is comma-separated list of node IDs
- [ ] Creates the contract node + produces/consumes_contract edges
- [ ] Contract is marked `manual=True` (survives rescans)
- [ ] Validates that producer and consumer node IDs exist (warn if not, but still create)
- [ ] Returns confirmation with contract details
- [ ] When computing blast radius for a node that is a contract producer, highlight all consumers
- [ ] When computing blast radius for a contract node, show both producer and all consumers
- [ ] Add contract-aware severity: breaking a contract producer is "critical" severity for all consumers
- [ ] No new parameters needed — just richer output when contracts are present
- [ ] Contract nodes styled distinctly (e.g., hexagonal shape, purple/violet color)
- [ ] `produces` edges styled with solid thick line
- [ ] `consumes_contract` edges styled with dashed line
- [ ] `violates` edges styled with red color
- [ ] Contract tooltip shows: type, version, status, producer, consumer count
- [ ] No new routes needed — contracts are just nodes/edges rendered by existing graph
- [ ] Contract + blast radius integration tests
- [ ] Dashboard contract styling tests (if dashboard has render tests)
- [ ] Edge cases: no contracts, orphaned contracts, self-referencing contracts, duplicate contracts
- [ ] Backward compatibility: all 754 existing tests pass unchanged
- [ ] Target: 40+ new tests, 794+ total
- [ ] All changes MUST be backward compatible
- [ ] Existing 754 tests MUST continue to pass unchanged
- [ ] New schema types extend enums, don't modify existing values
- [ ] Contract inference is additive — it creates new nodes/edges, never removes existing ones
- [ ] Projects without detectable contracts work identically to v0.7.0
- [ ] No new required dependencies
- [ ] Cross-repository contract detection (already have federation for that)
- [ ] OpenAPI/Swagger spec file parsing (deferred — would require reading non-code files)
- [ ] Protocol Buffer / gRPC contract detection (deferred)
- [ ] GraphQL schema detection (deferred)
- [ ] Contract versioning/migration tracking (deferred)
- [ ] Contract test generation (deferred)
- [ ] Self-scan of CodeGiraffe: detects at least the internal contracts between scanner→recognizers
- [ ] Nexus (Go) project: detects API contracts (HTTP handlers + HTTP clients within same project)
- [ ] Contract validation correctly flags broken contracts when producer is removed
- [ ] Blast radius for contract producers shows critical severity for all consumers
- [ ] Zero regression in existing 754 tests
- [ ] 40+ new tests

## Implementation Checklist

- [ ] Code follows project style guide
- [ ] Functions have clear documentation
- [ ] Error handling is comprehensive
- [ ] Input validation is performed
- [ ] Logging is appropriate
- [ ] Performance is acceptable
- [ ] Security considerations addressed

## Testing Checklist

- [ ] Unit tests written for all functions
- [ ] Integration tests cover main workflows
- [ ] Edge cases are tested
- [ ] Error conditions are tested
- [ ] Performance tests (if applicable)
- [ ] All tests pass
- [ ] Test coverage >80%

## Quality Assurance

- [ ] Code review completed
- [ ] Documentation updated
- [ ] CHANGELOG.md updated
- [ ] No compiler warnings
- [ ] Linter passes (clippy, etc.)
- [ ] Dependencies are up to date

## Deployment Readiness

- [ ] All tests pass in CI
- [ ] Version number updated
- [ ] Release notes prepared
- [ ] Breaking changes documented
- [ ] Migration guide provided (if needed)

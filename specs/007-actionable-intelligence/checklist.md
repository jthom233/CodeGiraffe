# Implementation & Validation Checklist

Based on: ./specs/007-actionable-intelligence/spec.md

## Requirements Validation

- [ ] All methods must handle missing node_id gracefully (return empty results, not exceptions)
- [ ] Compute downstream impact (all descendants)
- [ ] Optionally compute upstream impact (all ancestors) when include_upstream=True
- [ ] For each impacted node, compute "distance" (shortest path length from changed node)
- [ ] Assign severity tier based on distance and edge types:
- [ ] **direct** (distance=1): nodes directly connected
- [ ] **transitive** (distance=2-3): nodes reachable within 2-3 hops
- [ ] **indirect** (distance>3): nodes farther away
- [ ] Return structured result with:
- [ ] `target_node`: the node being analyzed
- [ ] `downstream`: list of impacted nodes with {node_id, label, type, distance, severity, path}
- [ ] `upstream`: list of upstream dependencies (if include_upstream=True) with same fields
- [ ] `total_impact_count`: total number of impacted nodes
- [ ] `cycles`: any circular dependencies involving this node
- [ ] Input: blast_radius result dict, graph: ArchGraph
- [ ] Output: human-readable markdown string
- [ ] Format:
- [ ] Total blast radius:** {N} nodes affected
- [ ] {node_label} ({node_type}) — via {edge_type} edge
- [ ] {node_label} ({node_type}) — {distance} hops via {path_summary}
- [ ] {cycle description} (if any)
- [ ] {node_label} (centrality: {score}) — most-connected node in impact zone
- [ ] "Consider testing {X} — it's {distance} hops away and has {N} dependents"
- [ ] "Warning: circular dependency detected: A → B → C → A"
- [ ] Calls compute_blast_radius() then generate_impact_summary()
- [ ] Returns the human-readable markdown summary
- [ ] Handles errors gracefully (node not found → suggestions like existing query tool)
- [ ] If node_ids provided: assess risk for those specific nodes
- [ ] If node_ids is None: assess the top-10 riskiest nodes in the entire graph
- [ ] Return markdown report with nodes ranked by risk score
- [ ] Signature: `codegiraffe_cycles(project_path: str, max_cycles: int = 20) -> str`
- [ ] Detects circular dependencies in the architecture graph
- [ ] Returns markdown-formatted list of cycles with:
- [ ] Cycle path (A → B → C → A)
- [ ] Edge types involved
- [ ] Severity (shorter cycles are more severe)
- [ ] Files involved
- [ ] Add optional parameter: `include_impact: bool = False`
- [ ] When include_impact=True, for each returned node also include:
- [ ] blast_radius_count: how many nodes it impacts
- [ ] risk_score: the risk assessment score
- [ ] This augments the existing relevance scoring without changing the default behavior
- [ ] Backward compatible: default behavior (include_impact=False) is identical to current
- [ ] Add optional parameter: `metrics: str = "degree"` (options: "degree", "betweenness", "combined")
- [ ] "degree": current behavior (degree_centrality only)
- [ ] "betweenness": rank by betweenness_centrality instead
- [ ] "combined": weighted combination of degree (0.5) + betweenness (0.5)
- [ ] Backward compatible: default is "degree" (identical to current)
- [ ] All new functions in graph.py MUST have unit tests
- [ ] All new functions in query.py MUST have unit tests
- [ ] All new MCP tools MUST have integration tests
- [ ] Test cycles with known circular graph structures
- [ ] Test blast radius with various graph topologies (linear chain, tree, diamond, cyclic)
- [ ] Test impact summary output format
- [ ] Test edge cases: isolated nodes, self-loops, empty graphs, missing nodes
- [ ] Target: 50+ new tests, 748+ total
- [ ] All changes MUST be backward compatible
- [ ] Existing 698 tests MUST continue to pass unchanged
- [ ] New parameters on existing tools default to current behavior
- [ ] No changes to existing return formats unless include_impact/metrics explicitly requested
- [ ] No new required dependencies
- [ ] Cross-system contract node types (deferred to v0.8.0)
- [ ] Contract validation/schema checking (deferred to v0.8.0)
- [ ] Temporal/recency-based impact scoring (deferred)
- [ ] User feedback loops for relevance refinement (deferred)
- [ ] New export formats for impact reports (deferred)
- [ ] New tool codegiraffe_blast_radius returns meaningful markdown for any node in a project
- [ ] Nexus (Go) project: blast radius for "tui" package shows 10+ impacted nodes with severity tiers
- [ ] Self-scan: blast radius for "graph" module shows scanner, query, server as direct dependents
- [ ] Risk assessment correctly identifies graph.py and scanner.py as highest-risk modules
- [ ] Cycle detection finds any circular imports in test graphs
- [ ] Zero regression in existing 698 tests
- [ ] 50+ new tests

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

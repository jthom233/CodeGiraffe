# Specification

## Requirements

## Code Giraffe v0.7.0 — Actionable Intelligence

### Problem Statement
CodeGiraffe produces architecture graphs with rich edge density (v0.6.0 achieved 1.41 edge/node ratio on Go projects), but the intelligence layer returns raw JSON subgraphs that AI agents must interpret manually. There is no blast radius analysis, no impact scoring, no actionable summaries, and no cross-system contract visibility. An AI agent using CodeGiraffe today gets "here are related nodes" but not "here's what breaks if you change this, ordered by severity."

### Goal
Add three new MCP tools and enhance existing ones to transform CodeGiraffe from a passive graph query tool into an active intelligence layer that provides actionable development guidance:
1. **Blast radius analysis** — "what breaks if I change this node?"
2. **Impact summaries** — human-readable, severity-ranked reports instead of raw JSON
3. **Enhanced graph traversal** — cycle detection, path finding, advanced centrality metrics

### Requirements

#### R1: ArchGraph Traversal Extensions
Extend the ArchGraph class in graph.py with thin NetworkX wrappers:
- `get_all_descendants(node_id) -> set[str]` — all transitively reachable downstream nodes via `nx.descendants()`
- `get_all_ancestors(node_id) -> set[str]` — all transitively reachable upstream nodes via `nx.ancestors()`
- `find_paths(source, target, max_depth=10) -> list[list[str]]` — all simple paths between nodes via `nx.all_simple_paths()` with cutoff
- `detect_cycles() -> list[list[str]]` — find circular dependencies via `nx.simple_cycles()` with a reasonable limit (max 100 cycles)
- `get_betweenness_centrality() -> dict[str, float]` — identify bottleneck nodes via `nx.betweenness_centrality()`
- All methods must handle missing node_id gracefully (return empty results, not exceptions)

#### R2: Blast Radius Analysis (query.py)
Add `compute_blast_radius()` function to query.py:
- Input: `graph: ArchGraph, node_id: str, include_upstream: bool = False, max_depth: int | None = None`
- Compute downstream impact (all descendants)
- Optionally compute upstream impact (all ancestors) when include_upstream=True
- For each impacted node, compute "distance" (shortest path length from changed node)
- Assign severity tier based on distance and edge types:
  - **direct** (distance=1): nodes directly connected
  - **transitive** (distance=2-3): nodes reachable within 2-3 hops
  - **indirect** (distance>3): nodes farther away
- Return structured result with:
  - `target_node`: the node being analyzed
  - `downstream`: list of impacted nodes with {node_id, label, type, distance, severity, path}
  - `upstream`: list of upstream dependencies (if include_upstream=True) with same fields
  - `total_impact_count`: total number of impacted nodes
  - `cycles`: any circular dependencies involving this node
  - `critical_paths`: the most-connected downstream nodes (betweenness centrality in the impact subgraph)

#### R3: Impact Summary Generation (query.py)
Add `generate_impact_summary()` function to query.py:
- Input: blast_radius result dict, graph: ArchGraph
- Output: human-readable markdown string
- Format:
  ```
  ## Impact Analysis: {node_label}
  
  **Total blast radius:** {N} nodes affected
  
  ### Direct Dependencies ({count})
  - {node_label} ({node_type}) — via {edge_type} edge
  ...
  
  ### Transitive Impact ({count})
  - {node_label} ({node_type}) — {distance} hops via {path_summary}
  ...
  
  ### Circular Dependencies
  - {cycle description} (if any)
  
  ### Hotspots in Impact Zone
  - {node_label} (centrality: {score}) — most-connected node in impact zone
  ...
  
  ### Recommendations
  - "Consider testing {X} — it's {distance} hops away and has {N} dependents"
  - "Warning: circular dependency detected: A → B → C → A"
  ```

#### R4: MCP Tool — codegiraffe_blast_radius
New MCP tool in server.py:
- Signature: `codegiraffe_blast_radius(project_path: str, node_id: str, include_upstream: bool = False, max_depth: int | None = None) -> str`
- Calls compute_blast_radius() then generate_impact_summary()
- Returns the human-readable markdown summary
- Handles errors gracefully (node not found → suggestions like existing query tool)

#### R5: MCP Tool — codegiraffe_risk_assessment  
New MCP tool in server.py:
- Signature: `codegiraffe_risk_assessment(project_path: str, node_ids: list[str] | None = None) -> str`
- If node_ids provided: assess risk for those specific nodes
- If node_ids is None: assess the top-10 riskiest nodes in the entire graph
- Risk score per node = (degree_centrality * 0.4) + (betweenness_centrality * 0.4) + (descendant_count / total_nodes * 0.2)
- Return markdown report with nodes ranked by risk score
- Include for each node: risk score, blast radius count, centrality metrics, and a brief "why this matters" description

#### R6: MCP Tool — codegiraffe_cycles
New MCP tool in server.py:
- Signature: `codegiraffe_cycles(project_path: str, max_cycles: int = 20) -> str`
- Detects circular dependencies in the architecture graph
- Returns markdown-formatted list of cycles with:
  - Cycle path (A → B → C → A)
  - Edge types involved
  - Severity (shorter cycles are more severe)
  - Files involved

#### R7: Enhanced codegiraffe_context_for
Enhance the existing context_for tool to optionally include impact information:
- Add optional parameter: `include_impact: bool = False`
- When include_impact=True, for each returned node also include:
  - blast_radius_count: how many nodes it impacts
  - risk_score: the risk assessment score
- This augments the existing relevance scoring without changing the default behavior
- Backward compatible: default behavior (include_impact=False) is identical to current

#### R8: Enhanced codegiraffe_hotspots
Enhance the existing hotspots tool with additional centrality metrics:
- Add optional parameter: `metrics: str = "degree"` (options: "degree", "betweenness", "combined")
- "degree": current behavior (degree_centrality only)
- "betweenness": rank by betweenness_centrality instead
- "combined": weighted combination of degree (0.5) + betweenness (0.5)
- Backward compatible: default is "degree" (identical to current)

#### R9: Test Coverage
- All new functions in graph.py MUST have unit tests
- All new functions in query.py MUST have unit tests
- All new MCP tools MUST have integration tests
- Test cycles with known circular graph structures
- Test blast radius with various graph topologies (linear chain, tree, diamond, cyclic)
- Test impact summary output format
- Test edge cases: isolated nodes, self-loops, empty graphs, missing nodes
- Target: 50+ new tests, 748+ total

#### R10: Backward Compatibility
- All changes MUST be backward compatible
- Existing 698 tests MUST continue to pass unchanged
- New parameters on existing tools default to current behavior
- No changes to existing return formats unless include_impact/metrics explicitly requested
- No new required dependencies

### Non-Goals
- Cross-system contract node types (deferred to v0.8.0)
- Contract validation/schema checking (deferred to v0.8.0)
- Temporal/recency-based impact scoring (deferred)
- User feedback loops for relevance refinement (deferred)
- New export formats for impact reports (deferred)

### Success Metrics
- New tool codegiraffe_blast_radius returns meaningful markdown for any node in a project
- Nexus (Go) project: blast radius for "tui" package shows 10+ impacted nodes with severity tiers
- Self-scan: blast radius for "graph" module shows scanner, query, server as direct dependents
- Risk assessment correctly identifies graph.py and scanner.py as highest-risk modules
- Cycle detection finds any circular imports in test graphs
- Zero regression in existing 698 tests
- 50+ new tests

## User Stories

As an AI coding agent, I want to ask "what breaks if I change this module?" and get a severity-ranked list of impacted components so that I can understand the full blast radius before making changes.

As an AI coding agent, I want to see which architectural nodes are the riskiest (most connected, most critical) so that I can prioritize careful testing when modifying them.

As a developer, I want to detect circular dependencies in my architecture so that I can refactor them before they cause issues.

As an AI coding agent, I want context_for to tell me not just "these nodes are relevant" but "these nodes are relevant AND changing them impacts N other components" so that I can make informed decisions.

As a developer, I want CodeGiraffe to give me human-readable impact reports instead of raw JSON graphs so that I can quickly understand architectural risk.

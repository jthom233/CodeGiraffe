[← Back to Documentation](../README.md)

# MCP Tool Reference

Code Giraffe exposes **37 tools** that any MCP client can call.

## Tool Index

| Tool | Category | Description |
|---|---|---|
| [`codegiraffe_init`](core.md#codegiraffe_init) | [Core](core.md) | Scan a project and bootstrap the architecture graph |
| [`codegiraffe_query`](core.md#codegiraffe_query) | [Core](core.md) | Query the graph by node ID or type |
| [`codegiraffe_add_relation`](core.md#codegiraffe_add_relation) | [Core](core.md) | Manually annotate a relationship that automated scanning missed |
| [`codegiraffe_sync`](core.md#codegiraffe_sync) | [Core](core.md) | Re-scan the project and synchronize the architecture graph |
| [`codegiraffe_sync_files`](core.md#codegiraffe_sync_files) | [Core](core.md) | Incrementally sync specific changed files without a full rescan |
| [`codegiraffe_export`](core.md#codegiraffe_export) | [Core](core.md) | Export the architecture graph as a visualization format |
| [`codegiraffe_detect_drift`](core.md#codegiraffe_detect_drift) | [Core](core.md) | Check if the graph still matches the actual codebase |
| [`codegiraffe_dashboard`](core.md#codegiraffe_dashboard) | [Core](core.md) | Launch the interactive web dashboard and open it in the browser |
| [`codegiraffe_context_for`](context-and-analysis.md#codegiraffe_context_for) | [Context & Analysis](context-and-analysis.md) | Return the minimal relevant subgraph for a natural-language task |
| [`codegiraffe_hotspots`](context-and-analysis.md#codegiraffe_hotspots) | [Context & Analysis](context-and-analysis.md) | Identify the most coupled, change-prone areas of the architecture |
| [`codegiraffe_patterns`](context-and-analysis.md#codegiraffe_patterns) | [Context & Analysis](context-and-analysis.md) | Extract naming conventions and detect structural anti-patterns |
| [`codegiraffe_blast_radius`](context-and-analysis.md#codegiraffe_blast_radius) | [Context & Analysis](context-and-analysis.md) | Analyze the blast radius of changing a specific node |
| [`codegiraffe_risk_assessment`](context-and-analysis.md#codegiraffe_risk_assessment) | [Context & Analysis](context-and-analysis.md) | Assess architectural risk scores for nodes |
| [`codegiraffe_cycles`](context-and-analysis.md#codegiraffe_cycles) | [Context & Analysis](context-and-analysis.md) | Detect circular dependencies in the architecture graph |
| [`codegiraffe_contracts`](contracts.md#codegiraffe_contracts) | [Contracts](contracts.md) | List and filter cross-system contracts |
| [`codegiraffe_validate_contracts`](contracts.md#codegiraffe_validate_contracts) | [Contracts](contracts.md) | Validate the integrity of cross-system contracts |
| [`codegiraffe_add_contract`](contracts.md#codegiraffe_add_contract) | [Contracts](contracts.md) | Manually create a cross-system contract node |
| [`codegiraffe_validate_changes`](change-impact.md#codegiraffe_validate_changes) | [Change Impact](change-impact.md) | Detect incomplete modifications from git diff |
| [`codegiraffe_suggest_tests`](change-impact.md#codegiraffe_suggest_tests) | [Change Impact](change-impact.md) | Suggest test files to run based on uncommitted changes |
| [`codegiraffe_file_coupling`](change-impact.md#codegiraffe_file_coupling) | [Change Impact](change-impact.md) | Analyze file coupling from git co-change history |
| [`codegiraffe_pr_diff`](change-impact.md#codegiraffe_pr_diff) | [Change Impact](change-impact.md) | Compare graph architecture at two git refs |
| [`codegiraffe_coverage`](change-impact.md#codegiraffe_coverage) | [Change Impact](change-impact.md) | Map test coverage data to graph nodes |
| [`codegiraffe_claim`](coordination.md#codegiraffe_claim) | [Coordination](coordination.md) | Claim graph nodes for an agent to prevent conflicts |
| [`codegiraffe_status`](coordination.md#codegiraffe_status) | [Coordination](coordination.md) | Update an agent's status and refresh its claim TTL |
| [`codegiraffe_agents`](coordination.md#codegiraffe_agents) | [Coordination](coordination.md) | List all active agents and their claimed nodes |
| [`codegiraffe_history`](versioning.md#codegiraffe_history) | [Versioning](versioning.md) | List version history for the architecture graph |
| [`codegiraffe_diff`](versioning.md#codegiraffe_diff) | [Versioning](versioning.md) | Compare two versions of the architecture graph |
| [`codegiraffe_snapshot`](versioning.md#codegiraffe_snapshot) | [Versioning](versioning.md) | Create a named snapshot of the current graph state |
| [`codegiraffe_restore`](versioning.md#codegiraffe_restore) | [Versioning](versioning.md) | Restore the architecture graph to a specific version |
| [`codegiraffe_federate`](federation.md#codegiraffe_federate) | [Federation](federation.md) | Register multiple repositories into a federated view |
| [`codegiraffe_cross_query`](federation.md#codegiraffe_cross_query) | [Federation](federation.md) | Query across federated graphs using namespaced node IDs |
| [`codegiraffe_cross_edges`](federation.md#codegiraffe_cross_edges) | [Federation](federation.md) | List all edges that cross repository boundaries |
| [`codegiraffe_cypher`](federation.md#codegiraffe_cypher) | [Federation](federation.md) | Run a read-only Cypher query against a Neo4j-backed graph |
| [`codegiraffe_annotate`](planning.md#codegiraffe_annotate) | [Planning](planning.md) | Annotate nodes with owner, stability, and custom notes |
| [`codegiraffe_domains`](planning.md#codegiraffe_domains) | [Planning](planning.md) | Infer or manage domain groupings from directory structure |
| [`codegiraffe_order_tasks`](planning.md#codegiraffe_order_tasks) | [Planning](planning.md) | Order tasks by dependency topology |
| [`codegiraffe_migration_plan`](planning.md#codegiraffe_migration_plan) | [Planning](planning.md) | Generate an ordered migration plan for large refactors |

## Categories

- **[Core](core.md)** (8 tools) — Graph initialization, querying, manual annotation, sync, export, drift detection, dashboard
- **[Context & Analysis](context-and-analysis.md)** (6 tools) — Intelligent context retrieval, hotspots, patterns, blast radius, risk, cycles
- **[Contracts](contracts.md)** (3 tools) — Cross-system contract modeling and validation
- **[Change Impact](change-impact.md)** (5 tools) — Change validation, test suggestions, file coupling, PR diffing, coverage
- **[Coordination](coordination.md)** (3 tools) — Multi-agent claim/status coordination
- **[Versioning](versioning.md)** (4 tools) — Schema evolution, history, snapshots, restore
- **[Federation](federation.md)** (4 tools) — Cross-repo federation, namespaced queries, Cypher
- **[Planning](planning.md)** (4 tools) — Annotation, domains, task ordering, migration planning

[← Back to Documentation](README.md)

# Usage Patterns

Common workflows and integration patterns for getting the most out of Code Giraffe.

---

## Orchestrator + Subagent Workflow

The most powerful pattern is using Code Giraffe as context for an orchestrator that delegates to subagents:

1. **Orchestrator** calls `codegiraffe_context_for(task="add rate limiting to payments")`
2. **Code Giraffe** returns the relevant subgraph (payments endpoint, its DB tables, middleware, env vars)
3. **Orchestrator** includes this context in the subagent's prompt
4. **Subagent** has exactly the architectural knowledge it needs — no wasted tokens

This pattern ensures subagents make changes that account for the full impact of their work, not just the files they can directly see.

See [Context and Analysis Tools](tools/context-and-analysis.md) for the full `codegiraffe_context_for` parameter reference.

---

## Continuous Graph Maintenance

Keep the graph in sync with your codebase as it evolves:

```
1. codegiraffe_init()          --> Bootstrap on first use
2. codegiraffe_add_relation()  --> Annotate what the scanner missed
3. codegiraffe_sync()          --> Update after code changes
4. codegiraffe_detect_drift()  --> Catch stale graph entries
5. codegiraffe_export()        --> Generate diagrams for documentation
```

For targeted updates after small changes, use `codegiraffe_sync_files` to sync only the affected files — much faster than a full rescan for large projects.

See [Core Tools](tools/core.md) for the full reference on init, sync, and export.

---

## Pre-Change Impact Analysis

Before modifying any code, understand the full blast radius of your change:

```
1. codegiraffe_blast_radius(node_id="endpoint:/api/payments")
   --> See downstream impact ranked by severity (direct, transitive, indirect)

2. codegiraffe_risk_assessment(node_ids=["endpoint:/api/payments"])
   --> Get composite risk score (degree + betweenness + descendants)

3. codegiraffe_hotspots(top_n=5, metrics="combined")
   --> Know which areas are most coupled and risky to change

4. codegiraffe_cycles()
   --> Detect circular dependencies that amplify change risk

5. codegiraffe_export(format="mermaid", node_id="endpoint:/api/payments", depth=2)
   --> Visualize the subgraph for documentation or review
```

See [Context and Analysis Tools](tools/context-and-analysis.md) for the full reference on blast radius and risk assessment.

---

## Cross-System Contracts

Code Giraffe models cross-system contracts — API schemas, event schemas, configuration contracts, and data contracts — as first-class `contract` nodes in the architecture graph. Contracts capture the coupling between producers (who define the contract) and consumers (who depend on it), making it possible to understand the full impact of schema changes, API modifications, and event format updates.

The scanner automatically infers contracts from detected patterns (e.g., API endpoints become API contracts, event emitters become event contracts). You can also create contracts manually:

```
1. codegiraffe_add_contract(name="User API", contract_type="api",
     producer="endpoint:/api/users", consumers="component:UserList,service:UserSync")
   --> Create a contract with explicit producer/consumer relationships

2. codegiraffe_contracts(contract_type="api")
   --> List all API contracts with their producers and consumers

3. codegiraffe_validate_contracts()
   --> Check contract integrity (orphaned consumers, missing producers, etc.)
```

Contract-aware blast radius analysis automatically flags contract consumers as **critical** severity, ensuring that changes to shared contracts surface all downstream impact.

See [Contracts Tools](tools/contracts.md) for the full contracts reference.

---

## Change Impact Validation

Before committing changes, validate completeness and identify the right tests to run:

```
1. codegiraffe_validate_changes(project_path="...")
   --> Detect incomplete modifications: maps your diff to graph nodes,
       computes blast radius, and flags potentially missing changes

2. codegiraffe_suggest_tests(project_path="...")
   --> Get prioritized test file recommendations based on graph relationships,
       naming conventions, and blast radius analysis

3. codegiraffe_file_coupling(project_path="...", depth=50)
   --> Discover implicit coupling from git history: files that always change
       together but aren't connected in the graph
```

See [Change Validation Tools](tools/change-impact.md) for the full reference on validate_changes, suggest_tests, and file_coupling.

---

## Multi-Agent Development

When running multiple agents in parallel on the same codebase, use coordination tools to prevent conflicts:

```
1. codegiraffe_agents()              --> See who is working where
2. codegiraffe_claim(...)            --> Claim nodes before modifying them
3. codegiraffe_status(..., "active") --> Keep claim alive while working
4. codegiraffe_status(..., "done")   --> Release claims when finished
```

**Example workflow:**

```
# Agent 1 claims the payments subsystem
codegiraffe_claim(project_path="...", agent_id="agent-1",
  node_ids=["endpoint:/api/payments", "service:PaymentService"],
  task="Add Stripe webhook handler", ttl=1800)

# Agent 2 tries to claim an overlapping node -- gets a conflict
codegiraffe_claim(project_path="...", agent_id="agent-2",
  node_ids=["service:PaymentService"],
  task="Refactor payment validation")
--> {"status": "conflict", "conflicting_agent": "agent-1", ...}

# Agent 1 finishes and releases its claims
codegiraffe_status(project_path="...", agent_id="agent-1", status="done")

# Agent 2 can now claim successfully
codegiraffe_claim(project_path="...", agent_id="agent-2",
  node_ids=["service:PaymentService"],
  task="Refactor payment validation")
--> {"status": "claimed", ...}
```

See [Coordination Tools](tools/coordination.md) for the full reference on claim, status, and agents.

[← Back to Documentation](../README.md) | [Tool Index](README.md)

# Multi-Agent Coordination

When multiple AI agents work on the same codebase simultaneously, Code Giraffe provides coordination tools to prevent conflicts.

## How It Works

1. **Claim** — Before modifying part of the architecture, an agent claims the relevant nodes using `codegiraffe_claim`. If another agent already holds a conflicting claim, the request fails with details about the conflict.
2. **Status** — While working, agents update their status (`"active"`, `"blocked"`, `"done"`) using `codegiraffe_status`. Active updates refresh the claim TTL so it doesn't expire during long-running tasks.
3. **Visibility** — Any agent can call `codegiraffe_agents` to see who is working on what, enabling informed coordination decisions.
4. **Expiration** — Claims automatically expire after their TTL (default: 30 minutes) to prevent deadlocks from crashed or abandoned agents.

## Example Workflow

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

# Agent 2 checks who is working where
codegiraffe_agents(project_path="...")
--> Shows agent-1 is active on PaymentService

# Agent 1 finishes and releases its claims
codegiraffe_status(project_path="...", agent_id="agent-1", status="done")

# Agent 2 can now claim successfully
codegiraffe_claim(project_path="...", agent_id="agent-2",
  node_ids=["service:PaymentService"],
  task="Refactor payment validation")
--> {"status": "claimed", ...}
```

---

### `codegiraffe_claim`

Claim graph nodes for an agent to prevent conflicts during concurrent multi-agent development.

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_path` | `str` | — | yes | Root directory of the project |
| `agent_id` | `str` | — | yes | Unique agent identifier |
| `node_ids` | `list[str]` | — | yes | Node IDs to claim |
| `task` | `str` | — | yes | Description of the agent's task |
| `ttl` | `int` | `1800` | no | Claim expiration in seconds (default: 30 min) |

Claims automatically expire after `ttl` seconds. If another agent has already claimed overlapping nodes, the claim fails with conflict details.

**Example:**
```
codegiraffe_claim(
  project_path="/home/user/my-project",
  agent_id="agent-1",
  node_ids=["endpoint:/api/payments", "service:PaymentService"],
  task="Add Stripe webhook handler"
)
--> {"status": "claimed", "agent_id": "agent-1", "nodes": [...], "expires_at": "..."}
```

---

### `codegiraffe_status`

Update an agent's status and refresh its claim TTL.

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_path` | `str` | — | yes | Root directory of the project |
| `agent_id` | `str` | — | yes | Agent identifier |
| `status` | `str` | — | yes | `"active"`, `"done"`, or `"blocked"` |
| `task` | `str \| None` | `None` | no | Updated task description |

Setting status to `"done"` releases the agent's claimed nodes. Setting status to `"active"` refreshes the TTL so claims don't expire during long-running work.

**Example:**
```
codegiraffe_status(
  project_path="/home/user/my-project",
  agent_id="agent-1",
  status="done"
)
--> {"agent_id": "agent-1", "status": "done", "released_nodes": [...]}
```

---

### `codegiraffe_agents`

List all active agents and their claimed nodes, enabling coordination and conflict avoidance.

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_path` | `str` | — | yes | Root directory of the project |

**Example:**
```
codegiraffe_agents(project_path="/home/user/my-project")
--> [
      {"agent_id": "agent-1", "status": "active", "task": "Add Stripe webhook", "nodes": ["endpoint:/api/payments"], "expires_at": "..."},
      {"agent_id": "agent-2", "status": "blocked", "task": "Update user schema", "nodes": ["table:users"], "expires_at": "..."}
    ]
```

---

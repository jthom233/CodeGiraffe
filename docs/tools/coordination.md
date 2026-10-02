[← Back to Documentation](../README.md) | [Tool Index](README.md)

# Multi-Agent Coordination

When multiple AI agents work on the same codebase simultaneously, Code Giraffe provides coordination tools to prevent conflicts.

## How It Works

1. **Claim** — Before modifying part of the architecture, an agent claims the relevant nodes using `codegiraffe_claim`. If another agent already holds a conflicting claim, the request fails with details about the conflict.
2. **Status** — While working, agents update their status (`"active"`, `"blocked"`, `"done"`) using `codegiraffe_update_agent_status`. Active updates refresh the claim TTL so it doesn't expire during long-running tasks. When status is set to `"done"`, claims are automatically released.
3. **Manual Release** — If an agent needs to release claims without completing (e.g., due to an error), call `codegiraffe_release` to immediately release them.
4. **Visibility** — Any agent can call `codegiraffe_agents` to see who is working on what, enabling informed coordination decisions.
5. **Expiration** — Claims automatically expire after their TTL (default: 30 minutes) to prevent deadlocks from crashed or abandoned agents.

## Concurrency

Every claim/status-update/release call is serialized around a load-modify-save
cycle on the on-disk store (`<project>/.codegiraffe/agents.json`), so two
agents racing for the same nodes can never both "win":

- **Cross-process locking** — an OS-level exclusive lock on a sibling
  `agents.json.lock` file (`msvcrt.locking` on Windows, `fcntl.flock`
  elsewhere), acquired with a bounded retry (every 50 ms, up to ~5 s total).
  If the lock can't be acquired in that window, the call fails with a clear
  timeout error rather than hanging indefinitely.
- **In-process locking** — a `threading.Lock` held alongside the file lock,
  since the MCP server and its dashboard thread share one `CoordinationStore`
  instance in the same process, and OS file locks alone don't serialize
  threads within a process.
- **Atomic writes** — the store file is written to a tempfile in the same
  directory and swapped into place with `os.replace()` (the same pattern
  `JSONStorage` uses for the graph file), so a crash or failure mid-write
  can never leave `agents.json` truncated or corrupted.

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
codegiraffe_update_agent_status(project_path="...", agent_id="agent-1", status="done")

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

### `codegiraffe_update_agent_status`

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
codegiraffe_update_agent_status(
  project_path="/home/user/my-project",
  agent_id="agent-1",
  status="done"
)
--> {"agent_id": "agent-1", "status": "done", "released_nodes": [...]}
```

---

### `codegiraffe_release`

Manually release all of an agent's claimed nodes. Releases every node the agent currently holds — there is no per-node selection.

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_path` | `str` | — | yes | Root directory of the project |
| `agent_id` | `str` | — | yes | Agent identifier whose claims will be released |

Use this when an agent needs to abandon all claims due to an error or cancellation without completing the task.

**Example:**
```
codegiraffe_release(
  project_path="/home/user/my-project",
  agent_id="agent-1"
)
--> {"success": true, "released": 2}
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

[← Back to Documentation](../README.md) | [Tool Index](README.md)

# Planning & Organization

These tools help you understand, annotate, and plan work against the architecture graph. Use them to add ownership and stability metadata to nodes, infer domain groupings, order tasks by dependency topology, and generate phased migration plans for large refactors.

---

### `codegiraffe_annotate`

Annotate nodes with metadata including owner, stability status, and custom notes. Annotations are marked as manual and survive re-scans.

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_path` | `str` | — | yes | Root directory of the project |
| `node_id` | `str` | — | yes | Node ID to annotate |
| `owner` | `str \| None` | `None` | no | Owner team/person for this node |
| `stability` | `str \| None` | `None` | no | Stability status: `stable`, `experimental`, `deprecated`, `legacy` |
| `notes` | `str \| None` | `None` | no | Free-form notes or documentation for this node |

**Example:**
```
codegiraffe_annotate(
  project_path="/home/user/my-project",
  node_id="service:PaymentService",
  owner="payments-team",
  stability="stable",
  notes="Stripe integration. Critical path. Do not break."
)
--> "Annotated service:PaymentService: owner=payments-team, stability=stable"
```

---

### `codegiraffe_domains`

Infer or manage domain groupings from directory structure. Groups related services/modules into logical domains.

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_path` | `str` | — | yes | Root directory of the project |
| `action` | `str` | — | yes | Action: `"infer"`, `"list"`, `"create"`, or `"update"` |
| `name` | `str` | optional | no | Domain name (required for `create`/`update`) |
| `node_ids` | `list[str]` | optional | no | Node IDs to assign to domain (for `create`/`update`) |

**Example:**
```
codegiraffe_domains(
  project_path="/home/user/my-project",
  action="infer"
)
--> {
      "domains": [
        {
          "name": "auth",
          "nodes": ["endpoint:/api/login", "service:AuthService", "table:users"],
          "inferred_from": "src/auth/*"
        },
        {
          "name": "payments",
          "nodes": ["endpoint:/api/payments", "service:PaymentService", "queue:payment-events"],
          "inferred_from": "src/payments/*"
        }
      ]
    }
```

---

### `codegiraffe_order_tasks`

Order a list of tasks by dependency topology, grouping parallelizable tasks and identifying conflict zones.

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_path` | `str` | — | yes | Root directory of the project |
| `tasks` | `str` | — | yes | JSON array of tasks with `id`, `description`, and optional `dependencies` fields |

**Example:**
```
codegiraffe_order_tasks(
  project_path="/home/user/my-project",
  tasks='[
    {"id": "task-1", "description": "Add auth endpoint", "dependencies": []},
    {"id": "task-2", "description": "Add user table", "dependencies": []},
    {"id": "task-3", "description": "Add user service", "dependencies": ["task-1", "task-2"]}
  ]'
)
--> {
      "ordered_groups": [
        ["task-1", "task-2"],  # Can run in parallel
        ["task-3"]              # Depends on both above
      ],
      "conflict_zones": []
    }
```

---

### `codegiraffe_migration_plan`

Generate an ordered migration plan for large refactors, identifying safe stages and breaking large changes into phases.

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_path` | `str` | — | yes | Root directory of the project |
| `description` | `str` | — | yes | Description of the refactor (e.g., "migrate auth from Firebase to JWT") |
| `target_nodes` | `list[str]` | optional | no | Specific nodes involved in the refactor |

**Example:**
```
codegiraffe_migration_plan(
  project_path="/home/user/my-project",
  description="migrate auth from Firebase to JWT",
  target_nodes=["service:AuthService", "endpoint:/api/login"]
)
--> {
      "phases": [
        {
          "phase": 1,
          "title": "Create JWT infrastructure",
          "nodes": ["service:TokenService"],
          "estimated_effort": "1-2 days"
        },
        {
          "phase": 2,
          "title": "Dual-mode endpoints (Firebase + JWT)",
          "nodes": ["endpoint:/api/login"],
          "estimated_effort": "2-3 days"
        },
        {
          "phase": 3,
          "title": "Migrate consumers to JWT",
          "nodes": ["service:UserService", "component:Dashboard"],
          "estimated_effort": "1-2 days"
        }
      ],
      "total_estimated_effort": "4-7 days",
      "breaking_points": []
    }
```

---

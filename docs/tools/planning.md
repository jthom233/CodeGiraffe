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
--> "Annotated node 'service:PaymentService' with: owner, stability, notes"
```

---

### `codegiraffe_list_domains`

List all defined domains in the architecture graph.

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_path` | `str` | — | yes | Root directory of the project |

**Example:**
```
codegiraffe_list_domains(project_path="/home/user/my-project")
--> Domains:
      auth [manual]: 3 member(s)
      payments: 2 member(s)
```

---

### `codegiraffe_infer_domains`

Auto-infer domain groupings from directory structure or ID prefix patterns.

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_path` | `str` | — | yes | Root directory of the project |

Auto-clustering creates domains for any cluster with 2+ members. Manual domains survive rescans.

**Example:**
```
codegiraffe_infer_domains(project_path="/home/user/my-project")
--> Inferred and added domains:
      auth: 3 member(s)
      payments: 3 member(s)
```

---

### `codegiraffe_add_domain`

Create a domain and assign nodes to it.

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_path` | `str` | — | yes | Root directory of the project |
| `name` | `str` | — | yes | Domain name |
| `node_ids` | `str` | — | yes | Comma-separated node IDs to assign to domain |

**Example:**
```
codegiraffe_add_domain(
  project_path="/home/user/my-project",
  name="billing",
  node_ids="endpoint:/api/billing,service:BillingService,table:invoices"
)
--> "Added domain 'billing' with 3 member(s)."
```

---

### `codegiraffe_remove_domain`

Delete a domain and its associations.

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_path` | `str` | — | yes | Root directory of the project |
| `name` | `str` | — | yes | Domain name to remove |

**Example:**
```
codegiraffe_remove_domain(
  project_path="/home/user/my-project",
  name="billing"
)
--> "Removed domain 'billing'."
```

---

### `codegiraffe_order_tasks`

Order a list of tasks by dependency topology, grouping parallelizable tasks and identifying conflict zones.

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_path` | `str` | — | yes | Root directory of the project |
| `tasks` | `str` | — | yes | JSON array of tasks. Each task must have `name` (str) and `target_files` (list of file paths). Dependencies are inferred from graph relationships — no explicit `dependencies` field. |

**Example:**
```
codegiraffe_order_tasks(
  project_path="/home/user/my-project",
  tasks='[
    {"name": "Add auth endpoint", "target_files": ["src/auth.py"]},
    {"name": "Add user table", "target_files": ["src/models/user.py"]},
    {"name": "Add user service", "target_files": ["src/services/user_service.py"]}
  ]'
)
--> ## Task Ordering Report
    **3 task(s) ordered**

    ### Execution Plan
    Group 1 (parallel): Add auth endpoint, Add user table
    Group 2 (sequential): Add user service
```

---

### `codegiraffe_migration_plan`

Generate an ordered migration plan for large refactors, identifying safe stages and breaking large changes into phases.

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_path` | `str` | — | yes | Root directory of the project |
| `description` | `str` | — | yes | Description of the refactor (e.g., "migrate auth from Firebase to JWT") |
| `target_nodes` | `str \| None` | `None` | no | Optional JSON array string of explicit node IDs involved in the refactor (e.g. `'["service:AuthService", "endpoint:/api/login"]'`). When omitted, affected nodes are inferred from `description`. |

**Example:**
```
codegiraffe_migration_plan(
  project_path="/home/user/my-project",
  description="migrate auth from Firebase to JWT",
  target_nodes='["service:AuthService", "endpoint:/api/login"]'
)
--> ## Migration Plan: migrate auth from Firebase to JWT

    **Steps:** 2  |  **Files affected:** 2  |  **Checkpoints:** 1

    ### Steps
    1. migrate `endpoint:/api/login` (`src/api/login.py`) ✓ checkpoint
    2. migrate `service:AuthService` (`src/services/auth_service.py`)

    ### Contract Implications
    - **UserAuthContract**: producer changes — verify consumers
```

---

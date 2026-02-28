[← Back to Documentation](../README.md) | [Tool Index](README.md)

# Cross-System Contracts

Contracts represent API schemas, event schemas, configuration contracts, and data contracts that couple different parts of the system. The scanner infers contracts automatically from matching producer/consumer node pairs; these tools let you list, validate, and manually create them.

---

### `codegiraffe_contracts`

List and filter cross-system contracts in the architecture graph.

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_path` | `str` | — | yes | Root directory of the project |
| `contract_type` | `str \| None` | `None` | no | Filter by contract type: `"api"`, `"event"`, `"config"`, `"data"` |
| `status` | `str \| None` | `None` | no | Filter by validation status |
| `node_id` | `str \| None` | `None` | no | Filter to contracts involving a specific producer or consumer node |

**Example:**
```
codegiraffe_contracts(project_path="/home/user/my-project", contract_type="api")
--> ## Contracts
    **2 contract(s) found**

    ### User API
    - **Type:** api
    - **Status:** active
    - **Producer:** GET /api/users (endpoint)
    - **Consumers:**
      - UserList (frontend_component)
      - UserSync (service)
```

---

### `codegiraffe_validate_contracts`

Validate the integrity of cross-system contracts. Checks that all contract producers and consumers exist, that contracts have at least one producer, and detects orphaned or broken contracts.

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_path` | `str` | — | yes | Root directory of the project |

**Example:**
```
codegiraffe_validate_contracts(project_path="/home/user/my-project")
--> ## Contract Validation Report

    **Total contracts:** 15

    ### Valid (12)

    - **UserService API** (api)
    - **PaymentService API** (api)

    ### Broken -- Producer Missing (1)

    - **LegacyAuthContract** -- producer `endpoint:/api/legacy-auth` not in graph

    ### Orphaned -- All Consumers Missing (1)

    - **InternalQueue** -- consumers ['service:OldWorker'] not in graph

    ### Deprecated With Active Consumers (1)

    - **UserV1Contract** -- deprecated but still consumed by ['component:Dashboard']
```

---

### `codegiraffe_add_contract`

Manually create a cross-system contract node with its producer and consumer relationships. The contract node and its edges are marked as manual so they survive re-scans.

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_path` | `str` | — | yes | Root directory of the project |
| `name` | `str` | — | yes | Contract name (used to generate node ID `contract:{name}`) |
| `contract_type` | `str` | — | yes | Contract type: `"api"`, `"event"`, `"config"`, `"data"` |
| `producer` | `str` | — | yes | Node ID of the producer that defines this contract |
| `consumers` | `str` | — | yes | Comma-separated node IDs that consume/depend on this contract |
| `version` | `str` | `""` | no | Optional contract version string |
| `metadata` | `str` | `"{}"` | no | JSON string of extra key-value pairs |

**Example:**
```
codegiraffe_add_contract(
  project_path="/home/user/my-project",
  name="UserService API",
  contract_type="api",
  producer="endpoint:/api/users",
  consumers="component:UserList,service:UserSync"
)
--> "Added contract 'UserService API' (api): endpoint:/api/users --[produces]--> contract:UserService API
     component:UserList --[consumes_contract]--> contract:UserService API
     service:UserSync --[consumes_contract]--> contract:UserService API"
```

---

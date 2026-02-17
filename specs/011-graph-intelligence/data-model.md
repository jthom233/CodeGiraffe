# Data Model: Graph Intelligence

**Branch**: `011-graph-intelligence` | **Date**: 2026-02-16

## Schema Changes

### Edge Model (graph.py)

**Current:**
```
Edge: source, target, type, metadata, manual
```

**New:**
```
Edge: source, target, type, metadata, manual, confidence (float, default=1.0)
```

- `confidence` — 0.0 to 1.0 float indicating detection reliability
- Default 1.0 ensures backward compatibility with existing stored graphs
- Pydantic v2 `model_validate()` auto-fills default on load

### New Node Types (schema.py)

| Type | ID Format | Example |
|------|-----------|---------|
| `decision` | `decision:{file}:{line}` | `decision:src/auth.py:42` |
| `domain` | `domain:{name}` | `domain:payments` |

### New Edge Types (schema.py)

| Type | Source → Target | Purpose |
|------|----------------|---------|
| `constrains` | decision → any node | Decision governs this node |
| `motivated_by` | decision → any node | Decision motivated by this context |
| `supersedes` | decision → decision | Newer decision replaces older |
| `belongs_to` | any node → domain | Node is part of this domain |
| `tested_by` | any node → module (test) | Test file covers this node |

## Key Entities

### Token Budget Context

Not persisted — computed at query time.

| Field | Type | Description |
|-------|------|-------------|
| `_token_estimate` | int | Estimated tokens for returned subgraph |
| `_detail_level` | str | "summary" / "standard" / "detailed" |

### Intent Classification

Not persisted — computed at query time.

| Field | Type | Description |
|-------|------|-------------|
| `_retrieval_strategy` | str | Classified intent (create/modify/debug/refactor/delete/test/general) |
| `_intent_keywords` | list[str] | Keywords that triggered classification |

### Decision Node Metadata

| Field | Type | Description |
|-------|------|-------------|
| `text` | str | Full decision text |
| `adr_id` | str or None | ADR identifier (e.g., "ADR-007") |
| `line_number` | int | Source line number |
| `mined_from` | str | "comment" / "commit" / "manual" |

### Pattern Brief (Convention Mining)

Returned by `codegiraffe_patterns`, not persisted.

| Field | Type | Description |
|-------|------|-------------|
| `node_type` | str | Type being analyzed |
| `sample_size` | int | Number of nodes in cluster |
| `naming_pattern` | str | Common naming convention detected |
| `common_attributes` | dict | Attributes present in >66% of nodes |
| `outliers` | list[str] | Node IDs deviating from conventions |
| `exemplar` | str | Node ID most representative of pattern |

### Ownership Annotation

Stored in node metadata (not a separate model).

| Field | Type | Description |
|-------|------|-------------|
| `owner` | str | Team or person (from CODEOWNERS / git blame / manual) |
| `stability` | str | "stable" / "experimental" / "deprecated" / "legacy" |
| `notes` | str | Free-text tribal knowledge |

### Domain Mapping

Stored as `domain` nodes with `belongs_to` edges.

| Field | Type | Description |
|-------|------|-------------|
| `name` | str | Domain name (e.g., "payments") |
| `inferred` | bool | Auto-detected vs manually created |
| `node_count` | int | Number of member nodes |

### Graph Diff Report

Returned by `codegiraffe_pr_diff`, not persisted.

| Field | Type | Description |
|-------|------|-------------|
| `base_ref` | str | Base git ref |
| `head_ref` | str | Head git ref |
| `nodes_added` | list[str] | New node IDs |
| `nodes_removed` | list[str] | Deleted node IDs |
| `nodes_modified` | list[str] | Changed node IDs |
| `edges_added` | list[dict] | New edges (source, target, type) |
| `edges_removed` | list[dict] | Deleted edges |
| `contracts_affected` | list[str] | Contract IDs impacted |
| `new_cycles` | list[list[str]] | Newly introduced dependency cycles |
| `summary` | str | Human-readable summary |

### Task Execution Plan

Returned by `codegiraffe_order_tasks`, not persisted.

| Field | Type | Description |
|-------|------|-------------|
| `ordered_tasks` | list[dict] | Tasks in execution order |
| `parallel_groups` | list[list[int]] | Groups of task indices that can run in parallel |
| `conflict_zones` | list[dict] | Tasks sharing files, requiring sequential execution |
| `dependency_edges` | list[dict] | (task_a, task_b, reason) |

### Migration Plan

Returned by `codegiraffe_migration_plan`, not persisted.

| Field | Type | Description |
|-------|------|-------------|
| `steps` | list[dict] | Ordered transformation steps |
| `checkpoints` | list[int] | Step indices that are safe rollback points |
| `contract_implications` | list[dict] | Contracts affected and when |
| `estimated_files` | int | Total files touched |

## State Transitions

### Edge Confidence Lifecycle

```
Created by scanner → confidence assigned based on detection method
↓
Loaded from storage → missing confidence defaults to 1.0
↓
Filtered by query → min_confidence parameter excludes low-confidence edges
↓
Weighted by impact analysis → blast_radius severity scaled by confidence
```

### Decision Node Lifecycle

```
Detected by scanner (comment marker) → decision node created, constrains edges inferred
OR manually added → decision node created with manual=True
↓
Referenced by context_for → auto-included when governed nodes appear
↓
Superseded → new decision node linked via supersedes edge
↓
Orphaned (governed nodes deleted) → persists with warning flag in metadata
```

### Domain Lifecycle

```
Auto-inferred from directory structure → domain nodes + belongs_to edges created
OR manually defined → domain node with manual=True
↓
Survives rescans → manual domains preserved, inferred re-computed
↓
Queried via context_for or blast_radius → domain grouping applied
```

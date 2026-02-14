# Implementation Plan: Code Giraffe v0.8.0 -- Cross-System Contracts

## Overview

This plan adds contract-aware scanning, new schema types, three new MCP tools,
enhanced blast radius analysis, and dashboard contract styling. Contracts
represent explicit or inferred agreements between architectural nodes -- API
contracts (producer/consumer), data contracts (schema expectations), event
contracts (publisher/subscriber), and configuration contracts (env var
dependencies).

**Scope:** 6 phases, 7 source files modified, 2 new test files, 3 new MCP tools
(25 total), 40+ new tests (794+ total).

---

## Phase 1: Schema + Data Model (Serial -- Must Go First)

### Rationale
All subsequent phases reference the new enum values. This phase is trivial but
foundational: add enum members, verify they exist, done.

### Files to Modify

#### `src/codegiraffe/schema.py`

**Add to `NodeType` enum** (after `MODULE = "module"`, line 23):
```python
CONTRACT = "contract"
```

**Add to `EdgeType` enum** (after `CROSS_REPO_CONSUMES`, line 44):
```python
PRODUCES = "produces"
CONSUMES_CONTRACT = "consumes_contract"
VALIDATES = "validates"
VIOLATES = "violates"
```

**Pattern to follow:** Each enum member is `NAME = "snake_case_value"` on its
own line. StrEnum values match the lowercase member name. Existing members are
never reordered or removed.

### Tests

#### `tests/test_schema.py` (modify existing)

Add assertions inside existing test class that checks all enum values:

```python
def test_contract_node_type_exists():
    assert NodeType.CONTRACT == "contract"

def test_produces_edge_type_exists():
    assert EdgeType.PRODUCES == "produces"

def test_consumes_contract_edge_type_exists():
    assert EdgeType.CONSUMES_CONTRACT == "consumes_contract"

def test_validates_edge_type_exists():
    assert EdgeType.VALIDATES == "validates"

def test_violates_edge_type_exists():
    assert EdgeType.VIOLATES == "violates"
```

**Test count:** +5 tests

---

## Phase 2: Contract Inference (Depends on Phase 1)

### Rationale
The scanner pipeline already has a clear pattern for post-scan inference:
`_infer_cross_file_edges`, `_infer_import_edges_universal`,
`_infer_inheritance_edges_universal`. We add `_infer_contract_edges` as a new
step in the same pipeline, called after all other inference steps in
`scan_project()` (line 1167, after `_infer_inheritance_edges`).

### Files to Modify

#### `src/codegiraffe/scanner.py`

##### 1. New top-level function: `_infer_contract_edges`

**Insert after:** `_infer_inheritance_edges_universal` (line 993)

**Signature:**
```python
def _infer_contract_edges(result: ScanResult) -> None:
    """Infer contract nodes and produces/consumes_contract edges.

    Examines the merged scan result for matching producer/consumer pairs:
    - API contracts: endpoint nodes matched against external_api nodes by URL path
    - Event contracts: event nodes matched by label (publisher/subscriber)
    - Config contracts: env_var nodes with both writer and reader references
    - Data contracts: database_table nodes referenced by multiple files

    Creates contract nodes (type=CONTRACT) and produces/consumes_contract edges.
    """
```

**Implementation:** Calls four sub-functions, each responsible for one contract
type. Each sub-function mutates `result.nodes` and `result.edges` in place.

```python
def _infer_contract_edges(result: ScanResult) -> None:
    _infer_api_contracts(result)
    _infer_event_contracts(result)
    _infer_config_contracts(result)
    _infer_data_contracts(result)
```

##### 2. Sub-function: `_infer_api_contracts`

**Signature:**
```python
def _infer_api_contracts(result: ScanResult) -> None:
    """Infer API contracts from endpoint + external_api node pairs.

    When an endpoint node defines a path (e.g., /api/users) and an
    external_api node references a URL containing that same path, infer
    a contract linking the producer (endpoint) to the consumer
    (external_api's parent module or service).
    """
```

**Algorithm:**
1. Collect all `endpoint` nodes. Extract their path from `node.metadata["path"]`
   or parse from `node.id` (format: `endpoint:METHOD /path`).
2. Collect all `external_api` nodes. Extract URL path from `node.metadata["url"]`
   or `node.label`.
3. For each endpoint, find external_api nodes whose URL path ends with the
   endpoint's path (suffix match, stripping scheme/host).
4. For each match, create:
   - Contract node: `id="contract:api:{path}"`, `type=NodeType.CONTRACT`,
     `label="API: {path}"`, `metadata={"contract_type": "api", "producer": endpoint.id, "consumers": [ext_api.id, ...], "status": "active"}`
   - Edge: `source=endpoint.id`, `target=contract_id`, `type=EdgeType.PRODUCES`
   - Edge: `source=ext_api.id`, `target=contract_id`, `type=EdgeType.CONSUMES_CONTRACT`
5. Deduplicate: skip if contract node with same ID already exists.

**Pattern to follow:** `_infer_cross_file_edges` (line 789) -- builds lookup
dicts from `result.nodes`, uses `existing_edges` set to deduplicate, appends
new nodes/edges to `result`.

##### 3. Sub-function: `_infer_event_contracts`

**Signature:**
```python
def _infer_event_contracts(result: ScanResult) -> None:
    """Infer event contracts from matching event node labels.

    When multiple event nodes share the same label (event name), one is
    the publisher and the other is the subscriber. Group by label and
    create a contract for each group with 2+ nodes.
    """
```

**Algorithm:**
1. Collect all `event` nodes. Group by label (event name).
2. For each group with 2+ nodes:
   - The node whose containing edges include a `publishes` edge is the producer.
   - All others are consumers.
   - If no clear producer, use the first node as producer.
3. Create contract node + produces/consumes_contract edges.
4. Contract ID: `contract:event:{event_label}`.

##### 4. Sub-function: `_infer_config_contracts`

**Signature:**
```python
def _infer_config_contracts(result: ScanResult) -> None:
    """Infer config contracts from env_var nodes with writer + reader.

    When an env_var node has both edges leading TO it (writes/configures)
    and edges leading FROM it (reads/depends_on), infer a config contract
    between the writer and readers.
    """
```

**Algorithm:**
1. Collect all `env_var` nodes.
2. For each env_var, check existing edges:
   - Find edges where `target == env_var.id` and `type in (writes, configures)` -- these are writers.
   - Find edges where `source == env_var.id` and `type in (reads, depends_on)` -- these are readers.
     OR edges where `target == env_var.id` and type is `reads` from a different direction.
   - Actually: look at all edges referencing the env_var node (both as source and target).
     Writers are nodes with edges `* --[writes/configures]--> env_var`.
     Readers are nodes with edges `env_var --[reads/configures]--> *` OR `* --[reads/depends_on]--> env_var`.
3. If both writer(s) and reader(s) exist, create contract.
4. Contract ID: `contract:config:{env_var_label}`.

##### 5. Sub-function: `_infer_data_contracts`

**Signature:**
```python
def _infer_data_contracts(result: ScanResult) -> None:
    """Infer data contracts from database_table nodes with multiple accessors.

    When a database_table node has edges from multiple files/services
    (reads/writes), infer a data contract. The table 'owner' (the node
    that writes to it) is the producer; readers are consumers.
    """
```

**Algorithm:**
1. Collect all `database_table` nodes.
2. For each table, check existing edges:
   - Writers: nodes with `* --[writes]--> table`.
   - Readers: nodes with `* --[reads]--> table`.
3. If at least one writer AND one reader exist (and they are different nodes),
   create a data contract.
4. Contract ID: `contract:data:{table_label}`.

##### 6. Integration into `scan_project()` pipeline

**Modify `scan_project()`** (line 1167, after `_infer_inheritance_edges`):

Add one line:
```python
    # Contract inference (detects cross-component agreements)
    _infer_contract_edges(merged)
```

Insert this after line 1167 (`_infer_inheritance_edges(merged, class_registry, file_contents)`) and before `return merged`.

### Tests

#### `tests/test_contracts.py` (new file)

```python
"""Tests for cross-system contract inference in the scanner pipeline."""

from __future__ import annotations

import pytest

from codegiraffe.graph import Edge, Node
from codegiraffe.scanner import (
    ScanResult,
    _infer_api_contracts,
    _infer_event_contracts,
    _infer_config_contracts,
    _infer_data_contracts,
    _infer_contract_edges,
)
from codegiraffe.schema import EdgeType, NodeType
```

**Test class: `TestApiContractInference`**
- `test_api_contract_inferred_from_endpoint_and_external_api` -- Create endpoint `/api/users` + external_api with URL containing `/api/users`, verify contract node + edges created.
- `test_api_contract_not_inferred_for_unmatched_paths` -- Endpoint `/api/users`, external_api `/api/orders` -- no contract.
- `test_api_contract_deduplication` -- Same endpoint/external_api pair twice, only one contract created.
- `test_api_contract_multiple_consumers` -- One endpoint, two external_api nodes referencing same path.

**Test class: `TestEventContractInference`**
- `test_event_contract_inferred_from_matching_labels` -- Two event nodes with label "user.created", verify contract.
- `test_event_contract_not_inferred_for_single_event` -- Only one event node, no contract.
- `test_event_contract_identifies_publisher_via_publishes_edge` -- Event with incoming `publishes` edge is tagged as producer.

**Test class: `TestConfigContractInference`**
- `test_config_contract_inferred_from_writer_and_reader` -- env_var with writes edge from A and reads edge to B, verify contract.
- `test_config_contract_not_inferred_without_reader` -- env_var with only writer, no contract.
- `test_config_contract_not_inferred_without_writer` -- env_var with only reader, no contract.

**Test class: `TestDataContractInference`**
- `test_data_contract_inferred_from_table_writer_and_reader` -- Table with writes from A and reads from B, verify contract.
- `test_data_contract_not_inferred_for_single_accessor` -- Table with only reader or only writer, no contract.
- `test_data_contract_not_inferred_when_writer_is_reader` -- Same node writes and reads (no cross-system contract).

**Test class: `TestContractInferenceOrchestrator`**
- `test_infer_contract_edges_calls_all_four_sub_functions` -- Build a result with all four contract types, verify all detected.
- `test_infer_contract_edges_empty_result` -- Empty ScanResult, no crash, no contracts.
- `test_contract_node_metadata_structure` -- Verify contract node has required metadata: contract_type, producer, consumers, status.

**Test class: `TestContractInferenceIntegration`**
- `test_scan_project_infers_api_contracts` -- Write synthetic files with endpoint + HTTP client call, run `scan_project()`, verify contract in result.
- `test_scan_project_no_contracts_when_no_matches` -- Clean project with no matching pairs, no contracts inferred.

**Test count:** +18 tests

---

## Phase 3: MCP Tools (Depends on Phase 1)

### Rationale
Three new tools provide contract management capabilities. The query logic lives
in `query.py`; the MCP tool wrappers live in `server.py`. This follows the
existing pattern where `compute_blast_radius` is in `query.py` and
`codegiraffe_blast_radius` in `server.py`.

### Files to Modify

#### `src/codegiraffe/query.py`

##### 1. New function: `get_contracts`

**Insert after:** `generate_impact_summary` (line 760)

**Signature:**
```python
def get_contracts(
    graph: ArchGraph,
    contract_type: str | None = None,
    status: str | None = None,
    node_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return all contract nodes with their producer/consumer relationships.

    Parameters
    ----------
    graph:
        The architecture graph.
    contract_type:
        Filter by "api", "event", "data", "config". None returns all.
    status:
        Filter by "active", "deprecated", "broken". None returns all.
    node_id:
        Only return contracts involving this node (as producer or consumer).

    Returns
    -------
    list[dict]
        Each dict contains: id, label, contract_type, status, producer,
        consumers (list of node_ids), producer_file_path, consumer_file_paths.
    """
```

**Algorithm:**
1. Get all nodes where `type == NodeType.CONTRACT`.
2. Filter by `contract_type` from `node.metadata["contract_type"]` if provided.
3. Filter by `status` from `node.metadata["status"]` if provided.
4. Filter by `node_id`: keep if `node_id` matches `metadata["producer"]` or is
   in `metadata["consumers"]`.
5. For each contract, resolve producer and consumer node details (file_path, label).
6. Return list of enriched dicts.

##### 2. New function: `validate_contracts`

**Insert after:** `get_contracts`

**Signature:**
```python
def validate_contracts(graph: ArchGraph) -> dict[str, Any]:
    """Validate all contracts in the graph.

    Checks:
    - Producer node exists in graph
    - All consumer nodes exist in graph
    - Contracts where producer is missing -> status "broken"
    - Contracts where all consumers are missing -> status "orphaned"
    - Deprecated contracts with active consumers -> flagged

    Returns
    -------
    dict
        Keys: valid (list), broken (list), orphaned (list),
        deprecated_with_consumers (list), total_contracts (int).
    """
```

**Algorithm:**
1. Get all contract nodes.
2. For each contract:
   - Check if `metadata["producer"]` node ID exists in `graph.graph`.
   - Check if each node ID in `metadata["consumers"]` exists in `graph.graph`.
   - Classify as valid/broken/orphaned based on results.
   - If `metadata["status"] == "deprecated"` and consumers still exist, flag.
3. Return structured result.

#### `src/codegiraffe/server.py`

##### 1. New tool: `codegiraffe_contracts`

**Insert after:** `codegiraffe_cycles` tool (around line 545, before `_format_risk_report`)

**Signature:**
```python
@mcp.tool()
def codegiraffe_contracts(
    project_path: str,
    contract_type: str | None = None,
    status: str | None = None,
    node_id: str | None = None,
) -> str:
    """List all contracts in the architecture graph.

    Contracts represent agreements between components -- API contracts,
    event contracts, data contracts, and configuration contracts.

    Filter by contract_type ("api", "event", "data", "config"),
    status ("active", "deprecated", "broken"), or node_id (show contracts
    involving this node as producer or consumer).

    Returns a markdown-formatted contract inventory.
    """
```

**Pattern to follow:** `codegiraffe_blast_radius` (line 407) -- calls
`_ensure_graph`, delegates to query function, formats result, catches exceptions.

**Implementation:** Calls `get_contracts()` from `query.py`, formats as markdown
table/list. If no contracts found, returns helpful message explaining
`codegiraffe_add_contract`.

**Import to add:** `from codegiraffe.query import get_contracts, validate_contracts`
(add alongside existing imports from `query.py`).

##### 2. New tool: `codegiraffe_validate_contracts`

**Insert after:** `codegiraffe_contracts`

**Signature:**
```python
@mcp.tool()
def codegiraffe_validate_contracts(project_path: str) -> str:
    """Validate all contracts in the architecture graph.

    Checks that producer and consumer nodes still exist. Reports broken
    contracts (missing producer), orphaned contracts (all consumers gone),
    and deprecated contracts that still have active consumers.

    Returns a markdown validation report with recommendations.
    """
```

**Implementation:** Calls `validate_contracts()` from `query.py`, formats as
markdown with sections for valid/broken/orphaned/deprecated. Includes
recommendations for fixing broken contracts.

##### 3. New tool: `codegiraffe_add_contract`

**Insert after:** `codegiraffe_validate_contracts`

**Signature:**
```python
@mcp.tool()
def codegiraffe_add_contract(
    project_path: str,
    name: str,
    contract_type: str,
    producer: str,
    consumers: str,
    version: str = "",
    metadata: str = "{}",
) -> str:
    """Add a manual contract between architectural components.

    Creates a contract node with produces/consumes_contract edges.
    The contract is marked manual=True so it survives automated rescans.

    Parameters
    ----------
    name:
        Contract name (e.g., "api/users", "user.created.event").
    contract_type:
        One of "api", "event", "data", "config".
    producer:
        Node ID of the producing component.
    consumers:
        Comma-separated list of consumer node IDs.
    version:
        Optional version string for the contract.
    metadata:
        JSON string of additional metadata key/value pairs.
    """
```

**Pattern to follow:** `codegiraffe_add_relation` (line 196) -- parses metadata
JSON, auto-creates nodes if missing (but here we just warn), creates edges,
persists with `_storage.save()`.

**Implementation:**
1. Parse `consumers` string: `consumer_list = [c.strip() for c in consumers.split(",") if c.strip()]`
2. Validate `contract_type` is one of `"api"`, `"event"`, `"data"`, `"config"`.
3. Create contract node: `id="contract:{name}"`, `type=NodeType.CONTRACT`, `manual=True`.
4. Set metadata: `contract_type`, `producer`, `consumers`, `version`, `status="active"`.
5. Check if producer exists in graph -- warn if not, but still create.
6. Check if consumer nodes exist -- warn if any missing, but still create.
7. Create `produces` edge from `producer` to contract node.
8. Create `consumes_contract` edge from each consumer to contract node.
9. Persist graph.

##### 4. Update section comment

Add section header before the new tools:
```python
# ---------------------------------------------------------------------------
# Cross-system contract tools (v0.8.0)
# ---------------------------------------------------------------------------
```

### Tests

#### `tests/test_contracts.py` (append to new file from Phase 2)

**Test class: `TestGetContracts`**
- `test_get_contracts_returns_all` -- Build graph with 3 contracts, verify all returned.
- `test_get_contracts_filter_by_type` -- Filter by "api", only API contracts returned.
- `test_get_contracts_filter_by_status` -- Filter by "active".
- `test_get_contracts_filter_by_node_id` -- Filter by producer node ID.
- `test_get_contracts_empty_graph` -- No contract nodes, returns empty list.

**Test class: `TestValidateContracts`**
- `test_validate_all_valid` -- All producers and consumers present, all valid.
- `test_validate_broken_missing_producer` -- Producer node removed, contract flagged broken.
- `test_validate_orphaned_all_consumers_missing` -- All consumer nodes removed, flagged orphaned.
- `test_validate_deprecated_with_active_consumers` -- Deprecated contract still has consumers.
- `test_validate_empty_graph` -- No contracts, returns zeros.

#### `tests/test_server_integration.py` (modify existing)

**Test class: `TestContractTools` (new class)**
- `test_contracts_tool_returns_markdown` -- Init project, add contract, verify markdown output.
- `test_contracts_tool_no_contracts_helpful_message` -- No contracts, returns help text.
- `test_validate_contracts_tool_returns_report` -- Add contracts, remove a node, validate.
- `test_add_contract_tool_creates_contract` -- Add contract via tool, verify in graph.
- `test_add_contract_tool_warns_missing_producer` -- Producer doesn't exist, still creates.
- `test_add_contract_tool_invalid_type` -- Bad contract_type, returns error.

**Test count:** +16 tests

---

## Phase 4: Enhanced Blast Radius (Depends on Phase 2)

### Rationale
When computing blast radius for a node that produces a contract, all consumers
should be flagged with "critical" severity regardless of hop distance. This
is the key value proposition: "what breaks if I remove this endpoint that
others depend on?"

### Files to Modify

#### `src/codegiraffe/query.py`

##### 1. Modify: `compute_blast_radius`

**Location:** Line 481

**Changes:**
After the downstream computation (line 555) and before the upstream computation
(line 558), add contract-aware impact detection:

```python
    # --- Contract impact ---
    contract_impact: list[dict[str, Any]] = []
    contract_impact = _compute_contract_impact(graph, node_id)

    # Merge contract consumers into downstream with critical severity
    downstream_ids = {item["node_id"] for item in downstream}
    for ci in contract_impact:
        if ci["node_id"] not in downstream_ids:
            downstream.append(ci)
            downstream_ids.add(ci["node_id"])
```

Add `contract_impact` to the result dict:
```python
    result["contract_impact"] = contract_impact
```

##### 2. New helper: `_compute_contract_impact`

**Insert before:** `compute_blast_radius`

**Signature:**
```python
def _compute_contract_impact(
    graph: ArchGraph, node_id: str
) -> list[dict[str, Any]]:
    """Find consumers of contracts where *node_id* is the producer.

    When a node is a contract producer, all consumers are at critical
    risk because they depend on the contract being honored.

    Also handles the case where *node_id* IS a contract node -- returns
    both the producer and all consumers.

    Returns
    -------
    list[dict]
        Each dict has: node_id, label, type, severity ("critical"),
        contract_name, contract_type, file_path.
    """
```

**Algorithm:**
1. Find all contract nodes in the graph.
2. For each contract:
   - If `metadata["producer"] == node_id`: collect all consumer node IDs, create
     entries with `severity="critical"`.
   - If `node_id` is in `metadata["consumers"]`: the producer is impacted too.
   - If `node_id` is the contract node itself: both producer and all consumers.
3. Resolve node details (label, type, file_path) from graph.
4. Return list.

##### 3. Modify: `generate_impact_summary`

**Location:** Line 623

**Changes:** After the "Indirect Impact" section (line 692) and before
"Upstream Dependencies" (line 695), add a contract impact section:

```python
    # --- Contract Impact ---
    contract_impact = blast_radius.get("contract_impact", [])
    if contract_impact:
        lines.append(f"### Contract Impact ({len(contract_impact)})")
        lines.append("")
        lines.append("These nodes depend on contracts produced by this component.")
        lines.append("Breaking this node may violate these contracts.")
        lines.append("")
        for item in contract_impact:
            contract_name = item.get("contract_name", "unknown")
            contract_type = item.get("contract_type", "unknown")
            fp = f" [{item['file_path']}]" if item.get("file_path") else ""
            lines.append(
                f"- **{item['label']}** ({item['type']}) -- "
                f"CRITICAL via {contract_type} contract `{contract_name}`{fp}"
            )
        lines.append("")
```

Also add a contract-specific recommendation:
```python
    if contract_impact:
        contract_count = len(contract_impact)
        recommendations.append(
            f"CRITICAL: {contract_count} node(s) depend on contracts produced by "
            f"this component. Validate contract compatibility before making changes."
        )
```

##### 4. Modify: `_compute_severity`

No change needed. Contract consumers get severity via the new
`_compute_contract_impact` function, which hard-codes `"critical"` severity.

### Tests

#### `tests/test_blast_radius.py` (modify existing)

**New fixture: `contract_graph`**
```python
@pytest.fixture
def contract_graph():
    """Graph with contract relationships:
    endpoint:GET /api/users --[produces]--> contract:api:/api/users
    ext_api:users-client --[consumes_contract]--> contract:api:/api/users
    """
```

**Test class: `TestBlastRadiusContracts` (new class)**
- `test_blast_radius_producer_shows_contract_impact` -- Blast radius for endpoint that produces a contract, verify consumer appears with "critical" severity.
- `test_blast_radius_contract_node_shows_both_sides` -- Blast radius for the contract node itself.
- `test_blast_radius_no_contracts_unchanged` -- Regular node with no contracts, verify output unchanged from v0.7.0 behavior.
- `test_impact_summary_includes_contract_section` -- `generate_impact_summary` includes "Contract Impact" heading.
- `test_impact_summary_contract_recommendation` -- Recommendations section includes CRITICAL warning.

**Test count:** +5 tests

---

## Phase 5: Dashboard Styling (Parallel with Phases 3-4)

### Rationale
Contracts should be visually distinct in the dashboard. This phase only touches
`dashboard.py` and its test file. The pattern is pure string additions to the
embedded HTML/JS/CSS template.

### Files to Modify

#### `src/codegiraffe/dashboard.py`

##### 1. Add contract color to `TYPE_COLORS` dict

**Location:** Line 278-282 (JS object in DASHBOARD_HTML)

**Add:**
```javascript
contract: '#8E44AD'
```

(Purple/violet -- `#8E44AD` is Wisteria from the flat UI color palette, distinct
from the existing `#9B59B6` used for `frontend_component`.)

##### 2. Add contract shape to `TYPE_SHAPES` dict

**Location:** Line 284-287 (JS object)

**Add:**
```javascript
contract: 'hexagon'
```

(Hexagonal shape for contract nodes, visually distinct. Note: `worker` also uses
`hexagon`, but they serve different purposes and have different colors. If
collision is a concern, use `'star'` instead, but hexagon is the spec
requirement.)

##### 3. Add Cytoscape edge styles for contract edge types

**Location:** Lines 394-432 (Cytoscape style declarations for edge types)

**Add new style blocks after the `contains` edge style (line 432):**

```javascript
          // Contract edges (v0.8.0)
          {
            selector: 'edge[type = "produces"]',
            style: {
              'line-color': '#8E44AD',
              'target-arrow-color': '#8E44AD',
              'width': 3
            }
          },
          {
            selector: 'edge[type = "consumes_contract"]',
            style: {
              'line-color': '#8E44AD',
              'target-arrow-color': '#8E44AD',
              'line-style': 'dashed'
            }
          },
          {
            selector: 'edge[type = "validates"]',
            style: {
              'line-color': '#27AE60',
              'target-arrow-color': '#27AE60',
              'line-style': 'dotted'
            }
          },
          {
            selector: 'edge[type = "violates"]',
            style: {
              'line-color': '#E74C3C',
              'target-arrow-color': '#E74C3C',
              'width': 3
            }
          },
```

##### 4. Add edge types to legend `edgeStyles` dict

**Location:** Lines 641-644 (JS edgeStyles object in `buildLegend`)

**Add:**
```javascript
produces: { color: '#8E44AD', style: '' },
consumes_contract: { color: '#8E44AD', style: 'dashed' },
validates: { color: '#27AE60', style: 'dotted' },
violates: { color: '#E74C3C', style: '' },
```

#### `src/codegiraffe/export.py`

##### 5. Add contract shape to Mermaid `_MERMAID_SHAPES` dict

**Location:** Line 11-23

**Add:**
```python
NodeType.CONTRACT: ("{{", "}}"),  # hexagon
```

(Mermaid `{{ }}` renders a hexagonal node shape.)

### Tests

#### `tests/test_dashboard.py` (modify existing)

**Add to existing test class (or new class `TestContractDashboardStyles`):**

- `test_contract_color_in_type_colors` -- Assert `#8E44AD` appears in DASHBOARD_HTML.
- `test_contract_shape_in_type_shapes` -- Assert `contract: 'hexagon'` or similar appears.
- `test_produces_edge_style_defined` -- Assert `produces` edge selector in HTML.
- `test_consumes_contract_edge_style_defined` -- Assert `consumes_contract` edge selector.
- `test_violates_edge_style_red` -- Assert `#E74C3C` associated with violates.

#### `tests/test_export.py` (modify existing)

- `test_mermaid_contract_hexagon_shape` -- Build GraphData with a contract node, export to Mermaid, verify hexagon syntax `{{ }}`.

**Test count:** +6 tests

---

## Phase 6: Polish (Last)

### Rationale
Version bump, documentation updates, and final verification. No new features.

### Files to Modify

#### `pyproject.toml`
- Bump `version` from `"0.7.0"` to `"0.8.0"`.

#### `CLAUDE.md`
- Update `Version` line to `0.8.0`.
- Update tool count from 22 to 25.
- Update test count target.
- Add `CONTRACT` to NodeType notes, `PRODUCES`, `CONSUMES_CONTRACT`,
  `VALIDATES`, `VIOLATES` to EdgeType notes.
- Add `Recent Changes` entry for v0.8.0.
- Update scanner description to mention contract inference.

#### `README.md`
- Add contract tools to tool list.
- Add contract feature description.
- Update version references.

### Verification

Run the full test suite:
```bash
source .venv/bin/activate && python -m pytest tests/ -v
```

- All 754 existing tests must pass unchanged.
- 40+ new tests must pass.
- Total test count: 794+.

### Test count: +0 (no new tests in this phase)

---

## Summary

| Phase | Files Modified | New Functions/Methods | Tests Added |
|-------|---------------|----------------------|-------------|
| 1. Schema | schema.py | 0 (enum values only) | 5 |
| 2. Contract Inference | scanner.py | 5 (_infer_contract_edges + 4 sub-functions) | 18 |
| 3. MCP Tools | query.py, server.py | 5 (get_contracts, validate_contracts, 3 tools) | 16 |
| 4. Blast Radius | query.py | 1 (_compute_contract_impact) + 2 modifications | 5 |
| 5. Dashboard | dashboard.py, export.py | 0 (template/dict additions) | 6 |
| 6. Polish | pyproject.toml, CLAUDE.md, README.md | 0 | 0 |
| **Total** | **7 files** | **11 functions** | **50 tests** |

### Dependency Graph

```
Phase 1 (Schema)
  |
  +---> Phase 2 (Inference) ---> Phase 4 (Blast Radius)
  |
  +---> Phase 3 (MCP Tools) ---> Phase 6 (Polish)
  |
  +---> Phase 5 (Dashboard) -----^
```

Phases 2, 3, and 5 can proceed in parallel once Phase 1 is complete.
Phase 4 depends on Phase 2 (needs contract nodes to exist).
Phase 6 is the final merge/polish after all feature phases.

### New MCP Tools (3 new, 25 total)

| Tool | Description |
|------|-------------|
| `codegiraffe_contracts` | List/filter contracts in the graph |
| `codegiraffe_validate_contracts` | Validate contract integrity |
| `codegiraffe_add_contract` | Manually create a contract |

### New Test Files

| File | Description |
|------|-------------|
| `tests/test_contracts.py` | Contract inference + query tests (34 tests) |

### Modified Test Files

| File | Tests Added |
|------|-------------|
| `tests/test_schema.py` | 5 |
| `tests/test_blast_radius.py` | 5 |
| `tests/test_dashboard.py` | 5 |
| `tests/test_export.py` | 1 |
| `tests/test_server_integration.py` | 6 (but counted in Phase 3 total, which uses test_contracts.py for unit tests) |

### Risk Assessment

**Low risk:**
- Phase 1 (enum additions are purely additive)
- Phase 5 (CSS/JS template changes are isolated)
- Phase 6 (documentation only)

**Medium risk:**
- Phase 2 (new inference logic must not create false-positive contracts)
  - Mitigation: strict matching rules, deduplication, extensive test coverage
- Phase 3 (new MCP tools must follow existing patterns exactly)
  - Mitigation: copy-paste from `codegiraffe_blast_radius` pattern

**Highest risk:**
- Phase 4 (modifying existing `compute_blast_radius` could break existing tests)
  - Mitigation: contract impact is additive, only appended when contracts exist.
    Existing tests have no contracts, so `contract_impact` list will be empty.
    `generate_impact_summary` only emits the contract section when non-empty.
    All existing behavior is preserved.

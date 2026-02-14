# Code Giraffe v0.7.0 — Actionable Intelligence: Implementation Plan

## 1. Architecture Overview

v0.7.0 adds an intelligence layer on top of the existing architecture graph. The change flows bottom-up through three files:

```
graph.py (traversal primitives)
    |
    v
query.py (blast radius + impact summary logic)
    |
    v
server.py (3 new MCP tools + 2 enhanced tools)
```

**No new files are created.** All changes extend existing modules. No new dependencies are required — everything builds on NetworkX >= 3.0 which is already installed.

### Component Map

| Component | File | What Changes |
|-----------|------|-------------|
| `ArchGraph` | `src/codegiraffe/graph.py` | +5 new methods (thin NetworkX wrappers) |
| Query engine | `src/codegiraffe/query.py` | +2 new functions (`compute_blast_radius`, `generate_impact_summary`) |
| MCP tools | `src/codegiraffe/server.py` | +3 new tools, 2 enhanced tools |
| Tests | `tests/test_graph.py` | +15 new test classes for traversal methods |
| Tests | `tests/test_blast_radius.py` | +25 new tests (new file) |
| Tests | `tests/test_server_integration.py` | +10 new tests for MCP tools |

### Backward Compatibility Contract

All changes are **additive only**:
- New methods on `ArchGraph` do not modify existing methods
- New functions in `query.py` do not modify existing functions
- New parameters on `codegiraffe_context_for` and `codegiraffe_hotspots` default to current behavior
- Existing 698 tests must pass unchanged

---

## 2. Phase 1: ArchGraph Traversal Extensions (`graph.py`)

### Overview

Add 5 new methods to the `ArchGraph` class (lines 46-200 in `src/codegiraffe/graph.py`). These are thin wrappers around NetworkX algorithms that provide a clean API for the query layer. All methods follow the same error-handling pattern: if a node_id is not present in the graph, return an empty result (never raise).

### 2.1 `get_all_descendants(node_id: str) -> set[str]`

**Purpose:** Find all transitively reachable downstream nodes from a given node.

**Implementation:**
```python
def get_all_descendants(self, node_id: str) -> set[str]:
    """Return all nodes transitively reachable from *node_id* via outgoing edges."""
    if node_id not in self._graph:
        return set()
    return nx.descendants(self._graph, node_id)
```

**Edge cases:**
- Node not in graph: return `set()`
- Node with no outgoing edges: return `set()`
- Cyclic graph: `nx.descendants()` handles cycles correctly (BFS-based, tracks visited)

### 2.2 `get_all_ancestors(node_id: str) -> set[str]`

**Purpose:** Find all upstream nodes that can transitively reach the given node.

**Implementation:**
```python
def get_all_ancestors(self, node_id: str) -> set[str]:
    """Return all nodes that can transitively reach *node_id* via outgoing edges."""
    if node_id not in self._graph:
        return set()
    return nx.ancestors(self._graph, node_id)
```

**Edge cases:** Same as `get_all_descendants`.

### 2.3 `find_paths(source: str, target: str, max_depth: int = 10) -> list[list[str]]`

**Purpose:** Find all simple paths between two nodes, useful for understanding how changes propagate.

**Implementation:**
```python
def find_paths(self, source: str, target: str, max_depth: int = 10) -> list[list[str]]:
    """Return all simple paths from *source* to *target* up to *max_depth* hops."""
    if source not in self._graph or target not in self._graph:
        return []
    return list(nx.all_simple_paths(self._graph, source, target, cutoff=max_depth))
```

**Edge cases:**
- Either node missing: return `[]`
- No path exists: return `[]`
- Source equals target: `nx.all_simple_paths` returns `[]` (no trivial self-path)
- `max_depth` prevents combinatorial explosion on dense graphs

### 2.4 `detect_cycles(max_cycles: int = 100) -> list[list[str]]`

**Purpose:** Find circular dependencies in the architecture graph.

**Implementation:**
```python
def detect_cycles(self, max_cycles: int = 100) -> list[list[str]]:
    """Return up to *max_cycles* simple cycles (circular dependencies).

    Cycles are sorted by length (shortest first) since shorter cycles
    are typically more severe architectural issues.
    """
    cycles: list[list[str]] = []
    for cycle in nx.simple_cycles(self._graph):
        cycles.append(cycle)
        if len(cycles) >= max_cycles:
            break
    cycles.sort(key=len)
    return cycles
```

**Performance note:** `nx.simple_cycles()` uses Johnson's algorithm. For very large graphs this can be expensive, but the `max_cycles` cap prevents runaway computation. The spec requires max 100 by default; the MCP tool passes a user-configurable cap (default 20).

**Edge cases:**
- No cycles: return `[]`
- Self-loops: included as single-element cycles `[node_id]`
- Empty graph: return `[]`

### 2.5 `get_betweenness_centrality() -> dict[str, float]`

**Purpose:** Identify bottleneck nodes — nodes that sit on many shortest paths.

**Implementation:**
```python
def get_betweenness_centrality(self) -> dict[str, float]:
    """Return betweenness centrality for all nodes.

    Betweenness centrality measures how often a node appears on shortest
    paths between other nodes -- high values indicate architectural
    bottlenecks.
    """
    if len(self._graph) == 0:
        return {}
    return nx.betweenness_centrality(self._graph)
```

**Edge cases:**
- Empty graph: return `{}`
- Single node: returns `{node_id: 0.0}`

### Insertion Point

All 5 methods are inserted after the existing `get_hotspots()` method (line 175 in `graph.py`), before the `to_data()` method. This keeps the traversal/query methods grouped together.

### Testing (Phase 1)

Add to `tests/test_graph.py`:

| Test Class | Tests | Description |
|-----------|-------|-------------|
| `TestGetAllDescendants` | 4 | Happy path, missing node, no descendants, cyclic graph |
| `TestGetAllAncestors` | 4 | Happy path, missing node, no ancestors, cyclic graph |
| `TestFindPaths` | 5 | Happy path, no path, missing node, max_depth, multiple paths |
| `TestDetectCycles` | 4 | No cycles, simple cycle, multiple cycles, max_cycles cap |
| `TestGetBetweennessCentrality` | 3 | Happy path, empty graph, bottleneck identification |

**Graph topologies for tests:**

```python
# Linear chain: A -> B -> C -> D
# Used for: descendants, ancestors, find_paths

# Diamond: A -> B, A -> C, B -> D, C -> D
# Used for: multiple paths, centrality

# Cycle: A -> B -> C -> A
# Used for: detect_cycles, descendants with cycles

# Isolated: A (no edges), B (no edges)
# Used for: empty results

# Empty graph: no nodes
# Used for: empty results
```

The `sample_graph` fixture from `conftest.py` provides a real-world-like topology that covers most needs. Build additional topologies inline in test methods for specific shapes.

---

## 3. Phase 2: Blast Radius + Impact Summary (`query.py`)

### 3.1 `compute_blast_radius()`

**Location:** Add to `src/codegiraffe/query.py`, after `context_for_task()` (around line 310).

**Signature:**
```python
def compute_blast_radius(
    graph: ArchGraph,
    node_id: str,
    include_upstream: bool = False,
    max_depth: int | None = None,
) -> dict[str, Any]:
```

**Algorithm:**

1. **Validate node exists.** If `node_id` not in graph, raise `ValueError` with fuzzy suggestions (reuse `_fuzzy_suggestions()` from query.py line ~25).

2. **Compute downstream impact:**
   ```python
   all_descendants = graph.get_all_descendants(node_id)
   ```

3. **Apply max_depth filter** (if specified): For each descendant, compute `nx.shortest_path_length(graph.graph, node_id, descendant)`. Discard descendants beyond `max_depth`.

4. **Compute shortest path and severity for each impacted node:**
   ```python
   for desc_id in all_descendants:
       distance = nx.shortest_path_length(graph.graph, node_id, desc_id)
       path = nx.shortest_path(graph.graph, node_id, desc_id)
       severity = _compute_severity(distance)  # "direct", "transitive", "indirect"
   ```

5. **Optionally compute upstream impact** (if `include_upstream=True`):
   ```python
   all_ancestors = graph.get_all_ancestors(node_id)
   # Same distance/severity computation, but reversed direction
   ```

6. **Detect cycles involving this node:**
   ```python
   all_cycles = graph.detect_cycles(max_cycles=50)
   relevant_cycles = [c for c in all_cycles if node_id in c]
   ```

7. **Compute critical paths** (hotspots within impact zone):
   ```python
   # Build subgraph of impacted nodes
   impact_ids = all_descendants | {node_id}
   sub = graph.graph.subgraph(impact_ids)
   betweenness = nx.betweenness_centrality(sub)
   critical = sorted(betweenness.items(), key=lambda x: x[1], reverse=True)[:5]
   ```

**Return structure:**
```python
{
    "target_node": {
        "id": node_id,
        "label": node.label,
        "type": node.type,
        "file_path": node.file_path,
    },
    "downstream": [
        {
            "node_id": "...",
            "label": "...",
            "type": "...",
            "distance": 1,
            "severity": "direct",
            "path": ["source", "...", "target"],
            "file_path": "...",
        },
        # ...sorted by distance ascending
    ],
    "upstream": [  # only if include_upstream=True
        # same structure
    ],
    "total_impact_count": 15,
    "cycles": [
        ["A", "B", "C", "A"],  # cycle paths
    ],
    "critical_paths": [
        {"node_id": "...", "label": "...", "centrality": 0.85},
        # ...top 5 by betweenness in impact subgraph
    ],
}
```

**Helper function:**
```python
def _compute_severity(distance: int) -> str:
    """Map distance to severity tier."""
    if distance == 1:
        return "direct"
    elif distance <= 3:
        return "transitive"
    else:
        return "indirect"
```

**Performance considerations:**
- `nx.shortest_path_length` is O(V+E) per call. For N descendants, this is O(N*(V+E)). For typical architecture graphs (< 1000 nodes), this is fast.
- If performance becomes an issue, use `nx.single_source_shortest_path_length(graph.graph, node_id)` once to get all distances in a single BFS — O(V+E) total. **Use this approach from the start:**

```python
# Efficient: single BFS for all distances
distances = dict(nx.single_source_shortest_path_length(graph.graph, node_id))
paths = dict(nx.single_source_shortest_path(graph.graph, node_id))

downstream = []
for desc_id in sorted(all_descendants):
    dist = distances.get(desc_id)
    if dist is None:
        continue
    if max_depth is not None and dist > max_depth:
        continue
    desc_node = graph.graph.nodes[desc_id].get("node")
    if desc_node is None:
        continue
    downstream.append({
        "node_id": desc_id,
        "label": desc_node.label,
        "type": desc_node.type,
        "distance": dist,
        "severity": _compute_severity(dist),
        "path": paths.get(desc_id, []),
        "file_path": desc_node.file_path,
    })

downstream.sort(key=lambda x: (x["distance"], x["node_id"]))
```

For upstream, use `nx.single_source_shortest_path_length()` on the reversed graph:
```python
if include_upstream:
    rev = graph.graph.reverse()
    up_distances = dict(nx.single_source_shortest_path_length(rev, node_id))
    up_paths = dict(nx.single_source_shortest_path(rev, node_id))
    # Build upstream list from ancestors using up_distances/up_paths
```

### 3.2 `generate_impact_summary()`

**Location:** Add immediately after `compute_blast_radius()` in `query.py`.

**Signature:**
```python
def generate_impact_summary(
    blast_radius: dict[str, Any],
    graph: ArchGraph,
) -> str:
```

**Output format (markdown string):**

```markdown
## Impact Analysis: {node_label}

**Total blast radius:** {N} nodes affected

### Direct Dependencies ({count})
- **{node_label}** ({node_type}) -- via {edge_type} edge [{file_path}]
...

### Transitive Impact ({count})
- **{node_label}** ({node_type}) -- {distance} hops via {path_summary} [{file_path}]
...

### Indirect Impact ({count})
- **{node_label}** ({node_type}) -- {distance} hops [{file_path}]
...

### Upstream Dependencies ({count})
- **{node_label}** ({node_type}) -- {distance} hops upstream [{file_path}]
...

### Circular Dependencies
- {cycle_path} (e.g., "A -> B -> C -> A")
...

### Hotspots in Impact Zone
- **{node_label}** (centrality: {score:.4f}) -- most-connected node in impact zone
...

### Recommendations
- Consider testing **{X}** -- it is {distance} hops away and has {N} dependents
- Warning: circular dependency detected: A -> B -> C -> A
```

**Implementation details:**

1. **Group downstream by severity:**
   ```python
   direct = [n for n in blast_radius["downstream"] if n["severity"] == "direct"]
   transitive = [n for n in blast_radius["downstream"] if n["severity"] == "transitive"]
   indirect = [n for n in blast_radius["downstream"] if n["severity"] == "indirect"]
   ```

2. **Format edge type for direct dependencies:** For direct nodes (distance=1), look up the actual edge from the graph to report the edge type:
   ```python
   target_id = blast_radius["target_node"]["id"]
   for item in direct:
       edge_data = graph.graph.edges.get((target_id, item["node_id"]), {})
       edge_obj = edge_data.get("edge")
       edge_type = edge_obj.type if edge_obj else "unknown"
   ```

3. **Path summary for transitive nodes:** Convert path list to arrow-separated string:
   ```python
   path_summary = " -> ".join(item["path"])
   ```

4. **Recommendations generation:**
   - For each hotspot in the impact zone, generate a testing recommendation
   - For each cycle, generate a warning
   - Recommend testing the most-distant direct dependency first (highest blast radius amplification)

5. **Omit empty sections:** If there are no cycles, omit the "Circular Dependencies" section entirely. Same for upstream (if not requested) and for each severity tier with zero items.

### Testing (Phase 2)

Create new file `tests/test_blast_radius.py`:

| Test Class | Tests | Description |
|-----------|-------|-------------|
| `TestComputeBlastRadius` | 8 | Linear chain, tree, diamond, cyclic, isolated node, missing node (ValueError), with/without upstream, max_depth |
| `TestComputeSeverity` | 3 | Distance 1 (direct), distance 2-3 (transitive), distance >3 (indirect) |
| `TestGenerateImpactSummary` | 6 | Has all sections, omits empty sections, correct counts, formats edge types, formats paths, recommendations |
| `TestBlastRadiusEdgeCases` | 5 | Empty graph, single node, self-loop, very deep chain, node with only upstream |

**Test topologies for blast radius:**

```python
@pytest.fixture
def linear_chain_graph():
    """A -> B -> C -> D -> E (5 nodes, 4 edges)"""
    graph = ArchGraph()
    for i, name in enumerate(["A", "B", "C", "D", "E"]):
        graph.add_node(Node(id=f"module:{name}", type=NodeType.MODULE, label=name, file_path=f"{name}.py"))
    for s, t in [("A", "B"), ("B", "C"), ("C", "D"), ("D", "E")]:
        graph.add_edge(Edge(source=f"module:{s}", target=f"module:{t}", type=EdgeType.IMPORTS))
    return graph

@pytest.fixture
def diamond_graph():
    """A -> B, A -> C, B -> D, C -> D (4 nodes, 4 edges)"""
    graph = ArchGraph()
    for name in ["A", "B", "C", "D"]:
        graph.add_node(Node(id=f"module:{name}", type=NodeType.MODULE, label=name))
    for s, t in [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")]:
        graph.add_edge(Edge(source=f"module:{s}", target=f"module:{t}", type=EdgeType.IMPORTS))
    return graph

@pytest.fixture
def cyclic_graph():
    """A -> B -> C -> A, plus C -> D (4 nodes, 4 edges, 1 cycle)"""
    graph = ArchGraph()
    for name in ["A", "B", "C", "D"]:
        graph.add_node(Node(id=f"module:{name}", type=NodeType.MODULE, label=name))
    for s, t in [("A", "B"), ("B", "C"), ("C", "A"), ("C", "D")]:
        graph.add_edge(Edge(source=f"module:{s}", target=f"module:{t}", type=EdgeType.IMPORTS))
    return graph
```

---

## 4. Phase 3: MCP Tools (`server.py`)

All tools follow the existing pattern in `server.py`: `@mcp.tool()` decorator, `_ensure_graph()` for loading, try/except for error handling, return `str` (JSON or markdown).

### 4.1 `codegiraffe_blast_radius` (New Tool)

**Insert after `codegiraffe_hotspots` (line ~320).**

```python
@mcp.tool()
def codegiraffe_blast_radius(
    project_path: str,
    node_id: str,
    include_upstream: bool = False,
    max_depth: int | None = None,
) -> str:
    """Analyze the blast radius of changing a specific node.

    Shows what breaks if you change this node -- downstream dependencies
    ranked by severity (direct, transitive, indirect), plus any circular
    dependencies and hotspots in the impact zone.

    Returns a human-readable markdown impact report.
    """
    try:
        graph = _ensure_graph(project_path)
        blast = compute_blast_radius(
            graph, node_id,
            include_upstream=include_upstream,
            max_depth=max_depth,
        )
        return generate_impact_summary(blast, graph)
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return f"Error computing blast radius: {exc}"
```

**Import additions to `server.py`:**
```python
from codegiraffe.query import (
    query_by_node, query_by_type, context_for_task, detect_drift,
    compute_blast_radius, generate_impact_summary,  # NEW
)
```

### 4.2 `codegiraffe_risk_assessment` (New Tool)

**Insert after `codegiraffe_blast_radius`.**

```python
@mcp.tool()
def codegiraffe_risk_assessment(
    project_path: str,
    node_ids: list[str] | None = None,
) -> str:
    """Assess architectural risk for specific nodes or the entire graph.

    Risk score per node = (degree_centrality * 0.4) + (betweenness_centrality * 0.4)
                        + (descendant_count / total_nodes * 0.2)

    If node_ids provided: assess risk for those specific nodes.
    If node_ids is None: assess the top-10 riskiest nodes in the entire graph.

    Returns a markdown report with nodes ranked by risk score.
    """
    try:
        graph = _ensure_graph(project_path)
        total_nodes = len(graph.graph)
        if total_nodes == 0:
            return "Graph is empty -- no nodes to assess."

        degree = nx.degree_centrality(graph.graph)
        betweenness = graph.get_betweenness_centrality()

        # Determine which nodes to assess
        if node_ids is not None:
            target_ids = node_ids
        else:
            target_ids = list(graph.graph.nodes)

        # Compute risk score for each node
        scored: list[dict[str, Any]] = []
        for nid in target_ids:
            if nid not in graph.graph:
                continue
            node_data = graph.graph.nodes[nid].get("node")
            if node_data is None:
                continue
            desc_count = len(graph.get_all_descendants(nid))
            risk = (
                degree.get(nid, 0.0) * 0.4
                + betweenness.get(nid, 0.0) * 0.4
                + (desc_count / total_nodes) * 0.2
            )
            scored.append({
                "node_id": nid,
                "label": node_data.label,
                "type": node_data.type,
                "risk_score": round(risk, 4),
                "degree_centrality": round(degree.get(nid, 0.0), 4),
                "betweenness_centrality": round(betweenness.get(nid, 0.0), 4),
                "blast_radius_count": desc_count,
                "file_path": node_data.file_path,
            })

        scored.sort(key=lambda x: x["risk_score"], reverse=True)

        # If no node_ids specified, take top 10
        if node_ids is None:
            scored = scored[:10]

        # Format as markdown
        return _format_risk_report(scored, total_nodes)
    except Exception as exc:
        return f"Error computing risk assessment: {exc}"
```

**Helper function `_format_risk_report`** (private, in `server.py`):
```python
def _format_risk_report(scored: list[dict], total_nodes: int) -> str:
    lines = ["## Risk Assessment Report", ""]
    lines.append(f"**Graph size:** {total_nodes} nodes")
    lines.append(f"**Nodes assessed:** {len(scored)}")
    lines.append("")

    for i, item in enumerate(scored, 1):
        lines.append(f"### {i}. {item['label']} (`{item['node_id']}`)")
        lines.append(f"- **Risk score:** {item['risk_score']}")
        lines.append(f"- **Type:** {item['type']}")
        lines.append(f"- **Degree centrality:** {item['degree_centrality']}")
        lines.append(f"- **Betweenness centrality:** {item['betweenness_centrality']}")
        lines.append(f"- **Blast radius:** {item['blast_radius_count']} downstream nodes")
        if item.get("file_path"):
            lines.append(f"- **File:** {item['file_path']}")

        # "Why this matters" description
        why = _risk_explanation(item)
        lines.append(f"- **Why this matters:** {why}")
        lines.append("")

    return "\n".join(lines)


def _risk_explanation(item: dict) -> str:
    """Generate a brief explanation of why a node is risky."""
    reasons = []
    if item["degree_centrality"] > 0.3:
        reasons.append("highly connected hub")
    if item["betweenness_centrality"] > 0.2:
        reasons.append("critical bottleneck on many paths")
    if item["blast_radius_count"] > 5:
        reasons.append(f"changes propagate to {item['blast_radius_count']} downstream nodes")
    if not reasons:
        reasons.append("moderate connectivity")
    return "; ".join(reasons)
```

### 4.3 `codegiraffe_cycles` (New Tool)

**Insert after `codegiraffe_risk_assessment`.**

```python
@mcp.tool()
def codegiraffe_cycles(project_path: str, max_cycles: int = 20) -> str:
    """Detect circular dependencies in the architecture graph.

    Returns markdown-formatted list of cycles with cycle path, edge types
    involved, severity (shorter cycles are more severe), and files involved.
    """
    try:
        graph = _ensure_graph(project_path)
        cycles = graph.detect_cycles(max_cycles=max_cycles)

        if not cycles:
            return "No circular dependencies detected."

        lines = ["## Circular Dependencies", ""]
        lines.append(f"**{len(cycles)} cycle(s) detected**")
        lines.append("")

        for i, cycle in enumerate(cycles, 1):
            # Make cycle display wrap back to start
            display_path = cycle + [cycle[0]]
            path_str = " -> ".join(display_path)
            severity = "high" if len(cycle) <= 2 else "medium" if len(cycle) <= 4 else "low"

            lines.append(f"### Cycle {i} (length {len(cycle)}, severity: {severity})")
            lines.append(f"```")
            lines.append(path_str)
            lines.append(f"```")

            # Edge types involved
            edge_types = []
            for j in range(len(cycle)):
                src = cycle[j]
                tgt = cycle[(j + 1) % len(cycle)]
                edge_data = graph.graph.edges.get((src, tgt), {})
                edge_obj = edge_data.get("edge")
                if edge_obj:
                    edge_types.append(f"{src} --[{edge_obj.type}]--> {tgt}")
            if edge_types:
                lines.append("**Edges:**")
                for et in edge_types:
                    lines.append(f"- {et}")

            # Files involved
            files = []
            for nid in cycle:
                node_data = graph.graph.nodes[nid].get("node")
                if node_data and node_data.file_path:
                    files.append(f"{nid}: {node_data.file_path}")
            if files:
                lines.append("**Files:**")
                for f in files:
                    lines.append(f"- {f}")

            lines.append("")

        return "\n".join(lines)
    except Exception as exc:
        return f"Error detecting cycles: {exc}"
```

### 4.4 Enhanced `codegiraffe_context_for` (Existing Tool)

**Current signature** (line 254 in `server.py`):
```python
def codegiraffe_context_for(project_path, task, max_nodes=20, use_embeddings=True)
```

**New signature:**
```python
def codegiraffe_context_for(
    project_path: str,
    task: str,
    max_nodes: int = 20,
    use_embeddings: bool = True,
    include_impact: bool = False,  # NEW
) -> str:
```

**Changes:**
- When `include_impact=False` (default): behavior is identical to current — returns `subgraph.model_dump_json(indent=2)`.
- When `include_impact=True`: After computing the subgraph, augment each node's metadata with:
  - `_blast_radius_count`: number of downstream descendants
  - `_risk_score`: the composite risk score

```python
@mcp.tool()
def codegiraffe_context_for(
    project_path: str,
    task: str,
    max_nodes: int = 20,
    use_embeddings: bool = True,
    include_impact: bool = False,
) -> str:
    """Get the most relevant subgraph for a natural-language task description.

    When sentence-transformers is installed and *use_embeddings* is True, uses
    embedding-based semantic similarity for scoring.  Otherwise falls back to
    keyword overlap scoring.  Returns the top-matching nodes with their
    immediate neighbors, capped at *max_nodes*.

    When *include_impact* is True, each returned node is augmented with
    blast_radius_count and risk_score metadata for impact awareness.

    Useful for scoping what parts of the architecture are relevant before
    making changes.
    """
    try:
        graph = _ensure_graph(project_path)
        subgraph = context_for_task(graph, task, max_nodes, use_embeddings=use_embeddings)

        if include_impact:
            total_nodes = len(graph.graph)
            degree = nx.degree_centrality(graph.graph)
            betweenness = graph.get_betweenness_centrality()
            for nid, node in subgraph.nodes.items():
                desc_count = len(graph.get_all_descendants(nid))
                risk = (
                    degree.get(nid, 0.0) * 0.4
                    + betweenness.get(nid, 0.0) * 0.4
                    + (desc_count / total_nodes) * 0.2
                ) if total_nodes > 0 else 0.0
                node.metadata["_blast_radius_count"] = desc_count
                node.metadata["_risk_score"] = round(risk, 4)

        return subgraph.model_dump_json(indent=2)
    except Exception as exc:
        return f"Error computing context: {exc}"
```

### 4.5 Enhanced `codegiraffe_hotspots` (Existing Tool)

**Current signature** (line 297 in `server.py`):
```python
def codegiraffe_hotspots(project_path, top_n=10)
```

**New signature:**
```python
def codegiraffe_hotspots(
    project_path: str,
    top_n: int = 10,
    metrics: str = "degree",  # NEW: "degree", "betweenness", "combined"
) -> str:
```

**Changes:**
- `metrics="degree"` (default): identical to current behavior
- `metrics="betweenness"`: rank by betweenness centrality instead
- `metrics="combined"`: weighted combination (degree * 0.5 + betweenness * 0.5)

```python
@mcp.tool()
def codegiraffe_hotspots(
    project_path: str,
    top_n: int = 10,
    metrics: str = "degree",
) -> str:
    """Find the most connected nodes (architectural hotspots) in the graph.

    Ranks nodes by centrality metrics -- highly connected nodes are likely
    architectural hotspots that deserve extra attention during changes.

    Use *metrics* to select the ranking strategy:
    - "degree": rank by degree centrality (default, current behavior)
    - "betweenness": rank by betweenness centrality (bottleneck detection)
    - "combined": weighted combination of degree (0.5) + betweenness (0.5)

    Returns a JSON array of {node_id, label, type, score} objects.
    """
    try:
        graph = _ensure_graph(project_path)

        if metrics == "betweenness":
            centrality = graph.get_betweenness_centrality()
        elif metrics == "combined":
            degree = nx.degree_centrality(graph.graph)
            betweenness = graph.get_betweenness_centrality()
            centrality = {
                nid: degree.get(nid, 0.0) * 0.5 + betweenness.get(nid, 0.0) * 0.5
                for nid in graph.graph.nodes
            }
        else:  # "degree" (default)
            centrality = nx.degree_centrality(graph.graph)

        ranked = sorted(centrality.items(), key=lambda item: item[1], reverse=True)

        result = []
        for nid, score in ranked[:top_n]:
            node_data = graph.graph.nodes[nid].get("node")
            if node_data is not None:
                result.append({
                    "node_id": node_data.id,
                    "label": node_data.label,
                    "type": node_data.type,
                    "score": round(score, 4),
                })
        return json.dumps(result, indent=2)
    except Exception as exc:
        return f"Error computing hotspots: {exc}"
```

### Tool Count Summary

After v0.7.0, Code Giraffe has **22 MCP tools** (19 existing + 3 new).

### Import Additions to `server.py`

```python
# At the top of server.py, update the query import:
from codegiraffe.query import (
    query_by_node, query_by_type, context_for_task, detect_drift,
    compute_blast_radius, generate_impact_summary,
)
import networkx as nx  # For centrality computations in enhanced tools
```

Note: `networkx` is already imported transitively through `graph.py`, but add an explicit import in `server.py` for clarity since `codegiraffe_context_for` and `codegiraffe_hotspots` now use `nx.degree_centrality()` directly.

---

## 5. Phase 4: Testing Strategy

### 5.1 Test Organization

| File | New Tests | Description |
|------|-----------|-------------|
| `tests/test_graph.py` | ~20 | Unit tests for 5 new ArchGraph methods |
| `tests/test_blast_radius.py` | ~25 | Unit tests for `compute_blast_radius()` and `generate_impact_summary()` |
| `tests/test_server_integration.py` | ~10 | Integration tests for 3 new tools + 2 enhanced |

**Total: ~55 new tests, bringing the total to 753+.**

### 5.2 Test Fixtures

Add to `conftest.py`:

```python
@pytest.fixture
def linear_graph():
    """Linear chain: A -> B -> C -> D -> E"""
    graph = ArchGraph()
    for name in "ABCDE":
        graph.add_node(Node(
            id=f"module:{name}", type=NodeType.MODULE,
            label=f"Module {name}", file_path=f"{name.lower()}.py",
        ))
    for s, t in [("A","B"), ("B","C"), ("C","D"), ("D","E")]:
        graph.add_edge(Edge(
            source=f"module:{s}", target=f"module:{t}",
            type=EdgeType.IMPORTS,
        ))
    return graph

@pytest.fixture
def diamond_graph():
    """Diamond: A -> B, A -> C, B -> D, C -> D"""
    graph = ArchGraph()
    for name in "ABCD":
        graph.add_node(Node(
            id=f"module:{name}", type=NodeType.MODULE,
            label=f"Module {name}", file_path=f"{name.lower()}.py",
        ))
    for s, t in [("A","B"), ("A","C"), ("B","D"), ("C","D")]:
        graph.add_edge(Edge(
            source=f"module:{s}", target=f"module:{t}",
            type=EdgeType.IMPORTS,
        ))
    return graph

@pytest.fixture
def cyclic_graph():
    """Cycle: A -> B -> C -> A, plus C -> D"""
    graph = ArchGraph()
    for name in "ABCD":
        graph.add_node(Node(
            id=f"module:{name}", type=NodeType.MODULE,
            label=f"Module {name}", file_path=f"{name.lower()}.py",
        ))
    for s, t in [("A","B"), ("B","C"), ("C","A"), ("C","D")]:
        graph.add_edge(Edge(
            source=f"module:{s}", target=f"module:{t}",
            type=EdgeType.IMPORTS,
        ))
    return graph
```

### 5.3 Test Categories

**graph.py unit tests** (`tests/test_graph.py`):

```python
class TestGetAllDescendants:
    def test_linear_chain(self, linear_graph):
        result = linear_graph.get_all_descendants("module:A")
        assert result == {"module:B", "module:C", "module:D", "module:E"}

    def test_missing_node(self, linear_graph):
        result = linear_graph.get_all_descendants("nonexistent")
        assert result == set()

    def test_leaf_node(self, linear_graph):
        result = linear_graph.get_all_descendants("module:E")
        assert result == set()

    def test_with_cycle(self, cyclic_graph):
        result = cyclic_graph.get_all_descendants("module:A")
        assert "module:B" in result
        assert "module:C" in result
        assert "module:D" in result

class TestGetAllAncestors:
    def test_linear_chain(self, linear_graph):
        result = linear_graph.get_all_ancestors("module:E")
        assert result == {"module:A", "module:B", "module:C", "module:D"}

    def test_missing_node(self, linear_graph):
        result = linear_graph.get_all_ancestors("nonexistent")
        assert result == set()

    def test_root_node(self, linear_graph):
        result = linear_graph.get_all_ancestors("module:A")
        assert result == set()

    def test_diamond(self, diamond_graph):
        result = diamond_graph.get_all_ancestors("module:D")
        assert result == {"module:A", "module:B", "module:C"}

class TestFindPaths:
    def test_linear_path(self, linear_graph):
        paths = linear_graph.find_paths("module:A", "module:E")
        assert len(paths) == 1
        assert paths[0] == ["module:A", "module:B", "module:C", "module:D", "module:E"]

    def test_no_path(self, linear_graph):
        paths = linear_graph.find_paths("module:E", "module:A")
        assert paths == []

    def test_missing_node(self, linear_graph):
        paths = linear_graph.find_paths("nonexistent", "module:A")
        assert paths == []

    def test_diamond_multiple_paths(self, diamond_graph):
        paths = diamond_graph.find_paths("module:A", "module:D")
        assert len(paths) == 2  # A->B->D and A->C->D

    def test_max_depth(self, linear_graph):
        paths = linear_graph.find_paths("module:A", "module:E", max_depth=2)
        assert paths == []  # Path length is 4, max_depth 2 cuts it off

class TestDetectCycles:
    def test_no_cycles(self, linear_graph):
        assert linear_graph.detect_cycles() == []

    def test_simple_cycle(self, cyclic_graph):
        cycles = cyclic_graph.detect_cycles()
        assert len(cycles) >= 1
        # At least one cycle should contain A, B, C
        cycle_sets = [set(c) for c in cycles]
        assert any({"module:A", "module:B", "module:C"} == cs for cs in cycle_sets)

    def test_max_cycles_cap(self):
        # Build graph with many cycles
        graph = ArchGraph()
        # ... (construct multi-cycle graph)
        cycles = graph.detect_cycles(max_cycles=2)
        assert len(cycles) <= 2

    def test_empty_graph(self):
        graph = ArchGraph()
        assert graph.detect_cycles() == []

class TestGetBetweennessCentrality:
    def test_linear_chain(self, linear_graph):
        bc = linear_graph.get_betweenness_centrality()
        # Middle nodes should have higher betweenness
        assert bc["module:C"] > bc["module:A"]
        assert bc["module:C"] > bc["module:E"]

    def test_empty_graph(self):
        graph = ArchGraph()
        assert graph.get_betweenness_centrality() == {}

    def test_all_nodes_present(self, diamond_graph):
        bc = diamond_graph.get_betweenness_centrality()
        assert set(bc.keys()) == {"module:A", "module:B", "module:C", "module:D"}
```

**Blast radius tests** (`tests/test_blast_radius.py`):

```python
class TestComputeBlastRadius:
    def test_linear_chain_downstream(self, linear_graph):
        result = compute_blast_radius(linear_graph, "module:A")
        assert result["total_impact_count"] == 4  # B, C, D, E
        assert all(item["severity"] in ("direct", "transitive", "indirect") for item in result["downstream"])

    def test_severity_tiers(self, linear_graph):
        result = compute_blast_radius(linear_graph, "module:A")
        severities = {item["node_id"]: item["severity"] for item in result["downstream"]}
        assert severities["module:B"] == "direct"
        assert severities["module:C"] == "transitive"
        assert severities["module:D"] == "transitive"
        assert severities["module:E"] == "indirect"

    def test_with_upstream(self, linear_graph):
        result = compute_blast_radius(linear_graph, "module:C", include_upstream=True)
        assert len(result["upstream"]) == 2  # A, B

    def test_missing_node(self, linear_graph):
        with pytest.raises(ValueError, match="not found"):
            compute_blast_radius(linear_graph, "nonexistent")

    def test_max_depth(self, linear_graph):
        result = compute_blast_radius(linear_graph, "module:A", max_depth=2)
        distances = [item["distance"] for item in result["downstream"]]
        assert all(d <= 2 for d in distances)

    def test_diamond_paths(self, diamond_graph):
        result = compute_blast_radius(diamond_graph, "module:A")
        assert result["total_impact_count"] == 3  # B, C, D

    def test_cyclic_graph(self, cyclic_graph):
        result = compute_blast_radius(cyclic_graph, "module:A")
        assert len(result["cycles"]) >= 1

    def test_leaf_node(self, linear_graph):
        result = compute_blast_radius(linear_graph, "module:E")
        assert result["total_impact_count"] == 0

class TestGenerateImpactSummary:
    def test_contains_header(self, linear_graph):
        blast = compute_blast_radius(linear_graph, "module:A")
        summary = generate_impact_summary(blast, linear_graph)
        assert "## Impact Analysis:" in summary

    def test_contains_sections(self, linear_graph):
        blast = compute_blast_radius(linear_graph, "module:A")
        summary = generate_impact_summary(blast, linear_graph)
        assert "### Direct Dependencies" in summary
        assert "Total blast radius" in summary

    def test_omits_empty_sections(self, linear_graph):
        blast = compute_blast_radius(linear_graph, "module:A")
        summary = generate_impact_summary(blast, linear_graph)
        if not blast["cycles"]:
            assert "### Circular Dependencies" not in summary

    def test_empty_blast_radius(self, linear_graph):
        blast = compute_blast_radius(linear_graph, "module:E")
        summary = generate_impact_summary(blast, linear_graph)
        assert "0 nodes affected" in summary
```

**Integration tests** (`tests/test_server_integration.py` additions):

```python
class TestBlastRadiusTool:
    def test_blast_radius_basic(self, project_dir):
        result = codegiraffe_blast_radius(str(project_dir), "module:...")
        assert "## Impact Analysis" in result

    def test_blast_radius_not_found(self, project_dir):
        result = codegiraffe_blast_radius(str(project_dir), "nonexistent")
        assert "not found" in result.lower()

class TestRiskAssessmentTool:
    def test_risk_assessment_all(self, project_dir):
        result = codegiraffe_risk_assessment(str(project_dir))
        assert "## Risk Assessment Report" in result

    def test_risk_assessment_specific(self, project_dir):
        result = codegiraffe_risk_assessment(str(project_dir), node_ids=["module:..."])
        assert "Risk score" in result

class TestCyclesTool:
    def test_no_cycles(self, project_dir):
        result = codegiraffe_cycles(str(project_dir))
        # Result depends on whether the scanned project has cycles

class TestEnhancedContextFor:
    def test_include_impact_false(self, project_dir):
        result = codegiraffe_context_for(str(project_dir), "users", include_impact=False)
        parsed = json.loads(result)
        # Should NOT have _blast_radius_count
        for node in parsed.get("nodes", {}).values():
            assert "_blast_radius_count" not in node.get("metadata", {})

    def test_include_impact_true(self, project_dir):
        result = codegiraffe_context_for(str(project_dir), "users", include_impact=True)
        parsed = json.loads(result)
        # Should have _blast_radius_count on each node
        for node in parsed.get("nodes", {}).values():
            assert "_blast_radius_count" in node.get("metadata", {})

class TestEnhancedHotspots:
    def test_degree_default(self, project_dir):
        result = codegiraffe_hotspots(str(project_dir))
        # Should work identically to current

    def test_betweenness(self, project_dir):
        result = codegiraffe_hotspots(str(project_dir), metrics="betweenness")
        parsed = json.loads(result)
        assert isinstance(parsed, list)

    def test_combined(self, project_dir):
        result = codegiraffe_hotspots(str(project_dir), metrics="combined")
        parsed = json.loads(result)
        assert isinstance(parsed, list)
```

---

## 6. Phase 5: Polish

### 6.1 Version Bump

Update version to `0.7.0` in:
- `pyproject.toml` — `version = "0.7.0"`
- `CLAUDE.md` — Active Technologies section and Recent Changes

### 6.2 Documentation Updates

Update `CLAUDE.md`:
- Add v0.7.0 to Recent Changes section
- Update tool count from 19 to 22
- Add `compute_blast_radius` and `generate_impact_summary` to Key Patterns
- Update test count

### 6.3 Dogfood Testing

Run against two real projects to validate output quality:

1. **Self-scan (CodeGiraffe itself):**
   ```
   codegiraffe_init(project_path=".", scanner_mode="regex")
   codegiraffe_blast_radius(project_path=".", node_id="module:graph")
   codegiraffe_risk_assessment(project_path=".")
   codegiraffe_cycles(project_path=".")
   ```

   **Expected results:**
   - blast radius for `module:graph` shows `scanner`, `query`, `server` as direct dependents
   - risk assessment identifies `graph.py` and `scanner.py` as highest-risk
   - No cycles expected in a well-structured Python project

2. **Nexus (Go project):**
   ```
   codegiraffe_blast_radius(project_path="/path/to/nexus", node_id="module:tui")
   ```

   **Expected results:**
   - blast radius for `tui` package shows 10+ impacted nodes
   - Severity tiers are correctly assigned

### 6.4 Commit Strategy

Single feature branch `007-actionable-intelligence` with atomic commits:

1. `feat(graph): add traversal extensions to ArchGraph`
2. `feat(query): add blast radius and impact summary functions`
3. `feat(server): add blast_radius, risk_assessment, cycles MCP tools`
4. `feat(server): enhance context_for and hotspots with impact/metrics params`
5. `test: add tests for actionable intelligence features`
6. `chore: bump version to 0.7.0`

---

## 7. Execution Strategy

### Dependency Graph

```
Phase 1: graph.py traversals
    |
    v
Phase 2: query.py blast radius + impact summary  (depends on Phase 1)
    |
    v
Phase 3: server.py tools  (depends on Phase 2)
    |
    v
Phase 4: Testing  (partially parallel with Phases 1-3)
    |
    v
Phase 5: Polish  (last)
```

### Parallelization Opportunities

- **Phase 1** must complete first (everything depends on the new ArchGraph methods).
- **Phase 2** depends on Phase 1 but is internally serial (`generate_impact_summary` depends on `compute_blast_radius` output structure).
- **Phase 3** depends on Phase 2 (tools call query functions), but the 3 new tools + 2 enhanced tools are independent of each other.
- **Phase 4 tests** can be written in parallel with implementation if the interfaces are defined first (this plan defines them). Test stubs for graph.py can be written alongside Phase 1 implementation.
- **Phase 5** is strictly last.

### Estimated Scope

| Phase | Files Modified | Lines Added | Tests Added |
|-------|---------------|-------------|-------------|
| 1 | graph.py | ~40 | ~20 |
| 2 | query.py | ~150 | ~25 |
| 3 | server.py | ~180 | ~10 |
| 4 | test files | ~350 | (counted above) |
| 5 | pyproject.toml, CLAUDE.md | ~20 | 0 |
| **Total** | **5-6 files** | **~740** | **~55** |

---

## 8. Risk Assessment

### R1: NetworkX Performance on Large Graphs (Low Risk)

**Risk:** `nx.betweenness_centrality()` is O(VE) and `nx.simple_cycles()` can be expensive on dense graphs.

**Mitigation:** Architecture graphs are typically small (< 1000 nodes). The `max_cycles` cap on cycle detection prevents runaway computation. If performance becomes an issue in production, betweenness centrality can be approximated with `nx.betweenness_centrality(G, k=min(100, len(G)))` for sampling-based approximation.

**Monitoring:** Add a log warning if betweenness computation takes > 2 seconds (deferred — not in v0.7.0 scope).

### R2: Cycle Detection Potentially Slow (Low Risk)

**Risk:** `nx.simple_cycles()` uses Johnson's algorithm which is O((V+E)(C+1)) where C is the number of cycles. Highly cyclic graphs could have exponential cycles.

**Mitigation:** The `max_cycles` parameter (default 100 in ArchGraph, default 20 in the MCP tool) stops enumeration early. The tool's default of 20 cycles is conservative and safe.

### R3: Impact Summary Format May Need Iteration (Medium Risk)

**Risk:** The markdown output format is defined in the spec, but real-world output may need refinement after seeing actual graph data.

**Mitigation:** The `generate_impact_summary()` function is a pure formatting function with no side effects. It can be refined in a follow-up without changing the API. Dogfood testing in Phase 5 will reveal formatting issues.

### R4: Blast Radius on Disconnected Graphs (Low Risk)

**Risk:** A node with no outgoing edges returns empty blast radius, which is correct but may confuse users.

**Mitigation:** The impact summary handles this gracefully with "0 nodes affected" messaging. The tool docstring explains this.

### R5: `nx.shortest_path` on Unreachable Nodes (Low Risk)

**Risk:** If a descendant is found by `nx.descendants()` but `nx.shortest_path_length()` fails (should not happen, but defensive coding).

**Mitigation:** Use `nx.single_source_shortest_path_length()` which returns only reachable nodes. Filter descendants against the distances dict. This is the approach specified in Phase 2.

### R6: Backward Compatibility of Enhanced Tools (Low Risk)

**Risk:** Adding parameters to existing tools could break clients that don't expect them.

**Mitigation:** All new parameters have defaults that preserve current behavior. MCP tool parameters are keyword arguments. No existing return format changes unless the new parameter is explicitly set to a non-default value.

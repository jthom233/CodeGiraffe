[← Back to Documentation](../README.md) | [Tool Index](README.md)

# Context & Analysis

These tools help you understand the architecture before changing it. `codegiraffe_context_for` is the primary tool for retrieving task-relevant context; the others surface hotspots, structural patterns, change impact, and circular dependencies.

---

### `codegiraffe_context_for`

The killer tool. Given a natural-language task description, returns the minimal relevant subgraph ranked by impact — so agents get exactly the context they need without wasting tokens on irrelevant code. Automatically classifies task intent and adjusts retrieval strategy accordingly.

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_path` | `str` | — | yes | Root directory of the project |
| `task` | `str` | — | yes | Natural language task description |
| `max_nodes` | `int` | `20` | no | Maximum nodes to return |
| `use_embeddings` | `bool` | `true` | no | Use embedding-based semantic scoring when available |
| `include_impact` | `bool` | `false` | no | Augment nodes with `_blast_radius_count` and `_risk_score` metadata |
| `include_changes` | `bool` | `false` | no | Boost nodes affected by uncommitted git changes (adds `_recently_changed` and `_in_change_blast_radius` metadata) |
| `min_confidence` | `float` | `0.0` | no | Filter edges below this confidence threshold (0.0-1.0) |
| `token_budget` | `int` | `0` | no | Maximum estimated tokens for response (0 = unlimited) |
| `detail_level` | `str` | `"standard"` | no | Response detail level: `"summary"` (minimal tokens), `"standard"` (balanced), `"detailed"` (full context) |

**Response enhancements (v0.11.0):**
- `_token_estimate` — Estimated token count for the response
- `_retrieval_strategy` — Classified task intent used to steer retrieval: `create`, `debug`, `refactor`, `delete`, `test`, or `modify`

When `sentence-transformers` is installed and `use_embeddings` is `true`, scoring uses embedding-based semantic similarity for significantly better relevance ranking. Otherwise, it falls back to keyword overlap scoring.

When `include_changes` is `true`, nodes affected by uncommitted git changes receive a +0.3 score boost (directly changed) or +0.15 boost (in blast radius of changes), ensuring change-relevant context surfaces first.

Intent-aware navigation automatically classifies the task:
- **Feature addition** — Prioritizes endpoints and services that define the new capability
- **Bug fix** — Prioritizes nodes in the blast radius of error traces or affected modules
- **Performance** — Prioritizes hotspots (high centrality) and tight couplings
- **Refactoring** — Prioritizes cohesive clusters and related modules
- **Documentation** — Prioritizes public interfaces and entry points

**Example:**
```
codegiraffe_context_for(
  project_path="/home/user/my-project",
  task="add rate limiting to the payments endpoint",
  token_budget=2000,
  detail_level="detailed"
)
--> JSON subgraph with payments endpoint, its middleware, DB tables, env vars, ranked by relevance
    _token_estimate: 1856
    _retrieval_strategy: "modify"
```

---

### `codegiraffe_hotspots`

Identify the most coupled, change-prone areas of the architecture. Ranks nodes by degree centrality.

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_path` | `str` | — | yes | Root directory of the project |
| `top_n` | `int` | `10` | no | Number of hotspots to return |
| `metrics` | `str` | `"degree"` | no | Ranking strategy: `"degree"` (degree centrality), `"betweenness"` (bottleneck nodes), or `"combined"` (0.5×degree + 0.5×betweenness) |

**Example:**
```
codegiraffe_hotspots(project_path="/home/user/my-project", top_n=5)
--> [{"node_id": "service:AuthService", "label": "Auth Service", "type": "service", "score": 0.4231}]
```

---

### `codegiraffe_patterns`

Analyze clusters of same-type nodes to extract naming conventions, structural patterns, and detect anti-patterns. Useful for understanding architectural styles and identifying inconsistencies.

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_path` | `str` | — | yes | Root directory of the project |
| `node_type` | `str` | — | yes | Node type to analyze (e.g., `"endpoint"`, `"service"`, `"database_table"`) |
| `min_cluster` | `int` | `3` | no | Minimum cluster size to report |

**Analysis includes:**
- **Naming patterns** — Extracts common prefixes, suffixes, and delimiters (e.g., `GET /api/*`, `POST /admin/*`)
- **Structural patterns** — Identifies common edge types, counts, and dependency depths
- **Anti-patterns** — Detects inconsistencies like orphaned nodes, naming violations, or unusually high/low coupling
- **Cluster analysis** — Groups similar nodes and reports their characteristics

**Example:**
```
codegiraffe_patterns(project_path="/home/user/my-project", node_type="endpoint", min_cluster=3)
--> ## Convention Mining: `endpoint`
    **Nodes analysed:** 11

    **Naming pattern:** `endpoint:/api/*`

    **Exemplar node:** `endpoint:/api/users`

    **Common attributes** (present in >66% of nodes):
    - type: endpoint

    **Outliers** (deviate from naming pattern):
    - endpoint:/health
    - endpoint:get_user
```

---

### `codegiraffe_blast_radius`

Analyze the blast radius of changing a specific node. Returns what breaks downstream, ranked by severity (direct, transitive, indirect), plus any circular dependencies and hotspots. Edge confidence is weighted into the impact calculation.

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_path` | `str` | — | yes | Root directory of the project |
| `node_id` | `str \| None` | `None` | no | Exact node ID to analyze. Takes precedence over `query`. |
| `query` | `str \| None` | `None` | no | Free-text search to find the target node (substring + semantic match). Use when you don't know the exact node ID. |
| `include_upstream` | `bool` | `false` | no | Accepted for backwards compatibility; upstream is always included in the report. |
| `max_depth` | `int \| None` | `None` | no | Limit analysis to N hops |

**Example:**
```
codegiraffe_blast_radius(
  project_path="/home/user/my-project",
  node_id="service:AuthService",
  include_upstream=true
)
--> Formatted markdown impact report showing downstream dependencies ranked by severity (direct, transitive, indirect), circular dependencies, and hotspots in the impact zone
```

---

### `codegiraffe_risk_assessment`

Assess architectural risk for nodes. Risk = (degree * 0.4) + (betweenness * 0.4) + (descendants/total * 0.2).

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_path` | `str` | — | yes | Root directory of the project |
| `node_ids` | `list[str] \| None` | `None` | no | Specific nodes to assess (None = top 10) |

**Example:**
```
codegiraffe_risk_assessment(project_path="/home/user/my-project")
--> [{"node_id": "service:AuthService", "risk_score": 0.82, "degree_centrality": 0.45, "betweenness_centrality": 0.45, "blast_radius_count": 8, "file_path": "src/auth.py"}, ...]
```

---

### `codegiraffe_cycles`

Detect circular dependencies in the architecture graph.

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_path` | `str` | — | yes | Root directory of the project |
| `max_cycles` | `int` | `20` | no | Maximum number of cycles to detect |

**Example:**
```
codegiraffe_cycles(project_path="/home/user/my-project", max_cycles=10)
--> [{"cycle": ["service:A", "service:B", "service:C", "service:A"], "length": 3}, ...]
```

---

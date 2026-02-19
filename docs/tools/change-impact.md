[← Back to Documentation](../README.md) | [Tool Index](README.md)

# Change Impact

These tools analyze the impact of code changes against the architecture graph. Use them before committing to catch incomplete modifications, identify the right tests to run, detect implicit file coupling, review architectural changes in a PR, and map test coverage to graph nodes.

---

### `codegiraffe_validate_changes`

Analyze uncommitted (or arbitrary) changes against the architecture graph to detect incomplete modifications. Parses a diff, maps changed files to graph nodes, computes blast radius, and reports potentially missing changes and contract violations.

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_path` | `str` | — | yes | Root directory of the project |
| `diff` | `str \| None` | `None` | no | Raw unified diff string to analyze |
| `auto` | `bool` | `true` | no | When `true` and `diff` is not provided, reads uncommitted changes from git automatically |

**Example:**
```
codegiraffe_validate_changes(project_path="/home/user/my-project")
--> ## Change Validation Report
    **Changed files:** 3
    **Total blast radius:** 12 nodes affected
    **Covered:** 5 (also changed in diff)
    **Potentially missing:** 7 nodes

    ### Recommendations
    - Consider updating service:PaymentService (direct dependency)
    - Contract violation: changed producer endpoint:/api/users but consumer component:UserList unchanged
```

---

### `codegiraffe_suggest_tests`

Suggest test files to run based on uncommitted (or arbitrary) changes. Uses graph relationships, naming conventions, and blast radius analysis to identify the most relevant tests. Includes `coverage_status` field (covered/uncovered/unknown).

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_path` | `str` | — | yes | Root directory of the project |
| `diff` | `str \| None` | `None` | no | Raw unified diff string to analyze |
| `auto` | `bool` | `true` | no | When `true` and `diff` is not provided, reads uncommitted changes from git automatically |
| `max_suggestions` | `int` | `20` | no | Maximum number of test files to suggest |

Tests are scored by three strategies:
- **Graph-based (0.9)** — Test nodes with import edges to/from changed nodes
- **Naming convention (0.6)** — Test files matching common naming patterns for changed sources
- **Blast radius (0.3)** — Test nodes in transitive dependency set of changes

**Example:**
```
codegiraffe_suggest_tests(project_path="/home/user/my-project")
--> ## Test Suggestions
    **3 test(s) suggested**

    ### High Relevance (score >= 0.7)
    - tests/test_auth.py (0.90) — graph: imports changed module [graph] (coverage: covered)

    ### Medium Relevance (0.3 <= score < 0.7)
    - tests/test_users.py (0.60) — naming: matches changed file users.py [naming] (coverage: uncovered)

    ### Low Relevance (score < 0.3)
    - tests/test_api.py (0.30) — blast radius: transitive dependency [blast_radius] (coverage: unknown)
```

---

### `codegiraffe_file_coupling`

Analyze file coupling from git co-change history. Mines recent commits to find files that frequently change together, then cross-references with the architecture graph to detect implicit coupling not captured in the graph.

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_path` | `str` | — | yes | Root directory of the project |
| `file_path` | `str \| None` | `None` | no | Focus on a specific file's coupling partners |
| `depth` | `int` | `100` | no | Number of recent commits to analyze |
| `min_commits` | `int` | `3` | no | Minimum co-change count to report |
| `min_coupling` | `float` | `0.1` | no | Minimum coupling ratio (0.0-1.0) to report |

Coupling ratio = co-change count / max(changes in file A, changes in file B).

**Example:**
```
codegiraffe_file_coupling(project_path="/home/user/my-project", depth=50)
--> ## File Coupling Analysis
    **6 coupled pair(s) found**

    | Coupled File | Co-Changes | Coupling | In Graph? |
    |---|---|---|---|
    | auth.py ↔ users.py | 8 | 0.73 | Yes |
    | config.py ↔ settings.py | 5 | 0.50 | No |

    ### Implicit Coupling (not in graph)
    - config.py ↔ settings.py: 50% coupling over 5 co-changes — consider adding a graph relationship
```

---

### `codegiraffe_pr_diff`

Compare graph architecture at two git refs to detect structural changes. Useful for PR review to understand what's being added/removed at the architecture level.

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_path` | `str` | — | yes | Root directory of the project |
| `base_ref` | `str` | — | yes | Base git ref (branch, tag, or commit) |
| `head_ref` | `str` | `"HEAD"` | no | Head git ref to compare against |
| `scanner_mode` | `str` | `"regex"` | no | Scanner mode: `"regex"` (default) or `"ast"` (tree-sitter) |

**Example:**
```
codegiraffe_pr_diff(
  project_path="/home/user/my-project",
  base_ref="main",
  head_ref="feature/new-api"
)
--> {
      "nodes_added": ["endpoint:/api/v2/users", "service:UserServiceV2"],
      "nodes_removed": [],
      "edges_added": [{"source": "endpoint:/api/v2/users", "target": "table:users", "type": "reads"}],
      "structural_changes": 2
    }
```

---

### `codegiraffe_coverage`

Map test coverage data from coverage.py, Istanbul, or LCOV files to graph nodes. Links covered/uncovered code regions to their corresponding nodes for risk assessment.

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_path` | `str` | — | yes | Root directory of the project |
| `coverage_path` | `str` | — | yes | Path to coverage file (.coverage, coverage.json, or .lcov) |
| `format` | `str` | `"auto"` | no | Coverage format: `"auto"` (detect from file), `"coverage_py"`, `"istanbul"`, or `"lcov"` |

**Example:**
```
codegiraffe_coverage(
  project_path="/home/user/my-project",
  coverage_path=".coverage",
  format="coverage_py"
)
--> "Mapped coverage data: 127 nodes covered (78%), 36 nodes uncovered (22%)"
```

---

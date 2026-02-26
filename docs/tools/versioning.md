[← Back to Documentation](../README.md) | [Tool Index](README.md)

# Schema Evolution & Versioning

Code Giraffe tracks how your architecture graph changes over time. Every `codegiraffe_sync` and `codegiraffe_init(rescan=True)` automatically creates a version.

## Automatic Versioning

Version history is stored at `{project_path}/.codegiraffe/versions.json` as diffs (not full snapshots) for storage efficiency. Maximum 100 versions are retained by default.

## Manual Snapshots

Create named bookmarks before making significant changes:

```
codegiraffe_snapshot(project_path="...", message="Before payment refactor")
```

## Viewing History

```
codegiraffe_history(project_path="...")
--> [{version_id: 1, message: "Init", timestamp: "...", nodes_added: 47, ...}, ...]

codegiraffe_diff(project_path="...", version_a=3)
--> {nodes_added: [...], nodes_removed: [...], edges_added: [...], attrs_changed: [...]}
```

---

### `codegiraffe_history`

List version history for a project's architecture graph. Returns timestamped entries with diff summaries.

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_path` | `str` | — | yes | Root directory of the project |
| `limit` | `int` | `20` | no | Maximum number of versions to return |

**Example:**
```
codegiraffe_history(project_path="/home/user/my-project")
--> [{"version_id": 3, "timestamp": "...", "message": "Sync", "nodes_added": 2, "nodes_removed": 0, ...}]
```

---

### `codegiraffe_diff`

Compare two versions of the architecture graph, or view a specific version's diff.

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_path` | `str` | — | yes | Root directory of the project |
| `version_a` | `int` | — | yes | Version ID to inspect or compare |
| `version_b` | `int \| None` | `None` | no | Second version ID for comparison |

**Example:**
```
codegiraffe_diff(project_path="/home/user/my-project", version_a=3)
--> {"nodes_added": ["service:NewSvc"], "nodes_removed": [], "edges_added": [...], ...}
```

---

### `codegiraffe_snapshot`

Create a named snapshot of the current graph state for bookmarking before changes.

| Parameter | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_path` | `str` | — | yes | Root directory of the project |
| `message` | `str` | `"Manual snapshot"` | no | Descriptive message for this snapshot |

**Example:**
```
codegiraffe_snapshot(project_path="/home/user/my-project", message="Before auth refactor")
--> {"version_id": 4, "message": "Before auth refactor", "timestamp": "..."}
```

---


# Quickstart: Scanner Intelligence v0.4.0

## What Changed

The scanner now produces a much richer, more accurate architecture graph:

1. **Test files excluded** — No more test classes polluting the graph
2. **Import edges** — See which modules depend on which other modules
3. **Inheritance edges** — See class hierarchies and protocol implementations
4. **Module nodes** — File-level architecture view with containment relationships

## Try It

```bash
# Scan your project (test files excluded by default)
codegiraffe_init(project_path="/path/to/project")

# Include test files (tagged with source: test)
codegiraffe_init(project_path="/path/to/project", include_tests=True)

# Query module-level architecture
codegiraffe_query(project_path="/path/to/project", node_type="module")

# See import dependencies for a specific module
codegiraffe_query(project_path="/path/to/project", node_id="mod:mypackage.server", depth=1)

# Find which classes implement a protocol
codegiraffe_query(project_path="/path/to/project", node_id="service:StorageBackend", depth=1)
```

## New Node Types

- `module` — Represents a Python source file (e.g., `mod:codegiraffe.graph`)

## New Edge Types

- `imports` — Module A imports from Module B (with symbol list in metadata)
- `implements` — Class A inherits from / implements Class B
- `contains` — Module contains a class/function/entity

## Dashboard

The web dashboard now shows a connected, meaningful graph with:
- Module clusters connected by import edges
- Inheritance hierarchies visible as `implements` edges
- Filter by node type to toggle between module-level and class-level views

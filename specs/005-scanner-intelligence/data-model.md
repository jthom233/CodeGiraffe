# Data Model: Scanner Intelligence Improvements (v0.4.0)

## New Node Type

### Module

| Field | Value |
|-------|-------|
| **type** | `module` |
| **id format** | `mod:<dotted.module.path>` (e.g., `mod:codegiraffe.graph`) |
| **label** | Module name (e.g., `graph`) |
| **file_path** | Absolute path to the .py file |
| **metadata** | `{package: "codegiraffe", source: "production"}` |

**Rules**:
- One module node per .py source file (excluding test files by default)
- `__init__.py` produces a package-level module node (e.g., `mod:codegiraffe`)
- Module path derived from file path relative to project root, using Python package conventions
- Files outside packages (no `__init__.py` chain) use directory-relative path

## New Edge Types

### imports

| Field | Value |
|-------|-------|
| **source** | Module node (`mod:X`) |
| **target** | Module node (`mod:Y`) |
| **type** | `imports` |
| **metadata** | `{symbols: ["ArchGraph", "GraphData"], style: "absolute"}` |
| **manual** | `False` (auto-detected) |

**Rules**:
- One edge per unique (source_module, target_module) pair
- Multiple imports from same module → single edge with combined symbols list
- Only project-internal imports produce edges (stdlib and third-party excluded)
- Relative imports resolved to absolute paths before edge creation
- `style` metadata: `"absolute"` or `"relative"`

### implements

| Field | Value |
|-------|-------|
| **source** | Class node (`service:ChildClass`) |
| **target** | Class node (`service:BaseClass`) |
| **type** | `implements` |
| **metadata** | `{inferred: true, cross_file: true/false}` |
| **manual** | `False` (auto-detected) |

**Rules**:
- One edge per (subclass, base_class) pair
- Only base classes that exist as nodes in the graph produce edges
- Cross-file resolution: base class name matched against global class registry
- Multiple inheritance: one `implements` edge per base class

### contains

| Field | Value |
|-------|-------|
| **source** | Module node (`mod:X`) |
| **target** | Any entity node defined in the module |
| **type** | `contains` |
| **metadata** | `{inferred: true}` |
| **manual** | `False` (auto-detected) |

**Rules**:
- Connects module to all top-level entities (classes, functions, endpoints, etc.) defined within it
- Created during the same scan pass that creates the entity nodes

## Schema Changes

### NodeType Enum (schema.py)

Add: `MODULE = "module"`

### EdgeType Enum (schema.py)

Add:
- `IMPORTS = "imports"`
- `IMPLEMENTS = "implements"`
- `CONTAINS = "contains"`

## Modified Entities

### Node (graph.py)

No structural changes. New `source` metadata key:
- `source: "production"` — default for non-test files
- `source: "test"` — when `include_tests=True` and file is a test file

### scan_project() Parameters

New parameters:
- `include_tests: bool = False` — when True, scan test files with `source: test` tag
- (scanner_mode, backend already exist)

### MCP Tool Parameters

`codegiraffe_init` and `codegiraffe_sync` gain:
- `include_tests: bool = False` — passed through to `scan_project()`

## Backward Compatibility

- Existing graphs without `module` nodes or new edge types load fine (additive schema)
- Existing `service` nodes unchanged — module nodes are NEW alongside them
- No migration needed — old graphs just lack the new features until rescan

# Implementation Plan: Language-Agnostic Scanner Intelligence (v0.6.0)

**Branch**: `006-language-agnostic-intelligence` | **Date**: 2026-02-13 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/006-language-agnostic-intelligence/spec.md`

## Summary

Code Giraffe v0.4.0 introduced scanner intelligence features (module nodes, import edges, contains edges, inheritance edges) but they only work for Python. All other 8 supported languages produce sparse node-only graphs with edge/node ratios of 0.1-0.3 vs Python's 0.5+. This plan moves scanner intelligence into the universal pipeline and extends every recognizer to provide structured import and inheritance data, achieving rich graph density for all 9 languages.

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: FastMCP (mcp[cli] >= 1.2.0), NetworkX >= 3.0, Pydantic v2
**Storage**: JSON + SQLite + Neo4j (existing, unchanged)
**Testing**: pytest >= 8.0, pytest-asyncio >= 0.23 (566 existing tests)
**Package Management**: uv
**Target**: Any OS with Python 3.11+, all 9 supported languages
**Constraints**: Backward compatible with v0.5.0, all 566 existing tests must pass
**Performance Goals**: No measurable slowdown on scan_project(); go.mod/Cargo.toml reads are amortized per-project

## Constitution Check

| Principle | Status | Notes |
|-----------|--------|-------|
| I. MCP-Native | PASS | No new tools. Intelligence surfaces through existing `init`/`sync`/`query` tools |
| II. Graph-First | PASS | Extends typed graph with richer edges for all languages. Same schema types (module, imports, implements, contains) |
| III. Beyond-AST | PASS | Import/inheritance edges connect to beyond-AST nodes (env vars, APIs, queues) to form a complete architecture graph |
| IV. Context Efficiency | PASS | Richer edges improve context scoring without increasing node noise |
| V. Incremental & Non-Destructive | PASS | New ScanResult fields default to empty lists. Recognizers without the new protocol work unchanged |
| VI. Test-First | PASS | TDD mandatory. ~100+ new tests target |
| VII. Simplicity | PASS | 2 new dataclasses + 2 new optional ScanResult fields. No new dependencies. No schema changes |

---

## Architecture Overview

### Current State (v0.5.0)

```
scan_project()
├── For each file:
│   ├── recognizer.recognize(path, content) -> ScanResult(nodes, edges)
│   ├── IF .py: create module node + contains edges       <-- Python-only
│   └── merge into global result
├── _infer_cross_file_edges(result, file_contents)         <-- Python-only
├── _infer_import_edges(result, file_contents, project_path) <-- Python-only, parses .py
└── _infer_inheritance_edges(result, class_registry, file_contents) <-- Python-only, parses .py
```

### Target State (v0.6.0)

```
scan_project()
├── For each file:
│   ├── recognizer.recognize(path, content) -> ScanResult(nodes, edges, imports, implementations)
│   ├── FOR ALL LANGUAGES: create module node + contains edges   <-- UNIVERSAL
│   └── merge into global result
├── _infer_cross_file_edges(result, file_contents)               <-- unchanged, Python-specific
├── _infer_import_edges_universal(result, all_scan_results)      <-- NEW: works from ScanResult.imports
├── _infer_import_edges(result, file_contents, project_path)     <-- KEPT: Python fallback
├── _infer_inheritance_edges_universal(result, all_scan_results) <-- NEW: works from ScanResult.implementations
└── _infer_inheritance_edges(result, class_registry, file_contents) <-- KEPT: Python fallback
```

### Key Design Decisions

1. **ScanResult as the universal exchange contract.** Recognizers return structured `imports` and `implementations` data. The scanner pipeline converts these into edges. This inverts the current approach where the scanner parses Python source directly.

2. **Dual-path import inference.** The new `_infer_import_edges_universal()` processes `ScanResult.imports` from any language. The existing `_infer_import_edges()` remains as a fallback for Python files (which already works and has 566 tests depending on it). The universal path runs first; the Python-specific path only creates edges not already created by the universal path.

3. **Module ID format is `mod:{package}.{filename_stem}` for all languages.** Each language uses a `_file_to_module_path_*()` helper to convert file paths to dotted module paths. For Go, this includes the package declaration. For Rust, this follows `crate::module::submodule` conventions. For others, it mirrors the directory structure relative to the project root.

4. **go.mod / Cargo.toml / tsconfig.json reading is done once per scan, not per file.** The scanner reads project manifest files once and passes the module prefix to recognizers via a new optional `project_context` parameter or closure.

5. **Test file patterns are language-specific.** The `_is_test_file()` function is extended with a suffix-based dispatch that checks the file extension before applying language-specific patterns.

---

## Phase 1: Core Pipeline (scanner.py + ScanResult)

**Requirements**: R1, R2, R3, R4, R14
**Files to modify**: `src/codegiraffe/scanner.py`
**Dependencies**: None (must complete before Phases 2-5)
**Estimated new tests**: ~30

### 1.1 Add ImportInfo and ImplementationInfo Dataclasses

Add two new dataclasses to `scanner.py` alongside the existing `ScanResult`:

```python
@dataclass
class ImportInfo:
    """Structured import information returned by recognizers."""
    module_path: str        # Dotted or slash-separated module path (project-relative)
    symbols: list[str] = field(default_factory=list)  # Imported symbol names (empty = whole-module)
    style: str = "absolute" # "absolute" | "relative" | "wildcard"

@dataclass
class ImplementationInfo:
    """Structured inheritance/implementation information returned by recognizers."""
    child_class: str   # Name of the implementing class/struct
    parent_class: str  # Name of the base class/interface/trait
    file_path: str     # File where the child is defined (relative path)
```

**Design decision**: Plain dataclasses (not Pydantic) to match `ScanResult` convention and avoid import cost. The `file_path` on `ImplementationInfo` is the relative path string, consistent with `Node.file_path`.

### 1.2 Extend ScanResult with Optional Fields

Add two new optional fields to the `ScanResult` dataclass:

```python
@dataclass
class ScanResult:
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    imports: list[ImportInfo] = field(default_factory=list)           # NEW
    implementations: list[ImplementationInfo] = field(default_factory=list)  # NEW
```

Update `ScanResult.merge()` to also merge `imports` and `implementations` lists (simple extend, no dedup needed since they carry per-file context).

**Backward compatibility**: Both fields default to empty lists. Existing recognizers that return `ScanResult(nodes=..., edges=...)` continue to work because dataclass fields have defaults.

### 1.3 Universal Module Node Creation

Refactor the per-file loop in `scan_project()` to create module nodes for ALL languages, not just Python.

**Current code** (lines 887-912 of scanner.py):
```python
# T050: Create module node for Python files
if suffix in (".py", ".pyi"):
    module_path = _file_to_module_path(source_file, project_path)
    ...
```

**Refactored code**:
```python
# Create module node for ALL languages
module_path = _file_to_module_path_universal(source_file, project_path, suffix)
module_id = f"mod:{module_path}"
module_label = module_path.rsplit(".", 1)[-1] if "." in module_path else module_path

module_node = Node(
    id=module_id,
    type=NodeType.MODULE.value,
    label=module_label,
    file_path=str(rel_path),
    metadata={
        "package": module_path.rsplit(".", 1)[0] if "." in module_path else "",
        "source": "test" if is_test else "production",
        "language": _suffix_to_language(suffix),
    },
)
file_nodes.append(module_node)

# Create contains edges from module to all entities in this file
for node in file_nodes:
    if node.id != module_id:
        file_edges.append(Edge(
            source=module_id,
            target=node.id,
            type=EdgeType.CONTAINS.value,
            metadata={"inferred": True},
        ))
```

### 1.4 Universal File-to-Module-Path Helper

Add `_file_to_module_path_universal()` that handles all languages:

```python
def _file_to_module_path_universal(file_path: Path, project_path: str, suffix: str) -> str:
    """Convert a file path to a dotted module path for any language."""
    if suffix in (".py", ".pyi"):
        return _file_to_module_path(file_path, project_path)  # Existing Python logic

    # Generic: use relative path with dots
    rel = file_path.relative_to(project_path)
    parts = list(rel.parts)

    # Strip common source layout prefixes
    if parts and parts[0] in ("src", "lib", "app", "pkg", "cmd"):
        parts = parts[1:]

    # Remove extension from last component
    if parts:
        parts[-1] = Path(parts[-1]).stem

    return ".".join(parts)
```

**Design decision**: Keep the existing `_file_to_module_path()` for Python (well-tested, handles `__init__.py`, src-layout). The universal helper dispatches to it for `.py` files and uses a generic directory-to-dots conversion for everything else.

### 1.5 Language Suffix Helper

Add a simple mapping function:

```python
_SUFFIX_TO_LANGUAGE: dict[str, str] = {
    ".py": "python", ".pyi": "python",
    ".go": "go",
    ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript", ".cts": "typescript",
    ".rs": "rust",
    ".java": "java",
    ".cs": "csharp",
    ".c": "c", ".cpp": "cpp", ".h": "c", ".hpp": "cpp", ".cc": "cpp", ".cxx": "cpp",
    ".php": "php",
    ".rb": "ruby",
}

def _suffix_to_language(suffix: str) -> str:
    return _SUFFIX_TO_LANGUAGE.get(suffix, "unknown")
```

### 1.6 Universal Import Edge Inference

Add `_infer_import_edges_universal()`:

```python
def _infer_import_edges_universal(
    result: ScanResult,
    per_file_results: dict[Path, ScanResult],
) -> None:
    """Create imports edges from recognizer-provided ImportInfo data.

    Processes ScanResult.imports from all files and creates imports edges
    between module nodes. This is the language-agnostic replacement for
    _infer_import_edges() which only handles Python.
    """
    # Build set of known module node IDs
    module_ids: set[str] = {n.id for n in result.nodes if n.type == NodeType.MODULE.value}

    # Build mapping: relative file path -> module node ID
    file_to_mod_id: dict[str, str] = {}
    for node in result.nodes:
        if node.type == NodeType.MODULE.value and node.file_path:
            file_to_mod_id[node.file_path] = node.id

    existing_edges = {(e.source, e.target, e.type) for e in result.edges}

    for rel_path, file_result in per_file_results.items():
        source_mod_id = file_to_mod_id.get(str(rel_path))
        if not source_mod_id or not file_result.imports:
            continue

        for imp in file_result.imports:
            target_mod_id = f"mod:{imp.module_path}"
            if target_mod_id not in module_ids:
                continue  # External import, skip
            if source_mod_id == target_mod_id:
                continue  # Self-import, skip

            edge_key = (source_mod_id, target_mod_id, EdgeType.IMPORTS.value)
            if edge_key not in existing_edges:
                result.edges.append(Edge(
                    source=source_mod_id,
                    target=target_mod_id,
                    type=EdgeType.IMPORTS.value,
                    metadata={
                        "symbols": imp.symbols,
                        "style": imp.style,
                        "inferred": True,
                    },
                ))
                existing_edges.add(edge_key)
```

### 1.7 Universal Inheritance Edge Inference

Add `_infer_inheritance_edges_universal()`:

```python
def _infer_inheritance_edges_universal(
    result: ScanResult,
    per_file_results: dict[Path, ScanResult],
) -> None:
    """Create implements edges from recognizer-provided ImplementationInfo data."""
    # Build class name -> node ID registry from all nodes
    class_registry: dict[str, str] = {}
    for node in result.nodes:
        if node.type == NodeType.SERVICE.value:
            class_name = node.metadata.get("class_name") or node.metadata.get("struct_name") or node.label
            class_registry[class_name] = node.id

    existing_edges = {(e.source, e.target, e.type) for e in result.edges}

    for rel_path, file_result in per_file_results.items():
        for impl in file_result.implementations:
            child_id = class_registry.get(impl.child_class)
            parent_id = class_registry.get(impl.parent_class)

            if not child_id or not parent_id or child_id == parent_id:
                continue

            edge_key = (child_id, parent_id, EdgeType.IMPLEMENTS.value)
            if edge_key not in existing_edges:
                child_node = next((n for n in result.nodes if n.id == child_id), None)
                parent_node = next((n for n in result.nodes if n.id == parent_id), None)
                same_file = (child_node and parent_node and
                            child_node.file_path == parent_node.file_path)

                result.edges.append(Edge(
                    source=child_id,
                    target=parent_id,
                    type=EdgeType.IMPLEMENTS.value,
                    metadata={
                        "inferred": True,
                        "cross_file": not same_file,
                    },
                ))
                existing_edges.add(edge_key)
```

### 1.8 Wire Universal Inference into scan_project()

Modify `scan_project()` to:

1. Collect per-file `ScanResult` objects in a `dict[Path, ScanResult]` (in addition to the merged result).
2. After the file loop, call `_infer_import_edges_universal()` BEFORE `_infer_import_edges()`.
3. Call `_infer_inheritance_edges_universal()` BEFORE `_infer_inheritance_edges()`.
4. The Python-specific functions still run but the `existing_edges` check prevents duplicates.

```python
# New: collect per-file results for universal inference
per_file_results: dict[Path, ScanResult] = {}

for source_file in sorted(root.rglob("*")):
    # ... existing file loop ...
    combined = ScanResult(nodes=file_nodes, edges=file_edges,
                          imports=file_imports, implementations=file_implementations)
    per_file_results[rel_path] = combined
    merged.merge(combined)

# Universal import inference (all languages)
_infer_import_edges_universal(merged, per_file_results)

# Python-specific import inference (backward compat, fills gaps)
_infer_import_edges(merged, file_contents, project_path)

# Universal inheritance inference (all languages)
_infer_inheritance_edges_universal(merged, per_file_results)

# Python-specific inheritance inference (backward compat)
_infer_inheritance_edges(merged, class_registry, file_contents)
```

### 1.9 Collect Per-File Imports and Implementations

In the per-file loop, after running recognizers, aggregate the `imports` and `implementations` lists:

```python
file_imports: list[ImportInfo] = []
file_implementations: list[ImplementationInfo] = []
for recognizer in applicable:
    file_result = recognizer.recognize(rel_path, content)
    file_nodes.extend(file_result.nodes)
    file_edges.extend(file_result.edges)
    file_imports.extend(file_result.imports)
    file_implementations.extend(file_result.implementations)
```

### Phase 1 Test Plan

- Test `ImportInfo` and `ImplementationInfo` dataclasses (construction, defaults)
- Test `ScanResult` merge with imports/implementations
- Test `_file_to_module_path_universal()` for Go, TypeScript, Rust, Java, C#, C/C++, PHP, Ruby paths
- Test module node creation for non-Python files
- Test contains edge creation for non-Python files
- Test `_infer_import_edges_universal()` with mock ScanResults containing ImportInfo
- Test `_infer_inheritance_edges_universal()` with mock ScanResults containing ImplementationInfo
- Test backward compatibility: Python scan produces identical results as v0.5.0
- Test `_suffix_to_language()` mapping

---

## Phase 2: Go Recognizer Enhancement

**Requirements**: R5
**Files to modify**: `src/codegiraffe/recognizers/go.py`
**Dependencies**: Phase 1 must complete first
**Estimated new tests**: ~20
**Priority**: Highest (real user feedback from Nexus project)

### 2.1 Full Import Block Parsing

Add regex patterns for Go import statements:

```python
# Single import: import "path/to/package"
_GO_SINGLE_IMPORT_RE = re.compile(r'import\s+"([^"]+)"')

# Grouped import block: import ( "path1" \n "path2" )
_GO_GROUPED_IMPORT_RE = re.compile(r'import\s*\(([\s\S]*?)\)', re.MULTILINE)

# Individual import line within a group (handles aliases): alias "path/to/package"
_GO_IMPORT_LINE_RE = re.compile(r'(?:\w+\s+)?"([^"]+)"')
```

### 2.2 go.mod Module Path Detection

Read `go.mod` to determine the project's module path for internal vs external import classification:

```python
def _read_go_module_path(project_path: str) -> str | None:
    """Read the module path from go.mod if it exists."""
    go_mod = Path(project_path) / "go.mod"
    if not go_mod.exists():
        return None
    for line in go_mod.read_text().splitlines():
        if line.startswith("module "):
            return line.split(None, 1)[1].strip()
    return None
```

The Go recognizer needs the project's module path to distinguish internal imports from external ones. Two approaches:

**Option A**: Pass project context into recognize() via a new optional parameter.
**Option B**: Read go.mod inside the recognizer using file_path to find the project root.

**Decision**: Option A is cleaner but breaks the `PatternRecognizer` protocol. Instead, add a `set_project_context(project_path: str)` method to GoRecognizer that `scan_project()` calls before scanning. For recognizers that don't implement it, nothing happens. This keeps the protocol stable.

Actually, simpler: GoRecognizer reads go.mod lazily on first `recognize()` call, caching the result. It can derive the project root from the `file_path` argument by walking up to find `go.mod`.

**Final decision**: The scanner already knows `project_path`. Add an optional `project_path` field to `ScanResult` or pass it to recognizers. The cleanest approach: make recognizers accept an optional `project_path` kwarg. Since recognizers use duck-typing (Protocol), and Python ignores extra kwargs with `**kwargs`, this is safe. But simpler still: have GoRecognizer cache the module path the first time, derived from walking up from the scanned file's path.

**Simplest correct approach**: `scan_project()` already resolves the `project_path`. Before the file loop, it reads go.mod/Cargo.toml/etc. once, then stores the module prefix. It passes this as part of the file path or via a closure. However, to avoid changing the `PatternRecognizer` protocol at all, the recognizer can accept a `project_root` attribute set before scanning:

```python
class GoRecognizer:
    def __init__(self) -> None:
        self._go_module_path: str | None = None
        self._project_root: str | None = None

    def set_project_root(self, project_root: str) -> None:
        """Optional: set project root for import classification."""
        self._project_root = project_root
        go_mod = Path(project_root) / "go.mod"
        if go_mod.exists():
            for line in go_mod.read_text().splitlines():
                if line.startswith("module "):
                    self._go_module_path = line.split(None, 1)[1].strip()
                    break
```

`scan_project()` calls `set_project_root(project_path)` on any recognizer that has the method (duck-type check):

```python
for recognizer in applicable:
    if hasattr(recognizer, 'set_project_root'):
        recognizer.set_project_root(project_path)
```

### 2.3 Internal Import Classification

An import is internal if it starts with the go.mod module path:

```python
def _is_internal_go_import(self, import_path: str) -> bool:
    if not self._go_module_path:
        return False
    return import_path.startswith(self._go_module_path + "/")
```

For internal imports, convert the import path to a dotted module path:
```python
# "github.com/user/project/internal/store" -> "internal.store"
relative = import_path.removeprefix(self._go_module_path + "/")
module_path = relative.replace("/", ".")
```

### 2.4 Return ImportInfo from GoRecognizer

In `recognize()`, after parsing imports:

```python
imports: list[ImportInfo] = []
# ... parse all import statements ...
for import_path in internal_imports:
    relative = import_path.removeprefix(self._go_module_path + "/")
    module_path = relative.replace("/", ".")
    imports.append(ImportInfo(
        module_path=module_path,
        symbols=[],  # Go imports entire packages
        style="absolute",
    ))
```

### 2.5 Interface Implementation Detection

Go doesn't have explicit `implements` keywords. Use the method-receiver heuristic: if a struct has method receivers matching an interface's method names, infer an implementation relationship.

The GoRecognizer already collects `struct_methods: dict[str, set[str]]` (struct name -> method names) and interface definitions. Extend this:

```python
# After collecting all interfaces and struct methods in the file:
implementations: list[ImplementationInfo] = []
interface_methods: dict[str, set[str]] = {}

# Collect interface method signatures
for iface_name in detected_interfaces:
    # Parse the interface body to get method names
    iface_match = re.search(
        rf'type\s+{re.escape(iface_name)}\s+interface\s*\{{([^}}]*)\}}',
        content, re.DOTALL
    )
    if iface_match:
        body = iface_match.group(1)
        methods = set(re.findall(r'(\w+)\s*\(', body))
        interface_methods[iface_name] = methods

# Match structs to interfaces
for struct_name, methods in struct_methods.items():
    for iface_name, iface_methods in interface_methods.items():
        if iface_methods and iface_methods.issubset(methods):
            implementations.append(ImplementationInfo(
                child_class=struct_name,
                parent_class=iface_name,
                file_path=str(file_path),
            ))
```

**Limitation**: This is a same-file heuristic. Cross-file interface matching requires the universal pipeline to resolve after all files are scanned. For v0.6.0, same-file matching is sufficient and avoids the complexity of a global interface registry.

### 2.6 Remove Existing `_GO_INTERNAL_IMPORT_RE` Duplication

The current GoRecognizer already creates `depends_on` edges for `internal/` package imports via `_GO_INTERNAL_IMPORT_RE`. This overlaps with the new universal import edge system. Keep the existing `depends_on` edges for backward compatibility but also return `ImportInfo` so the universal system creates `imports` edges (which are richer, with module-to-module semantics).

### Phase 2 Test Plan

- Test go.mod parsing (valid, missing, malformed)
- Test internal vs external import classification
- Test single import parsing
- Test grouped import block parsing (with aliases, blank lines, comments)
- Test ImportInfo generation for internal imports
- Test interface method extraction
- Test struct-to-interface matching (exact match, subset, no match)
- Test ImplementationInfo generation
- Test full Go file scan produces module nodes + contains + imports + implements edges
- Test backward compatibility: existing Go depends_on edges still created

---

## Phase 3: TypeScript Recognizer Enhancement

**Requirements**: R6
**Files to modify**: `src/codegiraffe/recognizers/typescript.py`
**Dependencies**: Phase 1 must complete first. Can run in parallel with Phase 2.
**Estimated new tests**: ~15

### 3.1 ES6 Import Parsing

Add regex patterns for TypeScript/JavaScript import statements:

```python
# Named imports: import { X, Y } from './path'
_TS_NAMED_IMPORT_RE = re.compile(
    r"""import\s+\{([^}]+)\}\s+from\s+['"]([^'"]+)['"]""",
)

# Default import: import X from './path'
_TS_DEFAULT_IMPORT_RE = re.compile(
    r"""import\s+(\w+)\s+from\s+['"]([^'"]+)['"]""",
)

# Namespace import: import * as X from './path'
_TS_NAMESPACE_IMPORT_RE = re.compile(
    r"""import\s+\*\s+as\s+\w+\s+from\s+['"]([^'"]+)['"]""",
)

# Dynamic import: import('./path') or require('./path')
_TS_DYNAMIC_IMPORT_RE = re.compile(
    r"""(?:import|require)\s*\(\s*['"]([^'"]+)['"]\s*\)""",
)
```

### 3.2 Internal Import Classification

An import is internal if:
- Path starts with `./` or `../` (relative import)
- Path starts with `@/` or `~/` (common path alias conventions)

External imports (bare specifiers like `react`, `express`) are excluded.

```python
def _is_internal_ts_import(import_path: str) -> bool:
    return import_path.startswith(("./", "../", "@/", "~/"))
```

### 3.3 Import Path to Module Path Conversion

Convert TypeScript import paths to dotted module paths:

```python
def _ts_import_to_module_path(import_path: str, current_file: Path) -> str:
    """Convert a TS import path to a dotted module path."""
    if import_path.startswith("./") or import_path.startswith("../"):
        # Resolve relative to current file
        resolved = (current_file.parent / import_path).resolve()
        # Strip extension, convert separators
        stem = str(resolved).rstrip("/")
        for ext in (".ts", ".tsx", ".js", ".jsx", ".mts", ".cts"):
            if stem.endswith(ext):
                stem = stem[:-len(ext)]
                break
        # Convert to dotted path relative to project
        # (actual resolution handled by _file_to_module_path_universal)
    return import_path.replace("/", ".").lstrip(".")
```

### 3.4 Extends/Implements Detection

Add regex patterns for TypeScript class inheritance:

```python
# class X extends Y
_TS_EXTENDS_RE = re.compile(
    r"""class\s+(\w+)\s+extends\s+(\w+)""",
)

# class X implements Y, Z
_TS_IMPLEMENTS_RE = re.compile(
    r"""class\s+(\w+)\s+implements\s+([\w,\s]+)""",
)
```

Return `ImplementationInfo` for each detected relationship:

```python
implementations: list[ImplementationInfo] = []
for match in _TS_EXTENDS_RE.finditer(content):
    implementations.append(ImplementationInfo(
        child_class=match.group(1),
        parent_class=match.group(2),
        file_path=str(file_path),
    ))
for match in _TS_IMPLEMENTS_RE.finditer(content):
    child = match.group(1)
    parents = [p.strip() for p in match.group(2).split(",")]
    for parent in parents:
        implementations.append(ImplementationInfo(
            child_class=child,
            parent_class=parent,
            file_path=str(file_path),
        ))
```

### Phase 3 Test Plan

- Test named import parsing (`import { X, Y } from './path'`)
- Test default import parsing (`import X from './path'`)
- Test namespace import parsing (`import * as X from './path'`)
- Test dynamic import parsing (`import('./path')`)
- Test internal vs external classification
- Test extends detection (single inheritance)
- Test implements detection (single and multiple interfaces)
- Test combined extends + implements (`class X extends Y implements Z`)
- Test full TS file scan produces module + contains + imports + implements edges

---

## Phase 4: Remaining Recognizers

**Requirements**: R7, R8, R9, R10, R11, R12
**Files to modify**: All recognizer files in `src/codegiraffe/recognizers/`
**Dependencies**: Phase 1 must complete first. Can run in parallel with Phases 2, 3.
**Estimated new tests**: ~40 (across 6 recognizers)

Each recognizer gets import parsing and inheritance detection appropriate to its language. The recognizers can be implemented in parallel.

### 4.1 Rust Recognizer (`rust.py`)

**Import parsing**:
```python
# use crate::module::Symbol
_RS_USE_CRATE_RE = re.compile(r'use\s+crate::(\S+?)(?:\s*;|$)', re.MULTILINE)
# use super::Symbol
_RS_USE_SUPER_RE = re.compile(r'use\s+super::(\S+?)(?:\s*;|$)', re.MULTILINE)
# use self::Symbol
_RS_USE_SELF_RE = re.compile(r'use\s+self::(\S+?)(?:\s*;|$)', re.MULTILINE)
```

Internal imports: `crate::`, `super::`, `self::` prefixes are always internal. Convert `crate::module::sub` to `module.sub` dotted path.

**Inheritance (trait implementations)**:
```python
# impl Trait for Struct
_RS_IMPL_TRAIT_RE = re.compile(r'impl\s+(\w+)\s+for\s+(\w+)')
```

Returns `ImplementationInfo(child_class=struct_name, parent_class=trait_name)`.

**Tests**: ~7 tests (use statements, crate/super/self, trait impl, full scan)

### 4.2 Java Recognizer (`java.py`)

**Import parsing**:
```python
# import com.project.package.Class;
_JAVA_IMPORT_RE = re.compile(r'import\s+([\w.]+)\s*;', re.MULTILINE)
```

Internal import classification: An import is internal if it starts with the project's base package. Detect the base package from the first `package` declaration seen in scanned files. The recognizer stores the package prefix.

For initial implementation, use heuristic: if the import path's top-level package matches a package seen in other scanned files, it's internal.

**Inheritance**:
```python
# class X extends Y
_JAVA_EXTENDS_RE = re.compile(r'class\s+(\w+)\s+extends\s+(\w+)')
# class X implements Y, Z
_JAVA_IMPLEMENTS_RE = re.compile(r'class\s+(\w+)\s+implements\s+([\w,\s]+)')
```

**Tests**: ~7 tests (import parsing, internal classification, extends, implements, full scan)

### 4.3 C# Recognizer (`csharp.py`)

**Import parsing**:
```python
# using Namespace.SubNamespace;
_CS_USING_RE = re.compile(r'using\s+([\w.]+)\s*;', re.MULTILINE)
```

Internal classification: Match against namespace prefixes seen in the project. Use heuristic: if the using's root namespace matches any namespace declaration in scanned files, it's internal.

**Inheritance**:
```python
# class X : BaseClass, IInterface
_CS_INHERITANCE_RE = re.compile(r'class\s+(\w+)\s*:\s*([\w\s,<>]+?)(?:\s*\{|\s*where)')
```

Parse the base list, split by comma, and return `ImplementationInfo` for each.

**Tests**: ~6 tests (using parsing, inheritance with interfaces, full scan)

### 4.4 C/C++ Recognizer (`cpp.py`)

**Import parsing**:
The CppRecognizer already detects `#include "local.h"` directives and creates `depends_on` edges. Extend to also return `ImportInfo`:

```python
# Already exists: _CPP_INCLUDE_RE = re.compile(r'#include\s+"([^"]+)"')
# Convert include path to module path: "path/file.h" -> "path.file"
```

Only quoted includes (`"..."`) are internal; angle-bracket includes (`<...>`) are system/external.

**Inheritance**:
```python
# class X : public Y, private Z
_CPP_INHERITANCE_RE = re.compile(
    r'class\s+(\w+)\s*:\s*((?:(?:public|private|protected)\s+\w+\s*,?\s*)+)',
)
```

Parse the inheritance list, extract class names after access specifiers.

**Tests**: ~6 tests (include -> ImportInfo, class inheritance, full scan)

### 4.5 PHP Recognizer (`php.py`)

**Import parsing**:
```python
# use App\Models\User;
_PHP_USE_RE = re.compile(r'use\s+([\w\\]+)\s*;', re.MULTILINE)
# namespace App\Models;
_PHP_NAMESPACE_RE = re.compile(r'namespace\s+([\w\\]+)\s*;', re.MULTILINE)
```

Internal classification: Match the `use` statement's root namespace against the project's root namespace (detected from `namespace` declarations in scanned files or from `composer.json` autoload config).

Convert `App\Models\User` to `App.Models.User` dotted path.

**Inheritance**:
```python
# class X extends Y
_PHP_EXTENDS_RE = re.compile(r'class\s+(\w+)\s+extends\s+(\w+)')
# class X implements Y, Z
_PHP_IMPLEMENTS_RE = re.compile(r'class\s+(\w+)\s+implements\s+([\w,\s]+)')
```

**Tests**: ~7 tests (use parsing, namespace detection, extends, implements, full scan)

### 4.6 Ruby Recognizer (`ruby.py`)

**Import parsing**:
```python
# require_relative 'path/to/file'
_RB_REQUIRE_RELATIVE_RE = re.compile(r"require_relative\s+['\"]([^'\"]+)['\"]")
# require 'app/models/user'
_RB_REQUIRE_RE = re.compile(r"require\s+['\"]([^'\"]+)['\"]")
```

`require_relative` is always internal. Plain `require` is internal if the path matches a project file.

Convert `path/to/file` to `path.to.file` dotted path.

**Inheritance**:
```python
# class X < Y (already detected by RubyRecognizer for ActiveRecord, extend for general case)
_RB_INHERITANCE_RE = re.compile(r'class\s+(\w+)\s*<\s*(\w+(?:::\w+)*)')
```

Filter out known framework base classes (`ApplicationRecord`, `ActiveRecord::Base`) from `ImplementationInfo` — these are external.

**Tests**: ~6 tests (require_relative, require, class inheritance, full scan)

---

## Phase 5: Test File Patterns

**Requirements**: R13
**Files to modify**: `src/codegiraffe/scanner.py`
**Dependencies**: None (can run in parallel with Phases 2-4)
**Estimated new tests**: ~15

### 5.1 Language-Specific Test File Detection

Extend `_is_test_file()` to handle all languages by checking the file extension first:

```python
# Language-specific test file patterns
_TEST_PATTERNS: dict[str, list[str]] = {
    ".go": ["_test.go"],                          # *_test.go
    ".ts": [".test.ts", ".spec.ts"],              # *.test.ts, *.spec.ts
    ".tsx": [".test.tsx", ".spec.tsx"],            # *.test.tsx, *.spec.tsx
    ".mts": [".test.mts", ".spec.mts"],
    ".cts": [".test.cts", ".spec.cts"],
    ".java": ["Test.java", "Tests.java"],         # *Test.java, *Tests.java
    ".cs": ["Tests.cs", "Test.cs"],               # *Tests.cs, *Test.cs
    ".cpp": ["_test.cpp", "_test.cc"],            # *_test.cpp, *_test.cc
    ".c": ["_test.c"],                            # *_test.c
    ".cxx": ["_test.cxx"],
    ".php": ["Test.php"],                         # *Test.php
    ".rb": ["_test.rb", "_spec.rb"],              # *_test.rb, *_spec.rb
}

# Language-specific test directory names
_TEST_DIRS_EXTENDED: frozenset[str] = frozenset({
    "tests", "test",          # Universal + Python
    "__tests__",              # JavaScript/TypeScript convention
    "spec",                   # Ruby RSpec convention
})
```

### 5.2 Extend `_is_test_file()`

```python
def _is_test_file(file_path: Path) -> bool:
    """Return True if *file_path* looks like a test file for any language."""
    name = file_path.name
    suffix = file_path.suffix.lower()

    # Python-specific patterns (preserved from v0.4.0)
    if suffix in (".py", ".pyi"):
        if name == "conftest.py":
            return True
        if name.startswith("test_") and name.endswith(".py"):
            return True
        if name.endswith("_test.py"):
            return True

    # Language-specific suffix patterns
    patterns = _TEST_PATTERNS.get(suffix, [])
    for pattern in patterns:
        if name.endswith(pattern):
            return True

    # C/C++ prefix pattern: test_*.cpp, test_*.c
    if suffix in (".c", ".cpp", ".cc", ".cxx", ".h", ".hpp"):
        if name.startswith("test_"):
            return True

    return False
```

### 5.3 Extend `_is_in_test_dir()`

```python
def _is_in_test_dir(path: Path) -> bool:
    """Return True if any component of *path* is a test directory."""
    for part in path.parts:
        if part in _TEST_DIRS_EXTENDED:
            return True
    return False
```

Also add Java-specific: `src/test/` directory detection (common Maven/Gradle layout):

```python
    # Java: src/test/ directory
    parts = path.parts
    for i, part in enumerate(parts):
        if part == "src" and i + 1 < len(parts) and parts[i + 1] == "test":
            return True
```

### Phase 5 Test Plan

- Test Go test file detection (`*_test.go`)
- Test TypeScript test file detection (`*.test.ts`, `*.spec.ts`)
- Test TypeScript `__tests__/` directory detection
- Test Java test file detection (`*Test.java`, `*Tests.java`, `src/test/`)
- Test C# test file detection (`*Test.cs`, `*Tests.cs`)
- Test C/C++ test file detection (`*_test.cpp`, `test_*.c`)
- Test PHP test file detection (`*Test.php`, `tests/`)
- Test Ruby test file detection (`*_test.rb`, `*_spec.rb`, `spec/`)
- Test Rust `tests/` directory detection
- Test that `include_tests=True` tags non-Python test files with `source: test`
- Test that `include_tests=False` (default) excludes non-Python test files

---

## Phase 6: Polish & Verification

**Requirements**: R14, Success Metrics
**Files to modify**: `CLAUDE.md`, `pyproject.toml` (version), `src/codegiraffe/__init__.py` (if version stored there)
**Dependencies**: Phases 1-5 must all complete first

### 6.1 Version Bump

Update version to `0.6.0` in:
- `pyproject.toml`
- `CLAUDE.md` (Active Technologies section, Recent Changes)

### 6.2 Self-Scan Dogfood

Run Code Giraffe against itself and verify:
- All Python files produce module nodes + contains + imports edges (same as v0.5.0)
- Edge/node ratio >= 0.5
- Zero regressions from v0.5.0 self-scan results

### 6.3 Multi-Language Project Test

Create a synthetic test fixture directory containing files in all 9 languages with known import and inheritance patterns. Run `scan_project()` against it and verify:
- Module nodes created for every file
- Contains edges connect modules to entities
- Import edges created for internal imports
- Implements edges created for inheritance/implementation
- External imports filtered out
- Test files excluded by default

### 6.4 Full Test Suite

Run the complete test suite and verify:
- All 566 existing tests pass
- ~100+ new tests pass
- Total test count: 660+

### 6.5 Documentation Update

Update `CLAUDE.md`:
- Recent Changes section: add v0.6.0 entry
- Code Style section: mention `ImportInfo`, `ImplementationInfo`, `set_project_root()`
- Key Patterns section: mention universal module node creation, language-specific test patterns

---

## Dependency Graph and Parallelism

```
Phase 1 (Core Pipeline)
    |
    ├──> Phase 2 (Go)          ─┐
    ├──> Phase 3 (TypeScript)   │
    ├──> Phase 4.1 (Rust)       │
    ├──> Phase 4.2 (Java)       ├──> Phase 6 (Polish)
    ├──> Phase 4.3 (C#)         │
    ├──> Phase 4.4 (C/C++)      │
    ├──> Phase 4.5 (PHP)        │
    ├──> Phase 4.6 (Ruby)       │
    └──> Phase 5 (Test Patterns)┘
```

**Phase 1** is the only serial dependency. Once it completes, **Phases 2, 3, 4.1-4.6, and 5 can all run in parallel** since they modify different files with no interdependencies.

**Phase 6** waits for all other phases to complete.

### Recommended Implementation Order

If implementing sequentially (single developer):

1. **Phase 1** (Core Pipeline) -- foundation, ~30 tests
2. **Phase 5** (Test Patterns) -- small, independent, quick win
3. **Phase 2** (Go) -- highest priority per user feedback
4. **Phase 3** (TypeScript) -- second most common language
5. **Phase 4.2** (Java) -- straightforward import/inheritance
6. **Phase 4.1** (Rust) -- `use` + `impl Trait for` is clean
7. **Phase 4.3** (C#) -- similar to Java
8. **Phase 4.5** (PHP) -- similar to Java
9. **Phase 4.6** (Ruby) -- simple inheritance model
10. **Phase 4.4** (C/C++) -- already has partial include support
11. **Phase 6** (Polish) -- version bump, dogfood, docs

---

## Risk Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| Python scan regression | HIGH | Run all 566 existing tests after every change. Universal path runs before Python-specific path; Python path only adds edges not already present |
| go.mod not found | LOW | Graceful fallback: if go.mod missing, no internal imports detected (same as v0.5.0 behavior). Log warning |
| False-positive interface matching in Go | MEDIUM | Require ALL interface methods to be present on struct (subset match). Same-file only for v0.6.0 |
| Recognizer protocol break | HIGH | `imports` and `implementations` are optional dataclass fields with empty-list defaults. No protocol change needed |
| Performance regression from per-file result collection | LOW | Per-file results stored as references, not copies. Memory overhead is one dict entry per scanned file |
| Cross-language module ID collisions | MEDIUM | Module IDs include the full dotted path from project root, making collisions unlikely. Different languages in different directories |

## Complexity Tracking

> No constitution violations requiring justification. All changes are additive and within existing patterns. The ScanResult extension is the only cross-cutting change, and it uses default values for full backward compatibility.

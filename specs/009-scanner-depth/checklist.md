# Validation Checklist: Scanner Depth (v0.9.0)

Based on: ./specs/009-scanner-depth/spec.md, ./specs/009-scanner-depth/plan.md

---

## Data Model Correctness

### CallInfo

- [ ] `CallInfo` dataclass exists in `src/codegiraffe/scanner.py`
- [ ] Field `caller: str` -- name of the calling function/method
- [ ] Field `callee: str` -- name of the called function/method
- [ ] Field `receiver: str = ""` -- receiver/object if method call (e.g., "Store")
- [ ] Field `file_path: str = ""` -- relative path where the call occurs
- [ ] Field `style: str = "direct"` -- one of "direct", "method", "static", "constructor"
- [ ] Default construction `CallInfo(caller="a", callee="b")` works with all defaults

### InterfaceInfo

- [ ] `InterfaceInfo` dataclass exists in `src/codegiraffe/scanner.py`
- [ ] Field `name: str` -- interface name
- [ ] Field `methods: list[str] = field(default_factory=list)` -- required method names
- [ ] Field `file_path: str = ""` -- where the interface is defined
- [ ] Default construction `InterfaceInfo(name="Foo")` works with empty methods list

### MethodSetEntry

- [ ] `MethodSetEntry` dataclass exists in `src/codegiraffe/scanner.py`
- [ ] Field `struct_name: str` -- struct/class that has this method
- [ ] Field `method_name: str` -- method name
- [ ] Field `file_path: str = ""` -- where the method is defined

### ScanResult Extension

- [ ] `ScanResult` has `calls: list[CallInfo]` field with `field(default_factory=list)` default
- [ ] `ScanResult` has `interfaces: list[InterfaceInfo]` field with `field(default_factory=list)` default
- [ ] `ScanResult` has `method_sets: list[MethodSetEntry]` field with `field(default_factory=list)` default
- [ ] `ScanResult()` (no args) creates empty lists for all three new fields
- [ ] `ScanResult.merge()` extends `calls` from other `ScanResult`
- [ ] `ScanResult.merge()` extends `interfaces` from other `ScanResult`
- [ ] `ScanResult.merge()` extends `method_sets` from other `ScanResult`

---

## Scanner Pipeline Integration

### Inference Function Placement

- [ ] `_infer_interface_satisfaction()` is called BEFORE `_infer_inheritance_edges_universal()` in `scan_project()`
- [ ] `_infer_call_edges()` is called AFTER `_infer_inheritance_edges()` in `scan_project()`
- [ ] `_infer_call_edges()` is called BEFORE `_infer_contract_edges()` in `scan_project()`
- [ ] Pipeline order is: imports -> cross-file -> class_registry -> interface_satisfaction -> inheritance_universal -> inheritance -> call_edges -> contracts

### Per-File Collection

- [ ] `scan_project()` collects `file_calls` from per-file `ScanResult` objects
- [ ] `scan_project()` collects `file_interfaces` from per-file `ScanResult` objects
- [ ] `scan_project()` collects `file_method_sets` from per-file `ScanResult` objects
- [ ] Merged `ScanResult` includes all three new fields in its construction

### _infer_interface_satisfaction()

- [ ] Collects all `InterfaceInfo` records from `per_file_results` across all files
- [ ] Collects all `MethodSetEntry` records grouped by `struct_name` into `dict[str, set[str]]`
- [ ] Checks whether struct method set is a superset of interface required methods
- [ ] Emits `ImplementationInfo` records (mutates `result.implementations` in place)
- [ ] Does NOT create edges directly -- delegates to `_infer_inheritance_edges_universal`
- [ ] Avoids duplicating already-existing `ImplementationInfo` entries
- [ ] Handles empty interface methods list correctly (does not match everything)

### _infer_call_edges()

- [ ] Builds symbol registry mapping function/method names to node IDs
- [ ] Builds class registry mapping class/struct names to node IDs
- [ ] Processes all `CallInfo` records from `per_file_results`
- [ ] Resolves caller and callee to graph node IDs via `_resolve_call_participant()`
- [ ] Creates `calls` edges with metadata: `inferred`, `caller`, `callee`, `style`
- [ ] Deduplicates edges: same (source, target, calls) triple only once
- [ ] Skips self-loops (caller_id == callee_id)
- [ ] Is a no-op when no `CallInfo` records exist (backward compat)

### _resolve_call_participant()

- [ ] Checks method_node_registry for exact match first
- [ ] Checks symbol_registry for exact match
- [ ] For dotted names (e.g., "Store.Save"): splits on dot, resolves parent via class_registry
- [ ] Creates demand-driven method node when class exists but method node doesn't
- [ ] Returns `None` for unresolvable names (external calls, stdlib)
- [ ] Registers newly created method nodes in both method_node_registry and symbol_registry

---

## Per-Language Call Detection

### Go (Priority -- Full Detection)

- [ ] Detects method calls: `receiver.Method(args)` -> `CallInfo(style="method")`
- [ ] Detects plain exported function calls: `FuncName(args)` -> `CallInfo(style="direct")`
- [ ] Filters stdlib packages: `fmt`, `log`, `os`, `io`, `strings`, etc. excluded
- [ ] Determines enclosing function context: `func (a *App) Update()` -> `caller="App.Update"`
- [ ] Emits `InterfaceInfo` records from interface declarations
- [ ] Emits `MethodSetEntry` records from struct method receivers
- [ ] Multiple calls in one function produce multiple `CallInfo` records

### Python (Priority -- Full Detection)

- [ ] Detects `self.method()` calls -> `CallInfo(style="method", receiver="self")`
- [ ] Detects `ClassName()` constructor calls -> `CallInfo(style="constructor")`
- [ ] Detects `obj.method()` calls -> `CallInfo(style="method", receiver="obj")`
- [ ] Filters builtins: `print`, `len`, `range`, `int`, `str`, etc. excluded
- [ ] Determines enclosing function context from `def`/`async def`
- [ ] Skips private methods (single underscore prefix, except `__init__`)

### TypeScript (Priority -- Full Detection)

- [ ] Detects `this.method()` calls -> `CallInfo(style="method")`
- [ ] Detects `obj.method()` calls -> `CallInfo(style="method")`
- [ ] Detects `new ClassName()` constructor calls -> `CallInfo(style="constructor")`
- [ ] Filters builtins: `console`, `JSON`, `Math`, `Object`, `Array`, etc. excluded

### Java (Basic Detection)

- [ ] Detects `obj.method()` calls
- [ ] Detects `ClassName.staticMethod()` calls
- [ ] Detects `new ClassName()` constructor calls
- [ ] Blocklist includes: `System`, `Arrays`, `Collections`, `Objects`, `Math`, `String`

### Rust (Basic Detection)

- [ ] Detects `obj.method()` calls
- [ ] Detects `Module::function()` calls
- [ ] Blocklist includes: `std`, `println`, `eprintln`, `format`, `vec`, `panic`

### C# (Basic Detection)

- [ ] Detects `obj.Method()` calls
- [ ] Detects `ClassName.StaticMethod()` calls
- [ ] Detects `new ClassName()` constructor calls
- [ ] Blocklist includes: `Console`, `Math`, `String`, `Convert`, `Enum`

### PHP (Basic Detection)

- [ ] Detects `$obj->method()` calls
- [ ] Detects `ClassName::staticMethod()` calls
- [ ] Detects `new ClassName()` constructor calls
- [ ] Blocklist includes common builtins (`array_*`, `str_*`, `is_*`, etc.)

### Ruby (Basic Detection)

- [ ] Detects `obj.method()` calls
- [ ] Detects `ClassName.new` constructor calls
- [ ] Blocklist includes: `puts`, `print`, `p`, `require`, `raise`

### C++ (Basic Detection)

- [ ] Detects `obj.method()` and `obj->method()` calls
- [ ] Detects `namespace::function()` calls
- [ ] Detects `new ClassName()` constructor calls
- [ ] Blocklist includes: `std`, `cout`, `cin`, `endl`, `printf`, `malloc`, `free`

---

## Go Interface Satisfaction Detection

- [ ] Cross-file matching: interface in file1 + struct with matching method set in file2 -> `ImplementationInfo` emitted
- [ ] Method set superset check: struct must have ALL interface methods (superset allowed)
- [ ] Exact match works: struct has exactly the interface's methods
- [ ] Subset fails: struct missing any required method -> no match
- [ ] Does not duplicate: existing same-file `ImplementationInfo` not duplicated
- [ ] Multiple implementors: two structs satisfying same interface both get `ImplementationInfo`
- [ ] Multiple interfaces: one struct satisfying two interfaces gets two `ImplementationInfo`
- [ ] Empty interface: interface with no methods does not produce matches
- [ ] Resulting `ImplementationInfo` records are processed into `implements` edges by `_infer_inheritance_edges_universal`

---

## Method Node Creation (Demand-Driven Only)

- [ ] Method nodes are ONLY created when they participate in a call-graph edge
- [ ] Method node ID format: `service:{ParentName}.{MethodName}`
- [ ] Method node type: `NodeType.SERVICE` ("service")
- [ ] Method node `metadata["kind"]` == `"method"`
- [ ] Method node `metadata["parent"]` is set to the parent class/struct name
- [ ] Method node `metadata["method_name"]` is set to the method name
- [ ] A `contains` edge is created from parent class node to method node
- [ ] Method nodes are deduplicated: same method referenced from multiple callers -> one node
- [ ] No exhaustive method node creation: file with 50 methods but only 3 in calls -> 3 method nodes

---

## Backward Compatibility

- [ ] All 793 existing tests pass unchanged (zero regression)
- [ ] `ScanResult()` with no args still works (all new fields have defaults)
- [ ] Recognizers that don't implement call detection return empty `calls` list
- [ ] `_infer_call_edges()` is a no-op when no `CallInfo` records exist
- [ ] `_infer_interface_satisfaction()` is a no-op when no `InterfaceInfo`/`MethodSetEntry` exist
- [ ] Projects without detectable calls produce identical graphs to v0.8.0
- [ ] No schema changes: `EdgeType.CALLS` already exists in schema.py (just now populated)
- [ ] No new MCP tools: all 25 tools unchanged
- [ ] No new required dependencies

---

## Edge Quality (calls Edges)

- [ ] Edge type is `EdgeType.CALLS.value` ("calls")
- [ ] Edge `source` is the caller node ID
- [ ] Edge `target` is the callee node ID
- [ ] Edge `metadata["inferred"]` is `True`
- [ ] Edge `metadata["caller"]` contains the original caller name string
- [ ] Edge `metadata["callee"]` contains the original callee name string
- [ ] Edge `metadata["style"]` is one of "direct", "method", "static", "constructor"
- [ ] No duplicate edges: same (source, target, "calls") triple appears only once
- [ ] No self-loop edges: caller and callee resolve to different node IDs
- [ ] External/unresolvable calls are filtered out (no dangling references)
- [ ] Symbol registry filtering is the primary mechanism (not just blocklists)

---

## Integration with Existing Tools

### blast_radius

- [ ] `codegiraffe_blast_radius` for a callee node shows callers in downstream dependencies
- [ ] `calls` edges are traversed as part of blast radius analysis
- [ ] Impact severity correctly accounts for call-graph relationships

### context_for

- [ ] `codegiraffe_context_for` returns richer results when `calls` edges connect more nodes
- [ ] Call-graph connectivity improves relevance scoring for task-related queries

### risk_assessment

- [ ] `codegiraffe_risk_assessment` incorporates `calls` edge degree into risk scoring
- [ ] Highly-called nodes score higher risk (more callers = more dependents)
- [ ] Method nodes with many callers are correctly identified as hotspots

### cycles

- [ ] `codegiraffe_cycles` can detect circular call chains (A calls B calls A)
- [ ] Cycles involving `calls` edges are reported alongside existing edge types

### hotspots

- [ ] `codegiraffe_hotspots` ranks nodes with many `calls` edges higher
- [ ] Method nodes participating in many calls appear as architectural hotspots

---

## Tree-Sitter AST Call Detection

- [ ] `GoASTRecognizer.recognize()` produces `CallInfo` records via tree-sitter queries
- [ ] `GoASTRecognizer._find_calls()` uses `_GO_CALL_QUERY` query constant
- [ ] `GoASTRecognizer._find_enclosing_func_ast()` walks tree-sitter parents correctly
- [ ] `PythonASTRecognizer.recognize()` produces `CallInfo` records
- [ ] `TypeScriptASTRecognizer.recognize()` produces `CallInfo` records
- [ ] AST stdlib filtering matches regex-mode stdlib filtering
- [ ] AST and regex modes produce compatible `CallInfo` results for same source file
- [ ] All AST tests use `@pytest.mark.skipif(not HAS_TREE_SITTER, ...)` to skip gracefully

---

## Interface/Implementation Edge Cases

- [ ] TypeScript: `class Foo implements Bar, Baz` produces 2 `ImplementationInfo` records
- [ ] TypeScript: `class Foo implements Bar<string>` strips generic -> `parent_class="Bar"`
- [ ] TypeScript: `class Foo extends Base implements Bar` produces both extends and implements
- [ ] Java: multi-interface `implements Foo, Bar` produces correct records
- [ ] C#: `class Foo : BaseClass, IInterface` distinguishes base class from interface

---

## Documentation

- [ ] `pyproject.toml` version bumped from `"0.8.0"` to `"0.9.0"`
- [ ] `CLAUDE.md` version line updated to 0.9.0
- [ ] `CLAUDE.md` test count updated to reflect new total (862+)
- [ ] `CLAUDE.md` Code Style section lists `CallInfo`, `InterfaceInfo`, `MethodSetEntry` data classes
- [ ] `CLAUDE.md` documents that `calls` edge type is now populated by the scanner
- [ ] `CLAUDE.md` Recent Changes entry added for v0.9.0
- [ ] `CLAUDE.md` scanner description updated to mention call-graph detection

---

## Implementation Quality

- [ ] Code follows existing project patterns (data classes, inference functions, recognizer structure)
- [ ] Functions have clear docstrings explaining purpose and algorithm
- [ ] Error handling is defensive (empty lists, missing nodes, unresolvable names)
- [ ] No new imports of external packages (all stdlib or existing dependencies)
- [ ] Performance: no quadratic blowup in inference functions (use registries/dicts for lookup)
- [ ] No modification of schema.py (EdgeType.CALLS already exists)

---

## Test Coverage

- [ ] Phase 1: 9 tests -- data class fields, ScanResult defaults, merge behavior
- [ ] Phase 2: 24 tests -- per-language call detection (Go 8, Python 5, TypeScript 4, others 6+1)
- [ ] Phase 3: 26 tests -- inference pipeline (9), interface satisfaction (7), method nodes (5), integration (5)
- [ ] Phase 4: 5 tests -- AST call detection (Go, Python, TypeScript, stdlib filter, compat)
- [ ] Phase 5: 5 tests -- interface/implementation edge cases
- [ ] Total new tests: 69+
- [ ] Total tests (including existing): 862+
- [ ] All tests pass: `python -m pytest tests/ -v` exits with code 0

---

## Dogfood Validation

- [ ] Self-scan of CodeGiraffe project produces `calls` edges in the graph
- [ ] Self-scan correctly identifies cross-file calls within `src/codegiraffe/`
- [ ] No false positive `calls` edges to stdlib/third-party (filtered by symbol registry)
- [ ] Demand-driven method nodes appear only for methods that participate in detected calls
- [ ] Existing graph structure (nodes, imports, implements, contains, contracts) is unchanged

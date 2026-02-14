# Implementation Plan: Code Giraffe v0.9.0 -- Scanner Depth

## Overview

This plan deepens the scanner from structural pattern detection to behavioral
relationship extraction. It adds call-graph edges (`calls` edge type -- already
defined in `schema.py` but never populated by the scanner), cross-file Go
interface satisfaction, and demand-driven method-level nodes. No new MCP tools
are introduced; every existing tool (`context_for`, `blast_radius`,
`risk_assessment`, `cycles`, `hotspots`) automatically benefits from the richer
graph.

**Scope:** 6 phases, 12 source files modified, 2 new test files, 0 new MCP
tools (25 total unchanged), 60+ new tests (853+ total).

---

## Architecture Overview

### How the New Features Fit

The scanner pipeline in `scan_project()` (scanner.py:1341) follows a clear
pattern:

```
scan_project()
  |-- per-file: recognizer.recognize() -> ScanResult
  |-- merge all per-file results
  |-- _infer_import_edges_universal()           # existing (line 1490)
  |-- _infer_cross_file_edges()                 # existing (line 1493)
  |-- _infer_import_edges()                     # existing (line 1494)
  |-- class_registry construction               # existing (line 1497)
  |-- _infer_inheritance_edges_universal()       # existing (line 1502)
  |-- _infer_inheritance_edges()                 # existing (line 1505)
  |-- _infer_contract_edges()                   # existing (line 1508)
  |-- return merged
```

v0.9.0 inserts two new inference steps and extends the per-file data:

```
scan_project()
  |-- per-file: recognizer.recognize() -> ScanResult with nodes, edges, imports,
  |                                        implementations, calls (NEW),
  |                                        interfaces (NEW), method_sets (NEW)
  |-- merge all per-file results
  |-- _infer_import_edges_universal()           # existing
  |-- _infer_cross_file_edges()                 # existing
  |-- _infer_import_edges()                     # existing
  |-- class_registry construction               # existing
  |-- _infer_interface_satisfaction()            # NEW (before inheritance)
  |-- _infer_inheritance_edges_universal()       # existing
  |-- _infer_inheritance_edges()                 # existing
  |-- _infer_call_edges()                       # NEW (after inheritance, before contracts)
  |-- _infer_contract_edges()                   # existing
  |-- return merged
```

### Key Architectural Constraints

1. **No schema changes.** `EdgeType.CALLS` already exists (schema.py:29).
   Method-level nodes use the existing `NodeType.SERVICE` with
   `metadata.kind = "method"`.
2. **No new MCP tools.** All improvements are scanner-internal.
3. **Backward compatible.** New `ScanResult` fields have
   `field(default_factory=list)` defaults. Recognizers that don't implement
   call detection return empty lists. The new inference functions are no-ops
   when no data exists.
4. **Constitution compliance.** Test-First (Principle VI) is non-negotiable.
   Every phase writes tests before or alongside implementation.

---

## Phase 1: Data Model Extension (Serial -- Must Go First)

### Rationale

All subsequent phases depend on the new data classes and `ScanResult` fields.
This phase is small and foundational.

### Files to Modify

#### `src/codegiraffe/scanner.py`

##### 1. New data class: `CallInfo`

**Insert after:** `ImplementationInfo` (line 41)

```python
@dataclass
class CallInfo:
    """Structured call-site information returned by recognizers."""

    caller: str          # Name of the calling function/method
    callee: str          # Name of the called function/method
    receiver: str = ""   # Receiver/object if method call (e.g., "Store")
    file_path: str = ""  # Relative path where the call occurs
    style: str = "direct"  # "direct" | "method" | "static" | "constructor"
```

##### 2. New data class: `InterfaceInfo`

**Insert after:** `CallInfo`

```python
@dataclass
class InterfaceInfo:
    """Interface declaration with its required method signatures."""

    name: str                    # Interface name
    methods: list[str] = field(default_factory=list)  # Required method names
    file_path: str = ""          # Where the interface is defined
```

##### 3. New data class: `MethodSetEntry`

**Insert after:** `InterfaceInfo`

```python
@dataclass
class MethodSetEntry:
    """A single method belonging to a struct/class method set."""

    struct_name: str             # Struct/class that has this method
    method_name: str             # Method name
    file_path: str = ""          # Where the method is defined
```

##### 4. Extend `ScanResult`

**Modify `ScanResult`** (line 49-74):

Add three new fields after `implementations`:

```python
@dataclass
class ScanResult:
    """Aggregated output from scanning: discovered nodes and edges."""

    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    imports: list[ImportInfo] = field(default_factory=list)
    implementations: list[ImplementationInfo] = field(default_factory=list)
    calls: list[CallInfo] = field(default_factory=list)
    interfaces: list[InterfaceInfo] = field(default_factory=list)
    method_sets: list[MethodSetEntry] = field(default_factory=list)
```

##### 5. Extend `ScanResult.merge()`

**Modify `merge()`** (line 58-74):

Add three `extend` calls at the end, after the existing
`self.implementations.extend(other.implementations)`:

```python
        self.calls.extend(other.calls)
        self.interfaces.extend(other.interfaces)
        self.method_sets.extend(other.method_sets)
```

##### 6. Extend per-file collection in `scan_project()`

**Modify `scan_project()`** (around line 1451-1458):

Add collection variables for the new fields alongside existing ones:

```python
        file_calls: list[CallInfo] = []
        file_interfaces: list[InterfaceInfo] = []
        file_method_sets: list[MethodSetEntry] = []
```

And extend the per-recognizer loop to collect them:

```python
            file_calls.extend(file_result.calls)
            file_interfaces.extend(file_result.interfaces)
            file_method_sets.extend(file_result.method_sets)
```

And include them in the `ScanResult` construction:

```python
        combined = ScanResult(
            nodes=file_nodes,
            edges=file_edges,
            imports=file_imports,
            implementations=file_implementations,
            calls=file_calls,
            interfaces=file_interfaces,
            method_sets=file_method_sets,
        )
```

### Tests

#### `tests/test_scanner.py` (modify existing)

Add to existing test module or create a new test class:

- `test_callinfo_dataclass_fields` -- Verify `CallInfo` has caller, callee,
  receiver, file_path, style fields with correct defaults.
- `test_interfaceinfo_dataclass_fields` -- Verify `InterfaceInfo` has name,
  methods, file_path fields with correct defaults.
- `test_methodsetentry_dataclass_fields` -- Verify `MethodSetEntry` has
  struct_name, method_name, file_path fields.
- `test_scanresult_has_calls_field` -- Verify `ScanResult()` has empty `calls`
  list by default.
- `test_scanresult_has_interfaces_field` -- Verify `ScanResult()` has empty
  `interfaces` list by default.
- `test_scanresult_has_method_sets_field` -- Verify `ScanResult()` has empty
  `method_sets` list by default.
- `test_scanresult_merge_extends_calls` -- Merge two ScanResults, verify calls
  are combined.
- `test_scanresult_merge_extends_interfaces` -- Merge two ScanResults, verify
  interfaces are combined.
- `test_scanresult_merge_extends_method_sets` -- Merge two ScanResults, verify
  method_sets are combined.

**Test count:** +9 tests

---

## Phase 2: Recognizer Call Detection (Depends on Phase 1)

### Rationale

Each recognizer needs to extract function/method calls and return them as
`CallInfo` records. The three priority languages are Go, Python, and
TypeScript. The remaining six languages get basic call detection.

Call detection is intentionally noisy at the recognizer level -- the inference
pipeline in Phase 3 filters to intra-project calls using a symbol registry.
Recognizers only need to skip obvious stdlib/builtin calls to reduce noise.

### Files to Modify

#### `src/codegiraffe/recognizers/go.py`

##### 1. New regex constants

**Insert after:** `_GO_INTERFACE_METHOD_RE` (line 115)

```python
# --- Call detection (v0.9.0) ---

# Method call: receiver.Method(args)
_GO_FUNC_CALL_RE = re.compile(r'(\w+)\.(\w+)\s*\(')

# Plain function call: FunctionName(args)  -- uppercase start = exported Go func
_GO_PLAIN_CALL_RE = re.compile(r'(?<!\.)(\b[A-Z]\w+)\s*\(')

# Enclosing function context: func (r *Type) Name( or func Name(
_GO_FUNC_DEF_RE = re.compile(r'func\s+(?:\(\w+\s+\*?(\w+)\)\s+)?(\w+)\s*\(')

# Go stdlib packages to skip (common ones that create noise)
_GO_STDLIB_PACKAGES = frozenset({
    "fmt", "log", "os", "io", "strings", "strconv", "bytes", "errors",
    "context", "sync", "time", "math", "sort", "regexp", "path", "filepath",
    "encoding", "json", "xml", "csv", "bufio", "flag", "testing", "reflect",
    "runtime", "syscall", "unsafe", "unicode", "net", "http", "url",
    "crypto", "hash", "html", "mime", "text", "debug", "go",
})
```

##### 2. Extend `GoRecognizer.recognize()`

**Modify `recognize()`** (line 192-532):

After the interface implementation detection section (around line 525) and
before the `return ScanResult(...)`, add call detection logic:

```python
        # --- Call detection (v0.9.0) ---
        calls: list[CallInfo] = []

        # Build function context: map line numbers to enclosing function names
        lines = content.split('\n')
        func_ranges: list[tuple[int, int, str, str]] = []  # (start, end, func_name, receiver_type)
        # ... (parse function defs to build a line->function mapping)

        # Detect method calls: receiver.Method(args)
        for match in _GO_FUNC_CALL_RE.finditer(content):
            receiver_name = match.group(1)
            method_name = match.group(2)
            if receiver_name.lower() in _GO_STDLIB_PACKAGES:
                continue
            # Determine enclosing function from line position
            line_num = content[:match.start()].count('\n')
            caller = _find_enclosing_func(func_ranges, line_num)
            if caller:
                calls.append(CallInfo(
                    caller=caller,
                    callee=method_name,
                    receiver=receiver_name,
                    file_path=rel_path,
                    style="method",
                ))

        # Detect plain exported function calls: FuncName(args)
        for match in _GO_PLAIN_CALL_RE.finditer(content):
            func_name = match.group(1)
            line_num = content[:match.start()].count('\n')
            caller = _find_enclosing_func(func_ranges, line_num)
            if caller and func_name != caller:  # skip recursion
                calls.append(CallInfo(
                    caller=caller,
                    callee=func_name,
                    receiver="",
                    file_path=rel_path,
                    style="direct",
                ))
```

Also emit `InterfaceInfo` and `MethodSetEntry` records alongside the existing
interface/struct detection, for cross-file resolution in Phase 3:

```python
        # --- Emit InterfaceInfo for cross-file resolution (v0.9.0) ---
        interface_infos: list[InterfaceInfo] = []
        for iface_name, methods in interface_methods.items():
            interface_infos.append(InterfaceInfo(
                name=iface_name,
                methods=sorted(methods),
                file_path=rel_path,
            ))

        # --- Emit MethodSetEntry for cross-file resolution (v0.9.0) ---
        method_set_entries: list[MethodSetEntry] = []
        for struct_name, methods in struct_methods.items():
            for method_name in methods:
                method_set_entries.append(MethodSetEntry(
                    struct_name=struct_name,
                    method_name=method_name,
                    file_path=rel_path,
                ))
```

Update the return statement to include the new fields:

```python
        return ScanResult(
            nodes=nodes, edges=edges, imports=imports,
            implementations=implementations,
            calls=calls,
            interfaces=interface_infos,
            method_sets=method_set_entries,
        )
```

##### 3. New helper function: `_find_enclosing_func`

**Insert as module-level function** after the regex constants:

```python
def _find_enclosing_func(
    func_ranges: list[tuple[int, int, str, str]],
    line_num: int,
) -> str:
    """Return the name of the function enclosing the given line number."""
    for start, end, func_name, receiver_type in func_ranges:
        if start <= line_num <= end:
            if receiver_type:
                return f"{receiver_type}.{func_name}"
            return func_name
    return ""
```

#### `src/codegiraffe/scanner.py` (PythonRecognizer)

##### 1. New regex constants

**Insert after:** `_IMPORT_RE` (around line 338):

```python
# --- Python call detection (v0.9.0) ---
# self.method() calls
_PY_SELF_CALL_RE = re.compile(r'self\.(\w+)\s*\(')
# ClassName() constructor calls (uppercase first letter)
_PY_CONSTRUCTOR_CALL_RE = re.compile(r'(?<!\.)([A-Z]\w+)\s*\(')
# obj.method() calls
_PY_METHOD_CALL_RE = re.compile(r'(\w+)\.(\w+)\s*\(')
# def/async def for enclosing function context
_PY_FUNC_DEF_RE = re.compile(r'(?:def|async\s+def)\s+(\w+)\s*\(')
# Python builtins to skip
_PY_BUILTINS = frozenset({
    "print", "len", "range", "int", "str", "float", "bool", "list", "dict",
    "set", "tuple", "type", "isinstance", "issubclass", "super", "property",
    "staticmethod", "classmethod", "enumerate", "zip", "map", "filter",
    "sorted", "reversed", "min", "max", "sum", "abs", "round", "open",
    "hasattr", "getattr", "setattr", "delattr", "callable", "iter", "next",
    "repr", "format", "id", "hash", "input", "vars", "dir", "help",
    "Exception", "ValueError", "TypeError", "KeyError", "IndexError",
    "AttributeError", "RuntimeError", "StopIteration", "NotImplementedError",
    "FileNotFoundError", "OSError", "IOError",
})
```

##### 2. Extend `PythonRecognizer.recognize()`

**Modify `recognize()`** (line 642-780):

After the edge inference section (line 775) and before `return ScanResult(...)`:

```python
        # --- Call detection (v0.9.0) ---
        calls: list[CallInfo] = []
        # Build line->function context from cleaned content
        # ... parse function defs to determine enclosing function

        # Detect self.method() calls
        for match in _PY_SELF_CALL_RE.finditer(cleaned):
            method_name = match.group(1)
            if method_name.startswith('_') and method_name != '__init__':
                continue  # skip private/dunder (except __init__)
            line_num = cleaned[:match.start()].count('\n')
            caller = _find_enclosing_py_func(func_defs, line_num)
            if caller:
                calls.append(CallInfo(
                    caller=caller, callee=method_name, receiver="self",
                    file_path=rel_path, style="method",
                ))

        # Detect ClassName() constructor calls
        for match in _PY_CONSTRUCTOR_CALL_RE.finditer(cleaned):
            class_name = match.group(1)
            if class_name in _PY_BUILTINS:
                continue
            line_num = cleaned[:match.start()].count('\n')
            caller = _find_enclosing_py_func(func_defs, line_num)
            if caller:
                calls.append(CallInfo(
                    caller=caller, callee=class_name, receiver="",
                    file_path=rel_path, style="constructor",
                ))

        # Detect obj.method() calls (excluding self, cls, builtins)
        for match in _PY_METHOD_CALL_RE.finditer(cleaned):
            obj_name = match.group(1)
            method_name = match.group(2)
            if obj_name in ("self", "cls", "super"):
                continue  # already handled above or not useful
            line_num = cleaned[:match.start()].count('\n')
            caller = _find_enclosing_py_func(func_defs, line_num)
            if caller:
                calls.append(CallInfo(
                    caller=caller, callee=method_name, receiver=obj_name,
                    file_path=rel_path, style="method",
                ))
```

Update the return statement:

```python
        return ScanResult(nodes=nodes, edges=edges, calls=calls)
```

#### `src/codegiraffe/recognizers/typescript.py`

##### 1. New regex constants

**Insert after:** `_TS_CLASS_IMPLEMENTS_RE`:

```python
# --- TypeScript call detection (v0.9.0) ---
# this.method() calls
_TS_THIS_CALL_RE = re.compile(r'this\.(\w+)\s*\(')
# obj.method() calls
_TS_METHOD_CALL_RE = re.compile(r'(\w+)\.(\w+)\s*\(')
# new ClassName() constructor calls
_TS_CONSTRUCTOR_CALL_RE = re.compile(r'new\s+(\w+)\s*[\(<]')
# function/method def context
_TS_FUNC_DEF_RE = re.compile(
    r'(?:(?:async\s+)?function\s+(\w+)|(\w+)\s*(?::\s*\w+)?\s*\([^)]*\)\s*(?::\s*\w+)?\s*\{|(\w+)\s*=\s*(?:async\s+)?\([^)]*\)\s*=>)'
)
# TS builtins/globals to skip
_TS_BUILTINS = frozenset({
    "console", "JSON", "Math", "Object", "Array", "String", "Number",
    "Boolean", "Date", "RegExp", "Error", "Promise", "Map", "Set",
    "WeakMap", "WeakSet", "Symbol", "parseInt", "parseFloat", "setTimeout",
    "setInterval", "clearTimeout", "clearInterval", "fetch", "require",
    "Buffer", "process",
})
```

##### 2. Extend `TypeScriptRecognizer.recognize()`

Add call detection following the same pattern as Go and Python:

- Detect `this.method()` calls -> `CallInfo(style="method")`
- Detect `obj.method()` calls -> `CallInfo(style="method")`
- Detect `new ClassName()` -> `CallInfo(style="constructor")`
- Filter out builtins via `_TS_BUILTINS`
- Return `calls` in the `ScanResult`

#### Other Recognizers (Java, Rust, C#, PHP, Ruby, C++)

Each recognizer gets basic call detection following the same pattern:

**Java** (`recognizers/java.py`):
- Detect `obj.method()` calls
- Detect `ClassName.staticMethod()` calls
- Detect `new ClassName()` constructor calls
- Blocklist: `System`, `Arrays`, `Collections`, `Objects`, `Math`, `String`

**Rust** (`recognizers/rust.py`):
- Detect `obj.method()` calls (method syntax)
- Detect `Module::function()` calls (path syntax)
- Blocklist: `std`, `println`, `eprintln`, `format`, `vec`, `panic`

**C#** (`recognizers/csharp.py`):
- Detect `obj.Method()` calls
- Detect `ClassName.StaticMethod()` calls
- Detect `new ClassName()` constructor calls
- Blocklist: `Console`, `Math`, `String`, `Convert`, `Enum`

**PHP** (`recognizers/php.py`):
- Detect `$obj->method()` calls
- Detect `ClassName::staticMethod()` calls
- Detect `new ClassName()` constructor calls
- Blocklist: `array_*`, `str_*`, `is_*`, `echo`, `print`

**Ruby** (`recognizers/ruby.py`):
- Detect `obj.method()` calls
- Detect `ClassName.new` constructor calls
- Blocklist: `puts`, `print`, `p`, `require`, `raise`

**C++** (`recognizers/cpp.py`):
- Detect `obj.method()` and `obj->method()` calls
- Detect `namespace::function()` calls
- Detect `new ClassName()` constructor calls
- Blocklist: `std`, `cout`, `cin`, `endl`, `printf`, `malloc`, `free`

**Pattern for all:** Add 2-3 regex constants, a small blocklist, iterate over
matches in `recognize()`, append `CallInfo` records, include in the returned
`ScanResult`. Each recognizer's call detection is ~30-50 lines of code.

### Tests

#### `tests/test_call_detection.py` (new file)

**Test class: `TestGoCallDetection`**
- `test_go_method_call_detected` -- Go code with `s.Store.Save()`, verify
  `CallInfo` with receiver="Store", callee="Save", style="method".
- `test_go_package_qualified_call_detected` -- `store.NewSQLiteStore()`, verify
  CallInfo with receiver="store", callee="NewSQLiteStore".
- `test_go_plain_function_call_detected` -- `HandleKeyEvent(msg)`, verify
  CallInfo with callee="HandleKeyEvent", style="direct".
- `test_go_stdlib_calls_excluded` -- `fmt.Println()`, `log.Fatal()` not in
  calls list.
- `test_go_enclosing_function_context` -- Call inside `func (a *App) Update()`
  has caller="App.Update".
- `test_go_interface_info_emitted` -- Interface with 2 methods produces
  `InterfaceInfo` record.
- `test_go_method_set_entries_emitted` -- Struct with method receiver produces
  `MethodSetEntry` records.
- `test_go_multiple_calls_in_one_function` -- Function with 3 calls produces 3
  `CallInfo` records.

**Test class: `TestPythonCallDetection`**
- `test_python_self_method_call` -- `self.process()` produces
  `CallInfo(style="method")`.
- `test_python_constructor_call` -- `MyService()` produces
  `CallInfo(style="constructor")`.
- `test_python_obj_method_call` -- `db.query()` produces `CallInfo` with
  receiver="db".
- `test_python_builtins_excluded` -- `print()`, `len()`, `range()` not in
  calls list.
- `test_python_enclosing_function_context` -- Call inside `def handle_request`
  has caller="handle_request".

**Test class: `TestTypeScriptCallDetection`**
- `test_ts_this_method_call` -- `this.render()` produces `CallInfo(style="method")`.
- `test_ts_obj_method_call` -- `service.fetchData()` produces `CallInfo`.
- `test_ts_constructor_call` -- `new UserService()` produces
  `CallInfo(style="constructor")`.
- `test_ts_builtins_excluded` -- `console.log()`, `JSON.parse()` not in calls.

**Test class: `TestOtherLanguageCallDetection`**
- `test_java_method_call` -- Basic Java call detection works.
- `test_rust_method_call` -- Basic Rust call detection works.
- `test_csharp_method_call` -- Basic C# call detection works.
- `test_php_method_call` -- Basic PHP call detection works.
- `test_ruby_method_call` -- Basic Ruby call detection works.
- `test_cpp_method_call` -- Basic C++ call detection works.

**Test count:** +24 tests

---

## Phase 3: Inference Pipeline (Depends on Phases 1 and 2)

### Rationale

This is the core of v0.9.0. Two new inference functions process the raw
`CallInfo`, `InterfaceInfo`, and `MethodSetEntry` data collected by recognizers
and create graph edges. These functions follow the established pattern of
`_infer_import_edges_universal` (line 914) and
`_infer_inheritance_edges_universal` (line 955).

### Files to Modify

#### `src/codegiraffe/scanner.py`

##### 1. New function: `_infer_interface_satisfaction`

**Insert after:** `_infer_inheritance_edges_universal` (line 992)

**Signature:**
```python
def _infer_interface_satisfaction(
    result: ScanResult,
    per_file_results: dict[Path, ScanResult],
) -> None:
    """Perform cross-file duck-type matching for interface satisfaction.

    Collects InterfaceInfo and MethodSetEntry records from all files,
    then checks whether any struct's method set is a superset of an
    interface's required methods. Emits ImplementationInfo records that
    will be picked up by _infer_inheritance_edges_universal.

    This function MUST be called BEFORE _infer_inheritance_edges_universal
    so that the newly generated ImplementationInfo records are processed
    into implements edges.
    """
```

**Algorithm:**
1. Collect all `InterfaceInfo` records from `per_file_results` across all files.
2. Collect all `MethodSetEntry` records from `per_file_results`, grouped by
   `struct_name` into `dict[str, set[str]]`.
3. Build a set of already-existing implementations from the merged result to
   avoid duplicates:
   `existing = {(impl.child_class, impl.parent_class) for impl in result.implementations}`
4. For each interface, for each struct:
   - If the struct's method set is a superset of the interface's method list
   - And `(struct_name, interface_name)` not in `existing`
   - Determine `file_path` from the struct's first `MethodSetEntry`
   - Append `ImplementationInfo(child_class=struct_name, parent_class=interface_name, file_path=file_path)`
     to `result.implementations`
5. The newly appended `ImplementationInfo` records will be processed by
   `_infer_inheritance_edges_universal` which runs next.

**Important:** This function mutates `result.implementations` in place, adding
cross-file matches. It does NOT create edges directly -- that is the job of
`_infer_inheritance_edges_universal`.

##### 2. New function: `_infer_call_edges`

**Insert after:** `_infer_interface_satisfaction`

**Signature:**
```python
def _infer_call_edges(
    result: ScanResult,
    per_file_results: dict[Path, ScanResult],
) -> None:
    """Create calls edges from recognizer-provided CallInfo data.

    Resolution strategy:
    1. Build a symbol registry: map function/method names to node IDs.
    2. For each CallInfo, resolve caller and callee to graph node IDs.
    3. If both resolve, create a calls edge.
    4. If a caller/callee is a method without a node, create a
       demand-driven method node (service:{Parent}.{Method}).
    5. Deduplicate: same (source, target, calls) triple only once.
    """
```

**Algorithm:**

```python
def _infer_call_edges(
    result: ScanResult,
    per_file_results: dict[Path, ScanResult],
) -> None:
    # Step 1: Build symbol registry
    # Maps function/method name -> node ID
    # Maps "StructName.MethodName" -> node ID (for method nodes)
    # Maps "StructName" -> node ID (for class/struct nodes as fallback)
    symbol_registry: dict[str, str] = {}
    class_registry: dict[str, str] = {}

    for node in result.nodes:
        if node.type == NodeType.SERVICE.value:
            name = node.metadata.get("class_name") or node.metadata.get("struct_name") or node.label
            class_registry[name] = node.id
            symbol_registry[name] = node.id

    # Step 2: Track already-created method nodes to avoid duplicates
    method_node_registry: dict[str, str] = {}  # "Parent.Method" -> node_id
    existing_edges = {(e.source, e.target, e.type) for e in result.edges}

    # Step 3: Process all CallInfo records
    for rel_path, file_result in per_file_results.items():
        for call in file_result.calls:
            # Resolve caller to a node ID
            caller_id = _resolve_call_participant(
                call.caller, call.file_path, result, symbol_registry,
                class_registry, method_node_registry,
            )
            # Resolve callee to a node ID
            callee_key = f"{call.receiver}.{call.callee}" if call.receiver else call.callee
            callee_id = _resolve_call_participant(
                callee_key, call.file_path, result, symbol_registry,
                class_registry, method_node_registry,
            )

            if not caller_id or not callee_id or caller_id == callee_id:
                continue

            edge_key = (caller_id, callee_id, EdgeType.CALLS.value)
            if edge_key not in existing_edges:
                result.edges.append(Edge(
                    source=caller_id,
                    target=callee_id,
                    type=EdgeType.CALLS.value,
                    metadata={
                        "inferred": True,
                        "caller": call.caller,
                        "callee": call.callee,
                        "style": call.style,
                    },
                ))
                existing_edges.add(edge_key)
```

##### 3. New helper: `_resolve_call_participant`

**Insert before:** `_infer_call_edges`

```python
def _resolve_call_participant(
    name: str,
    file_path: str,
    result: ScanResult,
    symbol_registry: dict[str, str],
    class_registry: dict[str, str],
    method_node_registry: dict[str, str],
) -> str | None:
    """Resolve a caller/callee name to a graph node ID.

    Tries:
    1. Exact match in symbol_registry (e.g., "MyClass" -> service:MyClass)
    2. Method match: "ClassName.MethodName" in method_node_registry
    3. Class fallback: resolve "ClassName" from class_registry when the
       name contains a dot (e.g., "Store.Save" -> try "Store")
    4. On-demand method node creation: if class exists but method doesn't
       have a node, create one (demand-driven).

    Returns None if unresolvable (external call, stdlib, etc.)
    """
```

**Algorithm:**
1. Check `method_node_registry` for exact match -> return if found.
2. Check `symbol_registry` for exact match -> return if found.
3. If name contains `.`:
   - Split into `parent_name, method_name = name.rsplit(".", 1)`
   - Check `method_node_registry` for `parent_name.method_name` -> return.
   - Check `class_registry` for `parent_name`:
     - If found, create demand-driven method node:
       - `node_id = f"service:{parent_name}.{method_name}"`
       - Create `Node(id=node_id, type=SERVICE, label=f"{parent_name}.{method_name}", metadata={"kind": "method", "parent": parent_name, "method_name": method_name})`
       - Create `contains` edge from `class_registry[parent_name]` to `node_id`
       - Register in `method_node_registry`
       - Register in `symbol_registry`
       - Append node and edge to `result`
       - Return `node_id`
4. Return `None` if nothing resolves.

##### 4. Integration into `scan_project()` pipeline

**Modify `scan_project()`** (around line 1502-1510):

Insert `_infer_interface_satisfaction` before `_infer_inheritance_edges_universal`,
and `_infer_call_edges` after `_infer_inheritance_edges` but before
`_infer_contract_edges`:

```python
    # Cross-file interface satisfaction (Go duck typing, v0.9.0)
    _infer_interface_satisfaction(merged, per_file_results)

    # Universal inheritance inference (processes ScanResult.implementations)
    _infer_inheritance_edges_universal(merged, per_file_results)

    # Python-specific inheritance inference (backward compat)
    _infer_inheritance_edges(merged, class_registry, file_contents)

    # Call-graph edge inference (v0.9.0)
    _infer_call_edges(merged, per_file_results)

    # Contract inference (detects cross-component agreements)
    _infer_contract_edges(merged)
```

### Tests

#### `tests/test_call_graph.py` (new file)

**Test class: `TestInferCallEdges`**
- `test_infer_call_edges_creates_calls_edge` -- Two nodes exist (caller, callee),
  CallInfo links them, verify `calls` edge created.
- `test_infer_call_edges_deduplicates` -- Same call appears twice, only one
  edge created.
- `test_infer_call_edges_skips_unresolvable` -- CallInfo references a callee
  not in the graph, no edge created (external call filtered).
- `test_infer_call_edges_creates_method_node_on_demand` -- CallInfo references
  `Store.Save`, `Store` exists but `Save` doesn't, verify method node
  `service:Store.Save` created with `kind: method` metadata.
- `test_method_node_has_contains_edge_from_parent` -- Demand-driven method node
  gets a `contains` edge from its parent class node.
- `test_method_node_deduplication` -- Same method referenced from two callers,
  only one method node created.
- `test_calls_edge_metadata` -- Verify edge has `inferred`, `caller`, `callee`,
  `style` metadata fields.
- `test_infer_call_edges_no_self_loops` -- CallInfo where caller == callee does
  not create an edge.
- `test_infer_call_edges_empty_calls_list` -- No CallInfo records, no edges
  created, no crash.

**Test class: `TestInferInterfaceSatisfaction`**
- `test_cross_file_go_interface_satisfaction` -- Interface in file1 with methods
  ["Save", "Load"], struct in file2 with methods {"Save", "Load", "Delete"},
  verify ImplementationInfo emitted.
- `test_interface_satisfaction_requires_subset` -- Struct has only 1 of 2
  required methods, no match.
- `test_interface_satisfaction_exact_match` -- Struct has exactly the interface's
  methods, matches.
- `test_interface_satisfaction_does_not_duplicate_existing` -- If
  ImplementationInfo already exists (from same-file matching), don't add again.
- `test_interface_satisfaction_multiple_implementors` -- Two structs both satisfy
  the same interface, both get ImplementationInfo.
- `test_interface_satisfaction_multiple_interfaces` -- One struct satisfies two
  different interfaces.
- `test_interface_satisfaction_empty_interface` -- Interface with no methods does
  not match anything (edge case: empty method set is a subset of everything, but
  an empty interface is not meaningful).

**Test class: `TestMethodNodeCreation`**
- `test_method_node_id_format` -- Verify ID is `service:{Parent}.{Method}`.
- `test_method_node_type_is_service` -- Verify type is `NodeType.SERVICE`.
- `test_method_node_metadata_kind` -- Verify `metadata["kind"] == "method"`.
- `test_method_node_metadata_parent` -- Verify `metadata["parent"]` is set.
- `test_method_node_metadata_method_name` -- Verify `metadata["method_name"]`
  is set.

**Test class: `TestCallGraphIntegration`**
- `test_scan_project_creates_call_edges_go` -- Write synthetic Go files with
  cross-file calls, run `scan_project()`, verify `calls` edges in result.
- `test_scan_project_creates_call_edges_python` -- Write synthetic Python files
  with `self.method()` calls, verify `calls` edges.
- `test_scan_project_cross_file_interface_go` -- Write Go files with interface
  in one file and implementor in another, verify `implements` edge.
- `test_scan_project_call_graph_plus_blast_radius` -- Scan a project, get blast
  radius for a callee node, verify callers appear as impacted.
- `test_scan_project_no_calls_backward_compat` -- Scan a project with no
  detectable calls, verify output identical to v0.8.0 (no regression).

**Test count:** +26 tests

---

## Phase 4: Tree-Sitter AST Call Detection (Parallel with Phase 3)

### Rationale

The existing `ast_scanner.py` already has tree-sitter query constants for Go
call expressions (`_GO_CALL_QUERY`, line 384) and TypeScript call expressions
(`_TS_CALL_QUERY`, line 457). These queries are defined but not used to produce
`CallInfo` records. This phase wires them up.

AST-based call detection is more accurate than regex (no false positives from
strings or comments) but both modes must produce valid `CallInfo` records that
feed into the same inference pipeline.

### Files to Modify

#### `src/codegiraffe/ast_scanner.py`

##### 1. Extend `GoASTRecognizer.recognize()`

**Modify `recognize()`** (line 405-416):

Add a call to a new `_find_calls` method:

```python
    def recognize(self, file_path: Path, content: str) -> ScanResult:
        if not content.strip():
            return ScanResult()

        tree = self._parser.parse(content.encode())
        nodes: list[Node] = []
        rel = str(file_path)

        self._find_structs(tree, rel, nodes)
        self._find_env_vars(tree, rel, nodes)

        # Call detection (v0.9.0)
        calls = self._find_calls(tree, content, rel)

        return ScanResult(nodes=nodes, edges=[], calls=calls)
```

##### 2. New method: `GoASTRecognizer._find_calls`

```python
    def _find_calls(
        self, tree, content: str, rel_path: str,
    ) -> list[CallInfo]:
        """Extract call expressions using tree-sitter Go query."""
        from codegiraffe.scanner import CallInfo
        calls: list[CallInfo] = []

        query = self._go_lang.query(_GO_CALL_QUERY)
        matches = _query_matches(query, tree.root_node)
        for match in matches:
            obj_node = match.get("obj")
            method_node = match.get("method")
            if obj_node and method_node:
                receiver = _text(obj_node, content)
                method = _text(method_node, content)
                if receiver.lower() in _GO_AST_STDLIB_PACKAGES:
                    continue
                # Determine enclosing function via tree-sitter parent traversal
                caller = self._find_enclosing_func_ast(obj_node)
                if caller:
                    calls.append(CallInfo(
                        caller=caller, callee=method, receiver=receiver,
                        file_path=rel_path, style="method",
                    ))
        return calls
```

##### 3. New method: `GoASTRecognizer._find_enclosing_func_ast`

```python
    def _find_enclosing_func_ast(self, node) -> str:
        """Walk tree-sitter parents to find enclosing function declaration."""
        current = node.parent
        while current:
            if current.type in ("function_declaration", "method_declaration"):
                name_node = current.child_by_field_name("name")
                if name_node:
                    return _text(name_node, "")  # Will need content param
            current = current.parent
        return ""
```

##### 4. Extend `TypeScriptASTRecognizer` similarly

Apply the same pattern: use `_TS_CALL_QUERY` to extract call expressions,
convert to `CallInfo` records, filter builtins.

##### 5. Extend `PythonASTRecognizer`

Add a new tree-sitter query for Python call expressions:

```python
_PY_CALL_QUERY = """
(call
  function: (attribute
    object: (identifier) @obj
    attribute: (identifier) @method))
"""
```

Use it in `PythonASTRecognizer.recognize()` to produce `CallInfo` records.

##### 6. New constant: `_GO_AST_STDLIB_PACKAGES`

Same as `_GO_STDLIB_PACKAGES` in the regex recognizer, or import from scanner.

### Tests

#### `tests/test_ast_scanner.py` (modify existing)

**New test class: `TestASTCallDetection`**
- `test_go_ast_call_detection` -- Parse Go code with tree-sitter, verify
  `CallInfo` records in ScanResult.
- `test_go_ast_stdlib_filtered` -- `fmt.Println()` not in calls.
- `test_ts_ast_call_detection` -- Parse TypeScript code, verify CallInfo.
- `test_python_ast_call_detection` -- Parse Python code, verify CallInfo.
- `test_ast_and_regex_produce_compatible_results` -- Same Go file scanned with
  both modes, verify both produce CallInfo records with matching callee names.

All AST tests use `@pytest.mark.skipif(not HAS_TREE_SITTER, ...)` to skip
when tree-sitter is not installed.

**Test count:** +5 tests

---

## Phase 5: Improved Interface/Implementation Validation (Parallel with Phases 3-4)

### Rationale

The spec requires validating and improving the existing `implements` detection
in all recognizers. This is primarily verification with targeted fixes for
edge cases. The cross-file Go interface satisfaction was handled in Phase 3;
this phase covers the TypeScript and other-language validation.

### Files to Modify

#### `src/codegiraffe/recognizers/typescript.py`

##### 1. Verify `_TS_CLASS_IMPLEMENTS_RE`

Read the existing regex and verify it handles:
- Multiple interfaces: `class Foo implements Bar, Baz`
- Generic interfaces: `class Foo implements Bar<string>`
- With extends: `class Foo extends Base implements Bar`

If the regex doesn't handle these, fix it. The existing pattern is likely:
```python
_TS_CLASS_IMPLEMENTS_RE = re.compile(r'class\s+(\w+).*?\bimplements\s+([\w,\s<>]+)')
```

Ensure the capture group for interfaces properly splits on commas and strips
generic parameters for the purpose of interface name extraction.

#### Other Recognizers

For each recognizer, verify the existing implementation regex handles
real-world patterns:

- **Java** (`_JAVA_CLASS_IMPLEMENTS_RE`): Verify multi-interface
  `implements Foo, Bar`.
- **Rust** (`_RUST_IMPL_TRAIT_RE`): Verify `impl Trait for Struct` basic case.
- **C#** (`_CS_CLASS_INHERITANCE_RE`): Verify interface vs base class
  disambiguation (interfaces start with `I` by convention).
- **PHP** (`_PHP_CLASS_IMPL_RE`): Verify multi-interface.
- **Ruby** (`_RB_CLASS_INHERIT_RE`): Verify `include Module`.
- **C++** (`_CPP_CLASS_INHERITANCE_RE`): Verify `class Foo : public IBar`.

### Tests

#### `tests/test_recognizers.py` (modify existing)

Add targeted tests for edge cases:

- `test_ts_implements_multiple_interfaces` -- `class Foo implements Bar, Baz`
  produces 2 `ImplementationInfo` records.
- `test_ts_implements_generic_interface` -- `class Foo implements Bar<string>`
  produces `ImplementationInfo(parent_class="Bar")`.
- `test_ts_implements_with_extends` -- `class Foo extends Base implements Bar`
  produces both extends and implements.
- `test_java_implements_multiple` -- Verify multi-interface handling.
- `test_csharp_interface_vs_base_class` -- `class Foo : BaseClass, IInterface`
  distinguishes correctly.

**Test count:** +5 tests

---

## Phase 6: Polish (Last)

### Rationale

Version bump, documentation updates, final verification. No new features.

### Files to Modify

#### `pyproject.toml`

- Bump `version` from `"0.8.0"` to `"0.9.0"`.

#### `CLAUDE.md`

- Update `Version` line to `0.9.0`.
- Update test count from 791 to 853+.
- Add new data classes (`CallInfo`, `InterfaceInfo`, `MethodSetEntry`) to Code
  Style section.
- Add `calls` edge type documentation (note: enum already existed, now
  populated by scanner).
- Add `Recent Changes` entry for v0.9.0:
  ```
  - v0.9.0: Scanner depth -- call-graph edges (calls), cross-file Go interface
    satisfaction, demand-driven method nodes; CallInfo/InterfaceInfo/MethodSetEntry
    data classes; _infer_call_edges() and _infer_interface_satisfaction() pipeline
    steps; call detection in all 9 language recognizers + AST scanner; 853+ tests
  ```
- Update scanner description to mention call-graph detection.

### Verification

Run the full test suite:
```bash
source .venv/bin/activate && python -m pytest tests/ -v
```

- All 791 existing tests must pass unchanged.
- 60+ new tests must pass.
- Total test count: 853+.

### Test count: +0 (no new tests in this phase)

---

## Data Model Changes Summary

### New Data Classes (in `scanner.py`)

| Class | Fields | Purpose |
|-------|--------|---------|
| `CallInfo` | caller, callee, receiver, file_path, style | Structured call-site data from recognizers |
| `InterfaceInfo` | name, methods, file_path | Interface declaration with required methods |
| `MethodSetEntry` | struct_name, method_name, file_path | Single method in a struct's method set |

### ScanResult Extensions

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `calls` | `list[CallInfo]` | `[]` | Call-site records from recognizers |
| `interfaces` | `list[InterfaceInfo]` | `[]` | Interface declarations for cross-file matching |
| `method_sets` | `list[MethodSetEntry]` | `[]` | Method set entries for cross-file matching |

### Demand-Driven Method Nodes

| Property | Value |
|----------|-------|
| Type | `NodeType.SERVICE` ("service") |
| ID format | `service:{ParentName}.{MethodName}` |
| metadata.kind | `"method"` |
| metadata.parent | Parent class/struct name |
| metadata.method_name | Method name |
| Parent edge | `contains` from parent class node |

---

## Scanner Pipeline Changes

### Before (v0.8.0)

```
scan_project()
  per-file -> ScanResult(nodes, edges, imports, implementations)
  _infer_import_edges_universal()
  _infer_cross_file_edges()
  _infer_import_edges()
  class_registry construction
  _infer_inheritance_edges_universal()
  _infer_inheritance_edges()
  _infer_contract_edges()
```

### After (v0.9.0)

```
scan_project()
  per-file -> ScanResult(nodes, edges, imports, implementations,
                          calls, interfaces, method_sets)       # EXTENDED
  _infer_import_edges_universal()
  _infer_cross_file_edges()
  _infer_import_edges()
  class_registry construction
  _infer_interface_satisfaction()            # NEW - cross-file duck typing
  _infer_inheritance_edges_universal()
  _infer_inheritance_edges()
  _infer_call_edges()                       # NEW - call-graph edges
  _infer_contract_edges()
```

### Why This Order

1. **`_infer_interface_satisfaction` before `_infer_inheritance_edges_universal`:**
   Interface satisfaction generates `ImplementationInfo` records that are then
   processed by the existing inheritance inference into `implements` edges.
   Running it first avoids duplicating edge-creation logic.

2. **`_infer_call_edges` after inheritance, before contracts:**
   Call-graph edges need the full class registry (including inheritance info)
   to resolve method calls. Contracts come last because they may benefit from
   call-graph data in future versions.

---

## Key Design Decisions

### 1. Demand-Driven Method Nodes (Not Exhaustive)

**Decision:** Only create method-level nodes when they participate in a
call-graph edge.

**Rationale:** A file with 50 methods but only 3 that call other scanned
functions produces 3 method nodes, not 50. This keeps graph size manageable
and focused on architecturally significant relationships.

**Alternative considered:** Create method nodes for all detected functions.
Rejected because it would explode graph size for large codebases and most
method nodes would be leaves with no architectural significance.

### 2. Symbol Registry Filtering (Not Blocklists Alone)

**Decision:** The primary filter for excluding external calls is the symbol
registry: only create edges when both caller and callee resolve to nodes in
the graph. Blocklists are a secondary optimization to reduce noise in
`CallInfo` records.

**Rationale:** Blocklists are inherently incomplete. The symbol registry
approach naturally excludes all external calls because external functions
don't have nodes in the graph. Blocklists just reduce the number of
`CallInfo` records that need (and fail) resolution.

### 3. Interface Satisfaction in the Pipeline (Not in Recognizers)

**Decision:** Cross-file Go interface satisfaction is implemented as a
pipeline step (`_infer_interface_satisfaction`) in `scanner.py`, not in the
Go recognizer.

**Rationale:** Recognizers only see one file at a time. Cross-file matching
requires data from multiple files. The pipeline already handles this pattern
for imports and inheritance. The Go recognizer's existing within-file matching
is kept for backward compatibility and fast single-file results.

### 4. Reuse Existing `calls` EdgeType

**Decision:** No new schema types are needed. `EdgeType.CALLS` (schema.py:29)
already exists.

**Rationale:** The `calls` edge type was defined in the original schema but
never populated by the scanner. v0.9.0 populates it. This is the ideal
outcome: the schema was designed with this use case in mind.

### 5. Method Node ID Format

**Decision:** `service:{ParentName}.{MethodName}` using the existing
`NodeType.SERVICE` type.

**Rationale:** Introducing a new `NodeType.METHOD` would require changes to
every tool that switches on node types, plus dashboard styling, export logic,
etc. Using `SERVICE` with `metadata.kind = "method"` is cleaner: all existing
tools work without modification, and the `kind` metadata allows differentiation
when needed.

### 6. Enclosing Function Context via Line Counting

**Decision:** For regex-based scanning, determine the enclosing function by
mapping line numbers to function definition ranges.

**Rationale:** Regex cannot parse scope nesting, but a simple line-range mapping
(function definition line to next function definition line or EOF) works well
enough for the caller field. AST scanning via tree-sitter gets exact scope
via parent traversal, providing a more accurate alternative.

### 7. CallInfo Style Field

**Decision:** Include a `style` field ("direct", "method", "static",
"constructor") on `CallInfo`.

**Rationale:** The style field enables richer edge metadata and helps the
inference pipeline make better resolution decisions. Constructor calls
indicate object creation patterns; method calls with receivers help resolve
to the correct class.

---

## File Change Summary

| File | Change Type | Phase | Description |
|------|-------------|-------|-------------|
| `src/codegiraffe/scanner.py` | Modify | 1, 2, 3 | New data classes (CallInfo, InterfaceInfo, MethodSetEntry), ScanResult extension, PythonRecognizer call detection, new inference functions (_infer_call_edges, _infer_interface_satisfaction), pipeline integration |
| `src/codegiraffe/recognizers/go.py` | Modify | 2 | Call detection regex + logic, InterfaceInfo/MethodSetEntry emission |
| `src/codegiraffe/recognizers/typescript.py` | Modify | 2, 5 | Call detection, implements validation |
| `src/codegiraffe/recognizers/java.py` | Modify | 2 | Basic call detection |
| `src/codegiraffe/recognizers/rust.py` | Modify | 2 | Basic call detection |
| `src/codegiraffe/recognizers/csharp.py` | Modify | 2 | Basic call detection |
| `src/codegiraffe/recognizers/php.py` | Modify | 2 | Basic call detection |
| `src/codegiraffe/recognizers/ruby.py` | Modify | 2 | Basic call detection |
| `src/codegiraffe/recognizers/cpp.py` | Modify | 2 | Basic call detection |
| `src/codegiraffe/ast_scanner.py` | Modify | 4 | Wire up existing tree-sitter call queries to produce CallInfo |
| `pyproject.toml` | Modify | 6 | Version bump 0.8.0 -> 0.9.0 |
| `CLAUDE.md` | Modify | 6 | Documentation updates |
| `tests/test_call_detection.py` | Create | 2 | Recognizer-level call detection tests (24 tests) |
| `tests/test_call_graph.py` | Create | 3 | Inference pipeline + integration tests (26 tests) |
| `tests/test_scanner.py` | Modify | 1 | Data class and ScanResult extension tests (9 tests) |
| `tests/test_ast_scanner.py` | Modify | 4 | AST-based call detection tests (5 tests) |
| `tests/test_recognizers.py` | Modify | 5 | Interface/implementation edge case tests (5 tests) |

---

## Summary

| Phase | Files Modified | New Functions/Methods | Tests Added |
|-------|---------------|----------------------|-------------|
| 1. Data Model | scanner.py | 3 data classes + ScanResult extension | 9 |
| 2. Recognizer Call Detection | 9 recognizer files | ~9 call detection sections + helpers | 24 |
| 3. Inference Pipeline | scanner.py | 3 (_infer_call_edges, _infer_interface_satisfaction, _resolve_call_participant) | 26 |
| 4. AST Scanner | ast_scanner.py | ~3 _find_calls methods | 5 |
| 5. Interface Validation | typescript.py + others | 0 (fixes/validation only) | 5 |
| 6. Polish | pyproject.toml, CLAUDE.md | 0 | 0 |
| **Total** | **14 files** (12 source, 2 new test) | **~18 functions/methods** | **69 tests** |

### Dependency Graph

```
Phase 1 (Data Model)
  |
  +---> Phase 2 (Recognizer Call Detection) ---> Phase 3 (Inference Pipeline)
  |                                                        |
  +---> Phase 4 (AST Scanner) --------------------------->|
  |                                                        |
  +---> Phase 5 (Interface Validation)                     |
  |                                                        |
  +--------------------------------------------------------+---> Phase 6 (Polish)
```

Phase 1 must go first. Phases 2, 4, and 5 can proceed in parallel once Phase 1
is complete. Phase 3 depends on Phase 2 (needs CallInfo data from recognizers).
Phase 6 is the final merge/polish after all feature phases.

### Risk Assessment

**Low risk:**
- Phase 1 (purely additive data classes with defaults)
- Phase 5 (validation and edge-case fixes for existing code)
- Phase 6 (documentation only)

**Medium risk:**
- Phase 2 (new regex patterns may produce false positives)
  - Mitigation: stdlib/builtin blocklists reduce noise; symbol registry in
    Phase 3 filters out anything that doesn't resolve to a known node.
- Phase 4 (tree-sitter integration for calls)
  - Mitigation: AST scanner is optional; regex is the default; tests skip
    when tree-sitter is not installed.

**Highest risk:**
- Phase 3 (inference pipeline + demand-driven method nodes)
  - Mitigation: Method node creation is conservative (only on resolution
    success). Deduplication via registries prevents explosion. The
    `_infer_call_edges` function is a no-op when no `CallInfo` exists, so
    projects without call detection produce identical graphs. All 791
    existing tests pass because they have no `CallInfo` records.

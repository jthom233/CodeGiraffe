# Specification

## Requirements

## Code Giraffe v0.9.0 — Scanner Depth

### Overview

v0.9.0 deepens CodeGiraffe's scanner from structural pattern detection to **behavioral relationship extraction**. Today the scanner discovers *what exists* (structs, endpoints, modules) and *how things are organized* (contains, imports, implements). After v0.9.0, it also discovers *what calls what* and *who satisfies which interface* — the two missing relationship types that prevent AI agents from reasoning about runtime behavior and architectural contracts.

This is not a new tool release. It is a scanner intelligence upgrade that enriches the existing graph, making every existing MCP tool (`context_for`, `blast_radius`, `risk_assessment`, `cycles`, `hotspots`) produce significantly better results without any API changes.

### Motivation

Real-world user feedback on a Go project exposed two critical gaps:

1. **No call-graph edges.** The scanner creates `contains` edges from a module to its functions and `imports` edges between modules, but it does not know that `App.handleKeyEvent()` calls `clipboardChannel.Write()`. These `contains` edges are structural, not behavioral. An AI agent asked "what happens if I change `clipboardChannel.Write()`?" gets no downstream callers, because the `calls` edge type — already defined in `schema.py` — is never populated by the scanner.

2. **Incomplete interface/implementation tracking.** The Go recognizer detects interface declarations and struct method sets, and performs duck-type matching within a single file. But Go codebases define interfaces and their implementors in separate files and packages. The single-file matching works for trivial cases but misses the architecturally significant ones: `Store` defined in `internal/store/store.go` implemented by `SQLiteStore` in `internal/store/sqlite.go`. The cross-file universal pipeline in `scanner.py` resolves `ImplementationInfo` records across files, but the Go recognizer only emits them when interface and struct are in the same file.

These gaps make `blast_radius` undercount impact (it misses callers), `risk_assessment` underweight critical hub functions (they have no inbound edges), and `context_for` miss behavioral relationships entirely. Fixing the scanner fixes all downstream tools.

### Features

#### Feature 1: Call-Graph Edges (`calls` edge type)

##### F1.1: CallInfo Data Class

Add a new structured data class to `scanner.py`, following the established pattern of `ImportInfo` and `ImplementationInfo`:

```python
@dataclass
class CallInfo:
    """Structured call-site information returned by recognizers."""
    caller: str          # Name of the calling function/method
    callee: str          # Name of the called function/method
    receiver: str = ""   # Receiver/object if method call (e.g., "clipboardChannel")
    file_path: str = ""  # Relative path where the call occurs
    style: str = "direct"  # "direct" | "method" | "static" | "constructor"
```

Add `calls: list[CallInfo]` to the `ScanResult` dataclass, with `field(default_factory=list)`. Update `ScanResult.merge()` to extend calls from other results.

##### F1.2: Recognizer Call Detection

Each recognizer extracts function/method calls and returns them as `CallInfo` records. The scope is **intra-project calls only** — calls to standard library and external dependencies are excluded.

**Go recognizer** (`recognizers/go.py`):
- Detect method calls on named receivers: `s.Store.Save()` -> CallInfo(caller=enclosing_func, callee="Save", receiver="Store")
- Detect package-qualified function calls: `store.NewSQLiteStore()` -> CallInfo(caller=enclosing_func, callee="NewSQLiteStore", receiver="store")
- Detect plain function calls within the same package: `handleKeyEvent(msg)` -> CallInfo(caller=enclosing_func, callee="handleKeyEvent")
- Use the existing `_GO_METHOD_RECEIVER_RE` pattern to determine enclosing function context
- Exclude calls to stdlib packages (fmt, log, os, strings, etc.) and known framework calls (http.HandleFunc, etc.)

**Python recognizer** (`scanner.py` PythonRecognizer):
- Detect `self.method()` calls -> CallInfo(caller=enclosing_method, callee="method", style="method")
- Detect `obj.method()` calls where `obj` is a known local variable -> CallInfo
- Detect `ClassName.method()` or `module.function()` calls -> CallInfo(style="static")
- Detect `ClassName()` constructor calls -> CallInfo(style="constructor")
- Exclude calls to builtins (print, len, range, etc.) and stdlib imports

**TypeScript recognizer** (`recognizers/typescript.py`):
- Detect `this.method()` calls -> CallInfo(style="method")
- Detect `obj.method()` and `import.function()` calls
- Detect `new ClassName()` constructor calls -> CallInfo(style="constructor")
- Exclude calls to built-in globals (console, JSON, Math, etc.)

**Other recognizers** (Java, Rust, C#, PHP, Ruby, C++):
- Add basic call detection following the same pattern
- Priority is Go, Python, TypeScript — other languages get best-effort regex detection
- All recognizers return `CallInfo` records; the inference pipeline handles edge creation uniformly

##### F1.3: Call-Graph Edge Inference

Add `_infer_call_edges(result, per_file_results)` to `scanner.py`, following the pattern of `_infer_import_edges_universal` and `_infer_inheritance_edges_universal`.

Resolution strategy:
1. Build a symbol registry: map function/method names to node IDs from the scanned graph
2. For each `CallInfo` record, resolve caller and callee to graph node IDs
3. If both resolve to existing nodes, create a `calls` edge
4. If the callee resolves but the caller doesn't, create a method-level node for the caller (see Feature 3) and then create the edge
5. Metadata on `calls` edges: `{"inferred": true, "caller": "FuncName", "callee": "FuncName", "style": "method"}`

Deduplication: same `(source, target, "calls")` triple is only created once, even if the call appears multiple times in the source.

Call `_infer_call_edges()` in `scan_project()` after import inference but before contract inference, so that contracts can potentially leverage call-graph information in the future.

##### F1.4: Tree-Sitter AST Call Detection

Enhance `ast_scanner.py` to extract call expressions using tree-sitter queries. This is the natural fit for call detection since tree-sitter can parse call expressions precisely:

- Python: query `(call function: (_) @callee)` to extract all call expressions
- Go: query `(call_expression function: (_) @callee)` to extract all call expressions
- TypeScript: query `(call_expression function: (_) @callee)`

The AST recognizers return `CallInfo` records in the same `ScanResult`, so the inference pipeline works identically regardless of scanning mode. AST-based detection will be more accurate than regex (fewer false positives from string literals, comments, etc.) but both modes must produce valid `CallInfo` records.

#### Feature 2: Enhanced Interface/Implementation Tracking

##### F2.1: Cross-File Go Interface Satisfaction

The current Go recognizer detects interfaces and struct method sets within a single file. This must be extended to work cross-file:

**Current behavior** (single-file, already works):
```go
// store.go
type Store interface { Save(key string) error }
type MemoryStore struct{}
func (m *MemoryStore) Save(key string) error { ... }
// -> ImplementationInfo(child="MemoryStore", parent="Store")
```

**Required behavior** (cross-file):
```go
// store.go (file 1)
type Store interface { Save(key string) error }

// sqlite.go (file 2)
type SQLiteStore struct{}
func (s *SQLiteStore) Save(key string) error { ... }
// -> ImplementationInfo(child="SQLiteStore", parent="Store") must still be generated
```

The fix is in the **scanner pipeline**, not in the Go recognizer itself. The recognizer already collects:
- Interface method signatures (via `_GO_INTERFACE_BODY_RE`)
- Struct method sets (via `_GO_METHOD_RECEIVER_RE`)

But it only matches them within `recognize()` for a single file. The solution:

1. Add `interfaces: list[InterfaceInfo]` and `method_sets: list[MethodSetEntry]` to `ScanResult` (new data classes)
2. Go recognizer emits `InterfaceInfo(name="Store", methods=["Save"])` and `MethodSetEntry(struct_name="SQLiteStore", method_name="Save")` as raw data
3. New `_infer_interface_satisfaction(result, per_file_results)` function in `scanner.py` performs cross-file duck-type matching:
   - Collect all `InterfaceInfo` records across all files
   - Collect all `MethodSetEntry` records across all files, grouped by struct name
   - For each interface, check each struct's method set for subset inclusion
   - Emit `ImplementationInfo` for matches
4. This replaces (or supplements) the existing within-file matching in the Go recognizer

New data classes in `scanner.py`:

```python
@dataclass
class InterfaceInfo:
    """Interface declaration with its required method signatures."""
    name: str                    # Interface name
    methods: list[str]           # Required method names
    file_path: str = ""          # Where the interface is defined

@dataclass
class MethodSetEntry:
    """A single method belonging to a struct/class method set."""
    struct_name: str             # Struct/class that has this method
    method_name: str             # Method name
    file_path: str = ""          # Where the method is defined
```

Add `interfaces: list[InterfaceInfo]` and `method_sets: list[MethodSetEntry]` to `ScanResult`.

##### F2.2: Improved TypeScript `implements` Detection

The TypeScript recognizer already has `_TS_CLASS_IMPLEMENTS_RE` for `class Foo implements Bar`. Verify it handles:
- Multiple interfaces: `class Foo implements Bar, Baz`
- Generic interfaces: `class Foo implements Bar<string>`
- With extends: `class Foo extends Base implements Bar`

If any of these patterns are not handled, fix the regex. The existing implementation likely handles the basic case already — this requirement is about validation and edge case coverage.

##### F2.3: Other Languages

Verify and improve implementation detection in remaining recognizers:
- **Java**: `class Foo implements Bar, Baz` (already has `_JAVA_CLASS_IMPLEMENTS_RE` — verify multi-interface)
- **Rust**: `impl Trait for Struct` (already has `_RUST_IMPL_TRAIT_RE` — verify)
- **C#**: `class Foo : IBar, IBaz` (already has detection — verify interface vs base class disambiguation)
- **PHP**: `class Foo implements Bar, Baz` (already has detection — verify)
- **Ruby**: `include Module` / `prepend Module` (already has detection — verify)
- **C++**: `class Foo : public IBar` (already has detection — verify)

This requirement is primarily validation with targeted fixes, not a rewrite. All recognizers already return `ImplementationInfo` — the goal is ensuring they handle real-world patterns correctly.

#### Feature 3: Method-Level Nodes (On-Demand)

##### F3.1: Demand-Driven Method Nodes

Currently all nodes are at the struct/class/module level. Call-graph edges need function-level resolution. Rather than creating a method node for every function in every file (which would explode graph size), create method-level nodes **only when they participate in a call-graph edge**.

When `_infer_call_edges()` resolves a `CallInfo` and the caller or callee is a method that doesn't have its own node:
1. Create a `service` node with ID format: `service:{ClassName}.{MethodName}` (or `service:{package}.{FuncName}` for package-level functions)
2. Metadata: `{"kind": "method", "parent": "ClassName", "method_name": "MethodName"}`
3. Create a `contains` edge from the parent class/struct node to the method node
4. Then create the `calls` edge between the method nodes

This keeps the graph manageable: only methods that are part of call-graph edges get nodes. A file with 50 methods but only 3 that call other scanned functions will only add 3 method nodes.

##### F3.2: Method Node Deduplication

Multiple call sites may reference the same method. Ensure method nodes are created only once:
- Use a method node registry during `_infer_call_edges()` to track already-created method nodes
- Node ID format must be deterministic: `service:{ParentName}.{MethodName}`
- If a method node already exists (from the same or different file), reuse it

### Technical Approach

#### Scanner Pipeline Extension

The changes fit cleanly into the existing scanner architecture:

```
scan_project()
  |-- per-file: recognizer.recognize() -> ScanResult with nodes, edges, imports,
  |                                        implementations, calls (NEW), interfaces (NEW),
  |                                        method_sets (NEW)
  |-- merge all per-file results
  |-- _infer_import_edges_universal()           # existing
  |-- _infer_cross_file_edges()                 # existing (Python compat)
  |-- _infer_import_edges()                     # existing (Python compat)
  |-- _infer_interface_satisfaction()            # NEW: cross-file duck-type matching
  |-- _infer_inheritance_edges_universal()       # existing
  |-- _infer_inheritance_edges()                 # existing (Python compat)
  |-- _infer_call_edges()                       # NEW: call-graph edge creation
  |-- _infer_contract_edges()                   # existing
  `-- return merged
```

#### Regex Patterns for Call Detection

**Go** — detecting function/method calls:
```python
# Method calls: receiver.Method(args)
_GO_FUNC_CALL_RE = re.compile(r'(\w+)\.(\w+)\s*\(')

# Plain function calls: FunctionName(args) — uppercase start = exported
_GO_PLAIN_CALL_RE = re.compile(r'(?<!\.)(\b[A-Z]\w+)\s*\(')

# Enclosing function context: func (r *Type) Name( or func Name(
_GO_FUNC_DEF_RE = re.compile(r'func\s+(?:\(\w+\s+\*?(\w+)\)\s+)?(\w+)\s*\(')
```

**Python** — detecting function/method calls:
```python
# self.method() calls
_PY_SELF_CALL_RE = re.compile(r'self\.(\w+)\s*\(')

# obj.method() calls
_PY_METHOD_CALL_RE = re.compile(r'(\w+)\.(\w+)\s*\(')

# ClassName() constructor calls
_PY_CONSTRUCTOR_CALL_RE = re.compile(r'(?<!\.)([A-Z]\w+)\s*\(')

# Enclosing function context
_PY_FUNC_DEF_RE = re.compile(r'(?:def|async\s+def)\s+(\w+)\s*\(')
```

**TypeScript** — detecting function/method calls:
```python
# this.method() calls
_TS_THIS_CALL_RE = re.compile(r'this\.(\w+)\s*\(')

# obj.method() calls
_TS_METHOD_CALL_RE = re.compile(r'(\w+)\.(\w+)\s*\(')

# new ClassName() constructor calls
_TS_CONSTRUCTOR_CALL_RE = re.compile(r'new\s+(\w+)\s*\(')
```

#### Filtering External Calls

To limit call-graph edges to intra-project calls only:

1. **Symbol registry approach**: After scanning, build a set of all known function/method names from the graph. Only create `calls` edges where the callee name matches a known symbol.
2. **Stdlib blocklist**: Maintain per-language blocklists of common stdlib/builtin names to skip during recognition (not during inference). This reduces noise in `CallInfo` records.
3. **Package-awareness**: For Go, use `go.mod` module path (already parsed by GoRecognizer) to filter imports. For Python, use the project root to determine if a module is internal.

The symbol registry approach is the primary filter. The blocklist is a performance optimization to reduce the number of `CallInfo` records that need resolution.

#### Impact on Existing Tools

No API changes to any MCP tool. The improvements are entirely in graph richness:

- **`context_for`**: Call-graph edges improve semantic scoring. A query about "clipboard" will now return not just the clipboard module but also its callers, because `calls` edges connect them.
- **`blast_radius`**: Callers of a changed function are now downstream impacts. Changing `clipboardChannel.Write()` will show `App.handleKeyEvent()` as impacted.
- **`risk_assessment`**: Functions with many callers (high in-degree on `calls` edges) score higher risk. Interface types with many implementors score higher.
- **`cycles`**: Call cycles (A calls B calls A) are now detectable as circular dependencies.
- **`hotspots`**: Hub functions that are called by many others become hotspots via degree centrality.
- **`contracts`**: No direct impact, but call-graph edges could inform future contract detection (e.g., a function that calls an HTTP client is a contract consumer).

#### Backward Compatibility

All changes are additive:
- New fields on `ScanResult` have default values (`field(default_factory=list)`)
- New edge type `calls` already exists in `EdgeType` enum — no schema change needed
- New node type is not needed (method nodes use existing `service` type with metadata)
- Existing recognizers that don't implement call detection return empty `calls` lists
- The `_infer_call_edges()` function is a no-op when no `CallInfo` records exist
- Projects without detectable calls produce identical graphs to v0.8.0

### Acceptance Criteria

- [ ] `CallInfo` data class added to `scanner.py` with fields: caller, callee, receiver, file_path, style
- [ ] `ScanResult` extended with `calls: list[CallInfo]`, `interfaces: list[InterfaceInfo]`, `method_sets: list[MethodSetEntry]`
- [ ] `ScanResult.merge()` updated to extend calls, interfaces, and method_sets
- [ ] Go recognizer detects method calls and package-qualified function calls, returning `CallInfo` records
- [ ] Python recognizer detects `self.method()`, `obj.method()`, and `ClassName()` calls, returning `CallInfo` records
- [ ] TypeScript recognizer detects `this.method()`, `obj.method()`, and `new Class()` calls, returning `CallInfo` records
- [ ] Java, Rust, C#, PHP, Ruby, C++ recognizers have basic call detection returning `CallInfo` records
- [ ] `_infer_call_edges()` function in `scanner.py` resolves `CallInfo` to `calls` edges using symbol registry
- [ ] `_infer_call_edges()` creates method-level nodes on demand when caller/callee is a method without a node
- [ ] Method-level nodes have ID format `service:{Parent}.{Method}` with `kind: method` metadata
- [ ] Method-level nodes get `contains` edges from their parent class/struct node
- [ ] Call-graph edges have metadata: `{"inferred": true, "caller": "...", "callee": "...", "style": "..."}`
- [ ] Go recognizer emits `InterfaceInfo` and `MethodSetEntry` records for cross-file resolution
- [ ] `_infer_interface_satisfaction()` performs cross-file duck-type matching for Go interfaces
- [ ] Cross-file Go interface satisfaction generates `implements` edges
- [ ] Tree-sitter AST scanner in `ast_scanner.py` extracts call expressions and returns `CallInfo` records
- [ ] Both regex and tree-sitter modes produce valid call-graph edges
- [ ] External/stdlib calls are filtered out (not turned into edges)
- [ ] `blast_radius` produces richer results with call-graph edges (callers shown as impacted)
- [ ] `risk_assessment` scores reflect call-graph connectivity
- [ ] `context_for` returns behavioral (call) relationships, not just structural ones
- [ ] All existing 793 tests pass unchanged
- [ ] 60+ new tests covering call-graph detection, cross-file interface matching, and method nodes
- [ ] 853+ total tests
- [ ] CLAUDE.md updated with v0.9.0 section

### Non-Goals

- **Full type resolution.** CodeGiraffe uses pattern matching and heuristic name resolution, not a type system. If `foo.Bar()` is ambiguous (multiple structs have a `Bar` method), the edge is created to all candidates or skipped. This is acceptable — CodeGiraffe is "beyond-AST" but not an LSP replacement.
- **Cross-project call graph.** Calls between federated repositories are out of scope. Federation already handles cross-repo edges at the service level; function-level cross-repo calls are not useful without shared type information.
- **Tracking calls to external libraries/stdlib.** Calls to `fmt.Println()`, `os.ReadFile()`, `console.log()`, or `requests.get()` are noise in an architecture graph. They are explicitly filtered out.
- **Replacing tree-sitter with a new parser.** The existing `ast_scanner.py` is extended, not replaced. Regex scanning remains the default.
- **Full method-level graph.** Method nodes are created on demand only when they participate in call-graph edges. A comprehensive method-level graph would be a separate feature (and would require rethinking graph scale).
- **Dynamic dispatch resolution.** If a variable is typed as an interface, we do not resolve which concrete implementation's method will be called at runtime. The call edge targets the method name as declared.
- **Call argument tracking.** We detect that A calls B, not what arguments are passed. Argument-level tracking is out of scope.

### Dependencies

- **No new required dependencies.** All features work with the existing regex-based scanner.
- **Optional**: tree-sitter and language packages (already optional dependencies since v0.3.0) enable more accurate call detection via AST queries.
- **Internal dependencies**:
  - `schema.py`: `EdgeType.CALLS` already exists — no change needed
  - `scanner.py`: Extended with `CallInfo`, `InterfaceInfo`, `MethodSetEntry` data classes and new inference functions
  - `graph.py`: No changes needed (Pydantic models accept any edge/node type)
  - `query.py`: No changes needed (all query functions operate on the graph generically)
  - `server.py`: No changes needed (no new MCP tools)
  - `recognizers/*.py`: Each recognizer extended with call detection
  - `ast_scanner.py`: Extended with call expression extraction
  - All test files: New test files for call-graph and cross-file interface features; no changes to existing test files

### Success Metrics

- **Go project self-test**: Scanning a real Go project (e.g., the user's project that prompted this feedback) produces `calls` edges between functions that actually call each other, and `implements` edges between structs and interfaces defined in different files.
- **Edge density improvement**: The edge/node ratio should increase measurably (from ~1.4 to ~2.0+) due to call-graph edges.
- **Blast radius accuracy**: For a function that is called by 5 other functions, `blast_radius` should report all 5 callers as impacted.
- **Zero regression**: All 793 existing tests pass unchanged.
- **Test coverage**: 60+ new tests, 853+ total.

### User Stories

As an AI coding agent, I want to see which functions call a function I'm about to modify so that I can assess the impact of my changes on callers.

As an AI coding agent, I want to know which structs implement a Go interface defined in a different file so that I can understand the full set of types affected when the interface changes.

As an AI coding agent, I want `blast_radius` to show me behavioral dependencies (who calls this function) not just structural ones (which module contains it) so that I get accurate impact analysis.

As a developer, I want `context_for("handle clipboard paste")` to return not just the clipboard module but also the functions that call clipboard operations so that the AI agent has full behavioral context.

As a developer, I want the architecture graph to reflect how my code actually runs (call paths) not just how it's organized (file structure) so that CodeGiraffe provides genuine architectural intelligence.

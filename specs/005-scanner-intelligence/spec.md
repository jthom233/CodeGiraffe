# Feature Specification: Scanner Intelligence Improvements (v0.4.0)

**Feature Branch**: `005-scanner-intelligence`
**Created**: 2026-02-13
**Status**: Draft
**Input**: Dogfood assessment — self-scan of Code Giraffe revealed 65% false-positive nodes and zero real architectural edges

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Clean Scan Without Test Noise (Priority: P1)

A developer initializes Code Giraffe on their Python project. The resulting architecture graph contains only production code entities — no test classes, test fixtures, or test helper patterns. Test files are excluded by default but can be opted-in via a configuration flag.

**Why this priority**: This is the highest-impact fix. Currently 108 of 166 scanned nodes are test classes, making the graph unusable for architectural reasoning. Eliminating test noise immediately improves every downstream tool (hotspots, context_for, drift detection, dashboard visualization).

**Independent Test**: Scan the Code Giraffe project itself. The result should contain fewer than 20 test-derived nodes (down from 108). All production classes (ArchGraph, StorageBackend, Scanner, etc.) should still appear.

**Acceptance Scenarios**:

1. **Given** a Python project with `tests/` and `src/` directories, **When** the scanner runs with default settings, **Then** files matching test patterns (`test_*.py`, `*_test.py`, `conftest.py`, files inside `tests/` or `test/` directories) are excluded from scanning.
2. **Given** a Python project, **When** the scanner runs with `include_tests=True`, **Then** test files are scanned but resulting nodes are tagged with `source: test` metadata so they can be filtered in queries and the dashboard.
3. **Given** test fixture content embedded in production code (e.g., example strings in docstrings), **When** the scanner encounters patterns inside triple-quoted strings or comments, **Then** those patterns are not promoted to graph nodes.

---

### User Story 2 — Import-Based Dependency Graph (Priority: P1)

A developer scans their project and the resulting graph shows which modules depend on which other modules, based on actual import statements. This reveals the real dependency structure of the codebase — which files import from which other files.

**Why this priority**: Import relationships are the most fundamental architectural signal in any Python project. Without them, the graph has no edges connecting real code. Currently zero import-based edges are detected, making the graph a disconnected collection of nodes.

**Independent Test**: Scan the Code Giraffe project. The result should contain at least 30 import-based edges (e.g., `server.py` imports from `graph.py`, `scanner.py`, `query.py`, etc.). Each edge should identify the source module, target module, and the specific symbols imported.

**Acceptance Scenarios**:

1. **Given** a Python file containing `from codegiraffe.graph import ArchGraph`, **When** the scanner processes this file, **Then** an edge of type `imports` is created from the source module node to the target module node, with metadata recording the imported symbols.
2. **Given** a Python file containing `import os` (stdlib), **When** the scanner processes this file, **Then** no edge is created for standard library imports (only project-internal imports produce edges).
3. **Given** a Python file containing `from codegiraffe.storage import JSONStorage`, **When** the target module exists in the scanned project, **Then** the edge target resolves to the actual module node, not a dangling reference.

---

### User Story 3 — Inheritance and Protocol Relationships (Priority: P2)

A developer scans their project and the resulting graph shows class inheritance chains and protocol/interface implementations. For example, `SQLiteStorage` implements `StorageBackend`, and `PythonASTRecognizer` implements `PatternRecognizer`.

**Why this priority**: Inheritance and protocol relationships are the second most important architectural signal after imports. They reveal the design patterns, abstraction layers, and extension points in the codebase. Currently none of these relationships are detected for Python.

**Independent Test**: Scan the Code Giraffe project. The result should show `implements` edges from concrete classes to their base classes/protocols (e.g., SQLiteStorage → StorageBackend, GoRecognizer → PatternRecognizer, JSONStorage → StorageBackend).

**Acceptance Scenarios**:

1. **Given** a Python class `class SQLiteStorage(StorageBackend):`, **When** the scanner processes this file, **Then** an edge of type `implements` is created from `service:SQLiteStorage` to `service:StorageBackend`.
2. **Given** a Python class with multiple bases `class MyClass(Base, Mixin):`, **When** the scanner processes this file, **Then** `implements` edges are created for each base class that exists as a node in the graph.
3. **Given** a base class defined in a different file than the subclass, **When** both files are scanned, **Then** the `implements` edge correctly connects them using cross-file resolution.

---

### User Story 4 — Module-Level Architecture View (Priority: P2)

A developer scans their project and the resulting graph includes module-level nodes representing Python files/packages. This provides a higher-level view of the architecture — which modules exist and how they relate to each other — complementing the existing class/function-level view.

**Why this priority**: Module-level nodes provide the "30,000 foot view" that developers need for understanding project structure. They serve as natural grouping containers for classes and functions, and their import relationships form the backbone of the dependency graph.

**Independent Test**: Scan the Code Giraffe project. The result should include module nodes for each significant source file (server, graph, scanner, storage, query, etc.) with import edges between them.

**Acceptance Scenarios**:

1. **Given** a Python project with `src/codegiraffe/graph.py`, **When** the scanner processes this file, **Then** a node of type `module` is created with ID `mod:codegiraffe.graph` and metadata including the file path.
2. **Given** a module node and classes defined within it, **When** the scan completes, **Then** `contains` edges connect the module node to the class/function nodes it defines.
3. **Given** a Python package directory with `__init__.py`, **When** the scanner processes the package, **Then** a single package-level module node is created (not one per `__init__.py` re-export).

---

### Edge Cases

- What happens when a test file imports production modules? The test file is excluded, but the production module's import edges are unaffected.
- What happens with circular imports? Both directions of the cycle are recorded as edges. No infinite loop in scanning.
- What happens with dynamic imports (`importlib.import_module`)? These are not detected by static scanning and are ignored.
- What happens with `__all__` re-exports in `__init__.py`? The scanner treats these as module-level exports but does not follow re-export chains.
- What happens with relative imports (`from . import graph`)? These are resolved relative to the package structure and produce the same edges as absolute imports.
- What happens when a class inherits from a class not found in the project (e.g., `Pydantic BaseModel`)? No `implements` edge is created — only project-internal relationships produce edges.

## Requirements *(mandatory)*

### Functional Requirements

**Test Exclusion:**
- **FR-001**: Scanner MUST exclude test files by default, matching patterns: `test_*.py`, `*_test.py`, `conftest.py`, and any file under `tests/`, `test/`, or `spec/` directories.
- **FR-002**: Scanner MUST accept an `include_tests` parameter (default: `False`) that, when enabled, scans test files but tags resulting nodes with `source: test` in metadata.
- **FR-003**: Scanner MUST filter out patterns found inside triple-quoted strings and single-line comments in production files to prevent test fixture false positives.

**Import Detection:**
- **FR-004**: Scanner MUST detect Python `import` and `from X import Y` statements and create `imports` edges between project-internal modules.
- **FR-005**: Scanner MUST NOT create import edges for standard library modules or third-party packages (only project-internal imports).
- **FR-006**: Scanner MUST resolve relative imports (`from . import X`, `from ..utils import Y`) to absolute module paths within the project.
- **FR-007**: Import edges MUST include metadata listing the specific symbols imported (e.g., `{symbols: ["ArchGraph", "GraphData"]}`).

**Inheritance Detection:**
- **FR-008**: Scanner MUST detect class definitions with base classes and create `implements` edges from the subclass to each base class that exists as a node in the graph.
- **FR-009**: Scanner MUST resolve base class references across files (e.g., `class Foo(Bar)` where `Bar` is defined in a different module).

**Module Nodes:**
- **FR-010**: Scanner MUST create nodes of type `module` for each Python source file in the project, with ID format `mod:<dotted.module.path>`.
- **FR-011**: Scanner MUST create `contains` edges from module nodes to the classes, functions, and other entities defined within that module.

**Schema Evolution:**
- **FR-012**: The `module` node type MUST be added to the node type enumeration.
- **FR-013**: The `imports`, `implements`, and `contains` edge types MUST be added to the edge type enumeration.

**Compatibility:**
- **FR-014**: All improvements MUST work with both regex and AST scanner modes.
- **FR-015**: Existing graphs (pre-v0.4.0) MUST continue to load without migration.
- **FR-016**: All existing tests (426) MUST continue to pass without modification.

### Key Entities

- **Module Node**: Represents a Python source file. Attributes: dotted module path, file path, package membership. Connected to its contained classes/functions via `contains` edges and to other modules via `imports` edges.
- **Import Edge**: Represents a Python import statement between two project-internal modules. Metadata: list of imported symbols, import style (absolute vs relative).
- **Implements Edge**: Represents class inheritance or protocol implementation. Connects a concrete class node to its base class/protocol node.
- **Contains Edge**: Represents the ownership relationship between a module and the entities defined within it.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Self-scan of Code Giraffe produces fewer than 20 test-derived nodes (down from 108), with all 36 real production classes still present.
- **SC-002**: Self-scan detects at least 30 import-based edges reflecting real module dependencies (up from 0).
- **SC-003**: Self-scan detects class inheritance relationships for all storage backends, recognizers, and other protocol implementations (at least 10 `implements` edges).
- **SC-004**: Self-scan produces module nodes for all 15 source files under `src/codegiraffe/`, connected via `contains` edges to their defined classes.
- **SC-005**: Scanning a 1000-file project completes in under 30 seconds with the new detection features enabled.
- **SC-006**: All existing 426 tests pass, plus new tests covering each improvement area (target: 60+ new tests).
- **SC-007**: The web dashboard renders a visually meaningful, connected graph of the Code Giraffe project itself — with clearly visible module clusters, import flows, and inheritance hierarchies.

## Assumptions

- Standard library modules are identified by checking against a known list or by verifying the import target exists within the project directory.
- Third-party packages are identified by exclusion — if the import target is neither stdlib nor within the project, it's third-party.
- The `include_tests` parameter applies to the `codegiraffe_init` and `codegiraffe_sync` MCP tools via a new optional parameter.
- Test file patterns are based on Python community conventions (pytest, unittest). Custom patterns are not supported in this version.
- Module dotted paths are derived from the file system path relative to the project root, following Python package conventions.

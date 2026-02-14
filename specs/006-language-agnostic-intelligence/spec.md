# Specification

## Requirements

## Code Giraffe v0.6.0 — Language-Agnostic Scanner Intelligence

### Problem Statement
The v0.4.0 scanner intelligence features (module nodes, import edges, contains edges, inheritance/implementation edges) only apply to Python files. All other 8 supported languages (TypeScript, Go, Rust, Java, C#, C/C++, PHP, Ruby) get the old-style node-only treatment with minimal edge inference. This creates a dramatic quality gap: Python projects get 0.5+ edge/node ratio while Go/TS/etc projects get 0.1-0.3, making the architecture graph too sparse to be useful for hotspot analysis, context scoring, blast radius, or dashboard visualization.

### Goal
Move scanner intelligence out of the Python-specific code path into the universal scanner pipeline. Each language recognizer provides language-specific import parsing and inheritance/implementation detection; the scanner handles module node creation, contains edges, and cross-file edge inference uniformly for all languages.

### Requirements

#### R1: Language-Agnostic Module Nodes
- Every source file scanned (regardless of language) MUST produce a `module` type node
- Module node ID format: `mod:{package}.{filename_stem}` (consistent with Python convention)
- Module node metadata MUST include `package` and `source` fields
- Module nodes created in the universal scanner pipeline, NOT in individual recognizers

#### R2: Language-Agnostic Contains Edges
- Every entity (service, endpoint, worker, etc.) detected in a file MUST have a `contains` edge FROM its module node TO the entity
- Contains edges created in the universal scanner pipeline after recognizer returns results
- Contains edge metadata includes `inferred: true`

#### R3: Recognizer Import Protocol
- Define a new optional field on `ScanResult`: `imports: list[ImportInfo]` where `ImportInfo` contains:
  - `module_path`: the imported module/package path (project-relative)
  - `symbols`: list of imported symbol names (empty list if whole-module import)
  - `style`: "absolute" | "relative" | "wildcard"
- Each recognizer MAY return import information via this field
- The scanner pipeline converts these into `imports` type edges between module nodes
- Only project-internal imports should be returned (recognizers filter out stdlib/third-party)

#### R4: Recognizer Inheritance/Implementation Protocol
- Define a new optional field on `ScanResult`: `implementations: list[ImplementationInfo]` where `ImplementationInfo` contains:
  - `child_class`: name of the implementing class/struct
  - `parent_class`: name of the base class/interface/trait
  - `file_path`: file where the child is defined
- Each recognizer MAY return implementation information via this field
- The scanner pipeline converts these into `implements` type edges between service nodes
- Only project-internal implementations should be returned

#### R5: Go Recognizer Enhancement
- Parse full Go import blocks (single and grouped imports)
- Detect project-internal imports by matching against the project's module path from go.mod
- Return ImportInfo for each internal import
- Detect interface implementations: when a struct has method receivers matching an interface's method signatures (heuristic: same method names)
- Return ImplementationInfo for detected implementations

#### R6: TypeScript Recognizer Enhancement
- Parse ES6 import statements: `import { X } from './path'`, `import X from 'path'`, `import * as X from 'path'`
- Detect project-internal imports (relative paths starting with ./ or ../, or configured path aliases)
- Return ImportInfo for each internal import
- Detect class inheritance: `class X extends Y`, `class X implements Y`
- Return ImplementationInfo for extends/implements

#### R7: Rust Recognizer Enhancement
- Parse `use` statements: `use crate::module::Symbol`, `use super::Symbol`
- Detect project-internal imports (crate::, super::, self::)
- Return ImportInfo for each internal import
- Detect trait implementations: `impl Trait for Struct`
- Return ImplementationInfo for trait impls

#### R8: Java Recognizer Enhancement
- Parse import statements: `import com.project.package.Class`
- Detect project-internal imports by matching against project package prefix
- Return ImportInfo for each internal import
- Detect class inheritance: `class X extends Y`, `class X implements Y`
- Return ImplementationInfo for extends/implements

#### R9: C# Recognizer Enhancement
- Parse `using` statements: `using Namespace.SubNamespace`
- Detect project-internal usings by matching against project namespace
- Return ImportInfo for each internal using
- Detect inheritance: `class X : BaseClass`, `class X : IInterface`
- Return ImplementationInfo for inheritance/implementation

#### R10: C/C++ Recognizer Enhancement
- Parse `#include` directives for local headers: `#include "path/file.h"`
- Detect project-internal includes (quoted includes, not angle-bracket system includes)
- Return ImportInfo for each internal include
- Detect class inheritance: `class X : public Y`
- Return ImplementationInfo for class inheritance

#### R11: PHP Recognizer Enhancement
- Parse `use` statements: `use App\Models\User`
- Detect project-internal uses by matching against project namespace
- Return ImportInfo for each internal use
- Detect inheritance: `class X extends Y`, `class X implements Y`
- Return ImplementationInfo for extends/implements

#### R12: Ruby Recognizer Enhancement
- Parse `require` and `require_relative` statements
- Detect project-internal requires (require_relative always internal, require with project paths)
- Return ImportInfo for each internal require
- Detect class inheritance: `class X < Y`
- Return ImplementationInfo for inheritance

#### R13: Test File Handling for All Languages
- Extend test file exclusion patterns to all languages:
  - Go: `*_test.go`
  - TypeScript/JS: `*.test.ts`, `*.spec.ts`, `__tests__/`
  - Rust: files in `tests/` directory, `#[cfg(test)]` modules
  - Java: `*Test.java`, `*Tests.java`, `src/test/`
  - C#: `*Tests.cs`, `*Test.cs`
  - C/C++: `*_test.cpp`, `*_test.c`, `test_*.cpp`
  - PHP: `*Test.php`, `tests/`
  - Ruby: `*_test.rb`, `*_spec.rb`, `spec/`
- When `include_tests=True`, tag with `source: test` metadata (matching Python behavior)

#### R14: Backward Compatibility
- All changes MUST be backward compatible
- Existing Python scanner intelligence MUST continue to work identically
- The new `imports` and `implementations` fields on ScanResult default to empty lists
- Recognizers that don't implement the new protocol continue to work unchanged
- Existing tests (566) MUST continue to pass

### Non-Goals
- Full call-graph analysis (function-to-function calls across packages)
- Dynamic/runtime relationship detection
- Constructor dependency injection inference
- Channel/goroutine flow analysis
- These are deferred to Direction B / v0.7.0

### Success Metrics
- Go project (Nexus-like): edge/node ratio increases from ~0.27 to 0.5+
- All 9 language recognizers return import information
- At least Go, TypeScript, Java, C# return implementation information
- Self-scan of CodeGiraffe itself: edge count increases significantly
- Zero regression in existing 566 tests
- New test coverage: ~100+ new tests across all recognizers

## User Stories

As an AI coding agent, I want CodeGiraffe to show rich module dependency graphs for Go/TypeScript/Rust/Java projects so that I can understand blast radius before making changes.

As an AI coding agent, I want to see which structs implement which interfaces in Go projects so that I can find all concrete implementations when modifying an interface.

As a developer, I want CodeGiraffe's architecture graph to be equally useful across all 9 supported languages, not just Python.

As an AI coding agent, I want CodeGiraffe to exclude test files by default for all languages so that the architecture graph shows only production code structure.

As a developer using the dashboard, I want to see connected module dependency graphs instead of isolated node clusters so that I can visually understand system architecture.

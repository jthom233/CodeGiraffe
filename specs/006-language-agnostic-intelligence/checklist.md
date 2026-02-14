# Implementation & Validation Checklist

Based on: ./specs/006-language-agnostic-intelligence/spec.md

## Requirements Validation

- [ ] Every source file scanned (regardless of language) MUST produce a `module` type node
- [ ] Module node ID format: `mod:{package}.{filename_stem}` (consistent with Python convention)
- [ ] Module node metadata MUST include `package` and `source` fields
- [ ] Module nodes created in the universal scanner pipeline, NOT in individual recognizers
- [ ] Contains edges created in the universal scanner pipeline after recognizer returns results
- [ ] Contains edge metadata includes `inferred: true`
- [ ] `module_path`: the imported module/package path (project-relative)
- [ ] `symbols`: list of imported symbol names (empty list if whole-module import)
- [ ] `style`: "absolute" | "relative" | "wildcard"
- [ ] Each recognizer MAY return import information via this field
- [ ] The scanner pipeline converts these into `imports` type edges between module nodes
- [ ] Only project-internal imports should be returned (recognizers filter out stdlib/third-party)
- [ ] `child_class`: name of the implementing class/struct
- [ ] `parent_class`: name of the base class/interface/trait
- [ ] `file_path`: file where the child is defined
- [ ] Each recognizer MAY return implementation information via this field
- [ ] The scanner pipeline converts these into `implements` type edges between service nodes
- [ ] Only project-internal implementations should be returned
- [ ] Parse full Go import blocks (single and grouped imports)
- [ ] Detect project-internal imports by matching against the project's module path from go.mod
- [ ] Return ImportInfo for each internal import
- [ ] Return ImplementationInfo for detected implementations
- [ ] Return ImportInfo for each internal import
- [ ] Detect class inheritance: `class X extends Y`, `class X implements Y`
- [ ] Return ImplementationInfo for extends/implements
- [ ] Parse `use` statements: `use crate::module::Symbol`, `use super::Symbol`
- [ ] Detect project-internal imports (crate::, super::, self::)
- [ ] Return ImportInfo for each internal import
- [ ] Detect trait implementations: `impl Trait for Struct`
- [ ] Return ImplementationInfo for trait impls
- [ ] Parse import statements: `import com.project.package.Class`
- [ ] Detect project-internal imports by matching against project package prefix
- [ ] Return ImportInfo for each internal import
- [ ] Detect class inheritance: `class X extends Y`, `class X implements Y`
- [ ] Return ImplementationInfo for extends/implements
- [ ] Parse `using` statements: `using Namespace.SubNamespace`
- [ ] Detect project-internal usings by matching against project namespace
- [ ] Return ImportInfo for each internal using
- [ ] Detect inheritance: `class X : BaseClass`, `class X : IInterface`
- [ ] Return ImplementationInfo for inheritance/implementation
- [ ] Parse `#include` directives for local headers: `#include "path/file.h"`
- [ ] Detect project-internal includes (quoted includes, not angle-bracket system includes)
- [ ] Return ImportInfo for each internal include
- [ ] Detect class inheritance: `class X : public Y`
- [ ] Return ImplementationInfo for class inheritance
- [ ] Parse `use` statements: `use App\Models\User`
- [ ] Detect project-internal uses by matching against project namespace
- [ ] Return ImportInfo for each internal use
- [ ] Detect inheritance: `class X extends Y`, `class X implements Y`
- [ ] Return ImplementationInfo for extends/implements
- [ ] Parse `require` and `require_relative` statements
- [ ] Detect project-internal requires (require_relative always internal, require with project paths)
- [ ] Return ImportInfo for each internal require
- [ ] Detect class inheritance: `class X < Y`
- [ ] Return ImplementationInfo for inheritance
- [ ] Extend test file exclusion patterns to all languages:
- [ ] Go: `*_test.go`
- [ ] TypeScript/JS: `*.test.ts`, `*.spec.ts`, `__tests__/`
- [ ] Rust: files in `tests/` directory, `#[cfg(test)]` modules
- [ ] Java: `*Test.java`, `*Tests.java`, `src/test/`
- [ ] C#: `*Tests.cs`, `*Test.cs`
- [ ] C/C++: `*_test.cpp`, `*_test.c`, `test_*.cpp`
- [ ] PHP: `*Test.php`, `tests/`
- [ ] Ruby: `*_test.rb`, `*_spec.rb`, `spec/`
- [ ] When `include_tests=True`, tag with `source: test` metadata (matching Python behavior)
- [ ] All changes MUST be backward compatible
- [ ] Existing Python scanner intelligence MUST continue to work identically
- [ ] The new `imports` and `implementations` fields on ScanResult default to empty lists
- [ ] Recognizers that don't implement the new protocol continue to work unchanged
- [ ] Existing tests (566) MUST continue to pass
- [ ] Full call-graph analysis (function-to-function calls across packages)
- [ ] Dynamic/runtime relationship detection
- [ ] Constructor dependency injection inference
- [ ] Channel/goroutine flow analysis
- [ ] These are deferred to Direction B / v0.7.0
- [ ] Go project (Nexus-like): edge/node ratio increases from ~0.27 to 0.5+
- [ ] All 9 language recognizers return import information
- [ ] At least Go, TypeScript, Java, C# return implementation information
- [ ] Self-scan of CodeGiraffe itself: edge count increases significantly
- [ ] Zero regression in existing 566 tests
- [ ] New test coverage: ~100+ new tests across all recognizers

## Implementation Checklist

- [ ] Code follows project style guide
- [ ] Functions have clear documentation
- [ ] Error handling is comprehensive
- [ ] Input validation is performed
- [ ] Logging is appropriate
- [ ] Performance is acceptable
- [ ] Security considerations addressed

## Testing Checklist

- [ ] Unit tests written for all functions
- [ ] Integration tests cover main workflows
- [ ] Edge cases are tested
- [ ] Error conditions are tested
- [ ] Performance tests (if applicable)
- [ ] All tests pass
- [ ] Test coverage >80%

## Quality Assurance

- [ ] Code review completed
- [ ] Documentation updated
- [ ] CHANGELOG.md updated
- [ ] No compiler warnings
- [ ] Linter passes (clippy, etc.)
- [ ] Dependencies are up to date

## Deployment Readiness

- [ ] All tests pass in CI
- [ ] Version number updated
- [ ] Release notes prepared
- [ ] Breaking changes documented
- [ ] Migration guide provided (if needed)

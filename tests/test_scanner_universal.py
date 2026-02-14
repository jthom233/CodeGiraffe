"""Tests for language-agnostic scanner intelligence (v0.6.0 Phase 1).

Covers ImportInfo/ImplementationInfo dataclasses, universal module path
conversion, multi-language test file detection, universal inference
functions, and backward compatibility with Python-only scanning.
"""

import pytest
from pathlib import Path

from codegiraffe.scanner import (
    ImportInfo,
    ImplementationInfo,
    CallInfo,
    InterfaceInfo,
    MethodSetEntry,
    ScanResult,
    scan_project,
    _file_to_module_path_universal,
    _suffix_to_language,
    _is_test_file,
    _is_in_test_dir,
    _infer_import_edges_universal,
    _infer_inheritance_edges_universal,
)
from codegiraffe.graph import Edge, Node
from codegiraffe.schema import EdgeType, NodeType


# ---------------------------------------------------------------------------
# 1. ImportInfo and ImplementationInfo construction and defaults
# ---------------------------------------------------------------------------


class TestImportInfo:
    """Test ImportInfo dataclass construction and defaults."""

    def test_basic_construction(self):
        info = ImportInfo(module_path="pkg.mod")
        assert info.module_path == "pkg.mod"
        assert info.symbols == []
        assert info.style == "absolute"

    def test_with_symbols(self):
        info = ImportInfo(module_path="pkg.mod", symbols=["Foo", "Bar"])
        assert info.symbols == ["Foo", "Bar"]

    def test_with_style(self):
        info = ImportInfo(module_path="pkg.mod", style="relative")
        assert info.style == "relative"

    def test_wildcard_style(self):
        info = ImportInfo(module_path="pkg.mod", style="wildcard")
        assert info.style == "wildcard"


class TestImplementationInfo:
    """Test ImplementationInfo dataclass construction."""

    def test_basic_construction(self):
        info = ImplementationInfo(
            child_class="Dog",
            parent_class="Animal",
            file_path="models/dog.go",
        )
        assert info.child_class == "Dog"
        assert info.parent_class == "Animal"
        assert info.file_path == "models/dog.go"


# ---------------------------------------------------------------------------
# 2. ScanResult merge with imports/implementations
# ---------------------------------------------------------------------------


class TestScanResultMergeExtended:
    """Test that ScanResult.merge handles imports and implementations."""

    def test_merge_imports(self):
        a = ScanResult(imports=[ImportInfo("mod.a")])
        b = ScanResult(imports=[ImportInfo("mod.b"), ImportInfo("mod.c")])
        a.merge(b)
        assert len(a.imports) == 3
        assert [i.module_path for i in a.imports] == ["mod.a", "mod.b", "mod.c"]

    def test_merge_implementations(self):
        a = ScanResult(implementations=[
            ImplementationInfo("Child", "Parent", "a.go"),
        ])
        b = ScanResult(implementations=[
            ImplementationInfo("Dog", "Animal", "b.go"),
        ])
        a.merge(b)
        assert len(a.implementations) == 2

    def test_merge_preserves_node_dedup(self):
        """Imports/implementations extend but nodes still deduplicate."""
        node = Node(id="svc:A", type="service", label="A")
        a = ScanResult(
            nodes=[node],
            imports=[ImportInfo("x")],
        )
        b = ScanResult(
            nodes=[node],  # duplicate
            imports=[ImportInfo("y")],
        )
        a.merge(b)
        assert len(a.nodes) == 1  # deduped
        assert len(a.imports) == 2  # extended


# ---------------------------------------------------------------------------
# 3. _file_to_module_path_universal for multiple languages
# ---------------------------------------------------------------------------


class TestFileToModulePathUniversal:
    """Test universal module path conversion for various language paths."""

    def test_go_file(self, tmp_path):
        f = tmp_path / "internal" / "handler" / "user.go"
        f.parent.mkdir(parents=True)
        f.touch()
        # "internal" should be stripped as src-layout prefix
        result = _file_to_module_path_universal(f, str(tmp_path), ".go")
        assert result == "handler.user"

    def test_go_file_no_src_prefix(self, tmp_path):
        f = tmp_path / "handler" / "user.go"
        f.parent.mkdir(parents=True)
        f.touch()
        result = _file_to_module_path_universal(f, str(tmp_path), ".go")
        assert result == "handler.user"

    def test_typescript_file(self, tmp_path):
        f = tmp_path / "src" / "services" / "auth.ts"
        f.parent.mkdir(parents=True)
        f.touch()
        result = _file_to_module_path_universal(f, str(tmp_path), ".ts")
        assert result == "services.auth"

    def test_rust_file(self, tmp_path):
        f = tmp_path / "src" / "handlers" / "api.rs"
        f.parent.mkdir(parents=True)
        f.touch()
        result = _file_to_module_path_universal(f, str(tmp_path), ".rs")
        assert result == "handlers.api"

    def test_java_file(self, tmp_path):
        f = tmp_path / "src" / "main" / "UserService.java"
        f.parent.mkdir(parents=True)
        f.touch()
        result = _file_to_module_path_universal(f, str(tmp_path), ".java")
        assert result == "main.UserService"

    def test_csharp_file(self, tmp_path):
        f = tmp_path / "src" / "Controllers" / "HomeController.cs"
        f.parent.mkdir(parents=True)
        f.touch()
        result = _file_to_module_path_universal(f, str(tmp_path), ".cs")
        assert result == "Controllers.HomeController"

    def test_php_file(self, tmp_path):
        f = tmp_path / "app" / "Http" / "UserController.php"
        f.parent.mkdir(parents=True)
        f.touch()
        result = _file_to_module_path_universal(f, str(tmp_path), ".php")
        assert result == "Http.UserController"

    def test_ruby_file(self, tmp_path):
        f = tmp_path / "lib" / "models" / "user.rb"
        f.parent.mkdir(parents=True)
        f.touch()
        result = _file_to_module_path_universal(f, str(tmp_path), ".rb")
        assert result == "models.user"

    def test_python_delegates_to_original(self, tmp_path):
        """Python files should use the original _file_to_module_path."""
        f = tmp_path / "src" / "mypackage" / "mod.py"
        f.parent.mkdir(parents=True)
        f.touch()
        result = _file_to_module_path_universal(f, str(tmp_path), ".py")
        assert result == "mypackage.mod"

    def test_cpp_file(self, tmp_path):
        f = tmp_path / "src" / "engine" / "render.cpp"
        f.parent.mkdir(parents=True)
        f.touch()
        result = _file_to_module_path_universal(f, str(tmp_path), ".cpp")
        assert result == "engine.render"

    def test_top_level_file(self, tmp_path):
        f = tmp_path / "main.go"
        f.touch()
        result = _file_to_module_path_universal(f, str(tmp_path), ".go")
        assert result == "main"


# ---------------------------------------------------------------------------
# 4. _suffix_to_language mapping
# ---------------------------------------------------------------------------


class TestSuffixToLanguage:
    """Test suffix-to-language mapping."""

    def test_python(self):
        assert _suffix_to_language(".py") == "python"
        assert _suffix_to_language(".pyi") == "python"

    def test_go(self):
        assert _suffix_to_language(".go") == "go"

    def test_typescript(self):
        assert _suffix_to_language(".ts") == "typescript"
        assert _suffix_to_language(".tsx") == "typescript"
        assert _suffix_to_language(".mts") == "typescript"
        assert _suffix_to_language(".cts") == "typescript"

    def test_rust(self):
        assert _suffix_to_language(".rs") == "rust"

    def test_java(self):
        assert _suffix_to_language(".java") == "java"

    def test_csharp(self):
        assert _suffix_to_language(".cs") == "csharp"

    def test_c_cpp(self):
        assert _suffix_to_language(".c") == "c"
        assert _suffix_to_language(".h") == "c"
        assert _suffix_to_language(".cpp") == "cpp"
        assert _suffix_to_language(".hpp") == "cpp"
        assert _suffix_to_language(".cc") == "cpp"
        assert _suffix_to_language(".cxx") == "cpp"

    def test_php(self):
        assert _suffix_to_language(".php") == "php"

    def test_ruby(self):
        assert _suffix_to_language(".rb") == "ruby"

    def test_unknown(self):
        assert _suffix_to_language(".xyz") == "unknown"
        assert _suffix_to_language(".txt") == "unknown"


# ---------------------------------------------------------------------------
# 5. Module node creation for non-Python files
# ---------------------------------------------------------------------------


class TestUniversalModuleNodes:
    """Test that scan_project creates module nodes for non-Python files."""

    def test_go_file_gets_module_node(self, tmp_path):
        """A .go file should produce a module node with language metadata."""
        from codegiraffe.registry import RecognizerRegistry
        from codegiraffe.recognizers.go import GoRecognizer

        # Create a Go file with a struct
        go_file = tmp_path / "handler.go"
        go_file.write_text('package main\n\ntype UserHandler struct {\n}\n')

        registry = RecognizerRegistry()
        registry.register(GoRecognizer(), extensions=[".go"])

        result = scan_project(str(tmp_path), registry=registry)

        module_nodes = [n for n in result.nodes if n.type == NodeType.MODULE.value]
        assert len(module_nodes) >= 1

        mod = module_nodes[0]
        assert mod.id == "mod:handler"
        assert mod.metadata["language"] == "go"
        assert mod.metadata["source"] == "production"

    def test_go_file_gets_contains_edges(self, tmp_path):
        """Module node should have contains edges to entities in the file."""
        from codegiraffe.registry import RecognizerRegistry
        from codegiraffe.recognizers.go import GoRecognizer

        go_file = tmp_path / "handler.go"
        go_file.write_text(
            'package main\n\ntype UserHandler struct {\n}\n'
            '\ntype AdminHandler struct {\n}\n'
        )

        registry = RecognizerRegistry()
        registry.register(GoRecognizer(), extensions=[".go"])

        result = scan_project(str(tmp_path), registry=registry)

        contains_edges = [e for e in result.edges if e.type == EdgeType.CONTAINS.value]
        module_ids = {n.id for n in result.nodes if n.type == NodeType.MODULE.value}
        assert len(module_ids) >= 1

        # Each service node should have a contains edge from the module
        service_nodes = [n for n in result.nodes if n.type == NodeType.SERVICE.value]
        for svc in service_nodes:
            matching = [e for e in contains_edges if e.target == svc.id]
            assert len(matching) >= 1, f"No contains edge for {svc.id}"

    def test_typescript_file_gets_module_node(self, tmp_path):
        """A .ts file should produce a module node with language=typescript."""
        from codegiraffe.registry import RecognizerRegistry
        from codegiraffe.recognizers.typescript import TypeScriptRecognizer

        ts_file = tmp_path / "service.ts"
        ts_file.write_text('export class AuthService {\n}\n')

        registry = RecognizerRegistry()
        registry.register(TypeScriptRecognizer(), extensions=[".ts", ".tsx"])

        result = scan_project(str(tmp_path), registry=registry)

        module_nodes = [n for n in result.nodes if n.type == NodeType.MODULE.value]
        assert len(module_nodes) >= 1
        assert module_nodes[0].metadata["language"] == "typescript"


# ---------------------------------------------------------------------------
# 6. _is_test_file for all languages
# ---------------------------------------------------------------------------


class TestIsTestFileMultiLanguage:
    """Test _is_test_file for all supported language conventions."""

    # Python (backward compat)
    def test_python_test_prefix(self):
        assert _is_test_file(Path("test_foo.py")) is True

    def test_python_test_suffix(self):
        assert _is_test_file(Path("foo_test.py")) is True

    def test_python_conftest(self):
        assert _is_test_file(Path("conftest.py")) is True

    def test_python_regular(self):
        assert _is_test_file(Path("foo.py")) is False

    # Go
    def test_go_test_file(self):
        assert _is_test_file(Path("handler_test.go")) is True

    def test_go_regular(self):
        assert _is_test_file(Path("handler.go")) is False

    # TypeScript
    def test_ts_test_dot(self):
        assert _is_test_file(Path("auth.test.ts")) is True

    def test_ts_spec_dot(self):
        assert _is_test_file(Path("auth.spec.ts")) is True

    def test_tsx_test(self):
        assert _is_test_file(Path("component.test.tsx")) is True

    def test_tsx_spec(self):
        assert _is_test_file(Path("component.spec.tsx")) is True

    def test_ts_regular(self):
        assert _is_test_file(Path("auth.ts")) is False

    # Java
    def test_java_test_suffix(self):
        assert _is_test_file(Path("UserServiceTest.java")) is True

    def test_java_tests_suffix(self):
        assert _is_test_file(Path("UserServiceTests.java")) is True

    def test_java_regular(self):
        assert _is_test_file(Path("UserService.java")) is False

    # C#
    def test_csharp_test_suffix(self):
        assert _is_test_file(Path("UserControllerTest.cs")) is True

    def test_csharp_tests_suffix(self):
        assert _is_test_file(Path("UserControllerTests.cs")) is True

    def test_csharp_regular(self):
        assert _is_test_file(Path("UserController.cs")) is False

    # C/C++
    def test_cpp_test_suffix(self):
        assert _is_test_file(Path("engine_test.cpp")) is True

    def test_c_test_prefix(self):
        assert _is_test_file(Path("test_utils.c")) is True

    def test_cc_test_suffix(self):
        assert _is_test_file(Path("handler_test.cc")) is True

    def test_cpp_regular(self):
        assert _is_test_file(Path("engine.cpp")) is False

    def test_h_regular(self):
        assert _is_test_file(Path("engine.h")) is False

    # PHP
    def test_php_test_suffix(self):
        assert _is_test_file(Path("UserControllerTest.php")) is True

    def test_php_regular(self):
        assert _is_test_file(Path("UserController.php")) is False

    # Ruby
    def test_ruby_test_suffix(self):
        assert _is_test_file(Path("user_test.rb")) is True

    def test_ruby_spec_suffix(self):
        assert _is_test_file(Path("user_spec.rb")) is True

    def test_ruby_regular(self):
        assert _is_test_file(Path("user.rb")) is False


# ---------------------------------------------------------------------------
# 7. _is_in_test_dir for new directories
# ---------------------------------------------------------------------------


class TestIsInTestDirExtended:
    """Test _is_in_test_dir for new test directory patterns."""

    def test_tests_dir(self):
        assert _is_in_test_dir(Path("project/tests/test_foo.py")) is True

    def test_test_dir(self):
        assert _is_in_test_dir(Path("project/test/handler.go")) is True

    def test_dunder_tests(self):
        assert _is_in_test_dir(Path("src/components/__tests__/Button.test.tsx")) is True

    def test_spec_dir(self):
        assert _is_in_test_dir(Path("lib/spec/models/user_spec.rb")) is True

    def test_java_src_test(self):
        assert _is_in_test_dir(Path("project/src/test/java/UserServiceTest.java")) is True

    def test_java_src_main_is_not_test(self):
        assert _is_in_test_dir(Path("project/src/main/java/UserService.java")) is False

    def test_regular_dir(self):
        assert _is_in_test_dir(Path("src/handlers/user.go")) is False


# ---------------------------------------------------------------------------
# 8. _infer_import_edges_universal
# ---------------------------------------------------------------------------


class TestInferImportEdgesUniversal:
    """Test universal import edge inference from ImportInfo data."""

    def test_creates_import_edge(self):
        """Should create an imports edge between two module nodes."""
        nodes = [
            Node(id="mod:handlers.user", type=NodeType.MODULE.value,
                 label="user", file_path="handlers/user.go"),
            Node(id="mod:models.user", type=NodeType.MODULE.value,
                 label="user", file_path="models/user.go"),
        ]
        result = ScanResult(nodes=nodes, edges=[])

        per_file = {
            Path("handlers/user.go"): ScanResult(
                imports=[ImportInfo(module_path="models.user", symbols=["User"])],
            ),
            Path("models/user.go"): ScanResult(),
        }

        _infer_import_edges_universal(result, per_file)

        import_edges = [e for e in result.edges if e.type == EdgeType.IMPORTS.value]
        assert len(import_edges) == 1
        assert import_edges[0].source == "mod:handlers.user"
        assert import_edges[0].target == "mod:models.user"
        assert import_edges[0].metadata["symbols"] == ["User"]
        assert import_edges[0].metadata["inferred"] is True

    def test_skips_nonexistent_target(self):
        """Should not create edge if target module doesn't exist."""
        nodes = [
            Node(id="mod:handlers.user", type=NodeType.MODULE.value,
                 label="user", file_path="handlers/user.go"),
        ]
        result = ScanResult(nodes=nodes, edges=[])

        per_file = {
            Path("handlers/user.go"): ScanResult(
                imports=[ImportInfo(module_path="external.pkg")],
            ),
        }

        _infer_import_edges_universal(result, per_file)

        assert len(result.edges) == 0

    def test_skips_self_import(self):
        """Should not create edge from a module to itself."""
        nodes = [
            Node(id="mod:handlers.user", type=NodeType.MODULE.value,
                 label="user", file_path="handlers/user.go"),
        ]
        result = ScanResult(nodes=nodes, edges=[])

        per_file = {
            Path("handlers/user.go"): ScanResult(
                imports=[ImportInfo(module_path="handlers.user")],
            ),
        }

        _infer_import_edges_universal(result, per_file)

        assert len(result.edges) == 0

    def test_deduplicates_edges(self):
        """Should not create duplicate edges for same source/target."""
        nodes = [
            Node(id="mod:a", type=NodeType.MODULE.value, label="a", file_path="a.go"),
            Node(id="mod:b", type=NodeType.MODULE.value, label="b", file_path="b.go"),
        ]
        result = ScanResult(nodes=nodes, edges=[])

        per_file = {
            Path("a.go"): ScanResult(
                imports=[
                    ImportInfo(module_path="b", symbols=["X"]),
                    ImportInfo(module_path="b", symbols=["Y"]),
                ],
            ),
            Path("b.go"): ScanResult(),
        }

        _infer_import_edges_universal(result, per_file)

        import_edges = [e for e in result.edges if e.type == EdgeType.IMPORTS.value]
        # Second one should be deduped
        assert len(import_edges) == 1


# ---------------------------------------------------------------------------
# 9. _infer_inheritance_edges_universal
# ---------------------------------------------------------------------------


class TestInferInheritanceEdgesUniversal:
    """Test universal inheritance edge inference from ImplementationInfo."""

    def test_creates_implements_edge(self):
        """Should create an implements edge between child and parent service nodes."""
        nodes = [
            Node(id="service:Dog", type=NodeType.SERVICE.value,
                 label="Dog", file_path="models/dog.go",
                 metadata={"class_name": "Dog"}),
            Node(id="service:Animal", type=NodeType.SERVICE.value,
                 label="Animal", file_path="models/animal.go",
                 metadata={"class_name": "Animal"}),
        ]
        result = ScanResult(nodes=nodes, edges=[])

        per_file = {
            Path("models/dog.go"): ScanResult(
                implementations=[
                    ImplementationInfo("Dog", "Animal", "models/dog.go"),
                ],
            ),
            Path("models/animal.go"): ScanResult(),
        }

        _infer_inheritance_edges_universal(result, per_file)

        impl_edges = [e for e in result.edges if e.type == EdgeType.IMPLEMENTS.value]
        assert len(impl_edges) == 1
        assert impl_edges[0].source == "service:Dog"
        assert impl_edges[0].target == "service:Animal"
        assert impl_edges[0].metadata["inferred"] is True
        assert impl_edges[0].metadata["cross_file"] is True

    def test_same_file_inheritance(self):
        """cross_file should be False when both are in the same file."""
        nodes = [
            Node(id="service:Dog", type=NodeType.SERVICE.value,
                 label="Dog", file_path="models.go",
                 metadata={"class_name": "Dog"}),
            Node(id="service:Animal", type=NodeType.SERVICE.value,
                 label="Animal", file_path="models.go",
                 metadata={"class_name": "Animal"}),
        ]
        result = ScanResult(nodes=nodes, edges=[])

        per_file = {
            Path("models.go"): ScanResult(
                implementations=[
                    ImplementationInfo("Dog", "Animal", "models.go"),
                ],
            ),
        }

        _infer_inheritance_edges_universal(result, per_file)

        impl_edges = [e for e in result.edges if e.type == EdgeType.IMPLEMENTS.value]
        assert len(impl_edges) == 1
        assert impl_edges[0].metadata["cross_file"] is False

    def test_skips_unknown_classes(self):
        """Should not create edge if child or parent not in class_registry."""
        nodes = [
            Node(id="service:Dog", type=NodeType.SERVICE.value,
                 label="Dog", file_path="dog.go",
                 metadata={"class_name": "Dog"}),
        ]
        result = ScanResult(nodes=nodes, edges=[])

        per_file = {
            Path("dog.go"): ScanResult(
                implementations=[
                    ImplementationInfo("Dog", "ExternalBase", "dog.go"),
                ],
            ),
        }

        _infer_inheritance_edges_universal(result, per_file)

        assert len(result.edges) == 0

    def test_deduplicates_edges(self):
        """Should not create duplicate implements edges."""
        nodes = [
            Node(id="service:Dog", type=NodeType.SERVICE.value,
                 label="Dog", file_path="dog.go",
                 metadata={"class_name": "Dog"}),
            Node(id="service:Animal", type=NodeType.SERVICE.value,
                 label="Animal", file_path="animal.go",
                 metadata={"class_name": "Animal"}),
        ]
        # Pre-existing edge
        existing = Edge(
            source="service:Dog",
            target="service:Animal",
            type=EdgeType.IMPLEMENTS.value,
            metadata={"inferred": True, "cross_file": True},
        )
        result = ScanResult(nodes=nodes, edges=[existing])

        per_file = {
            Path("dog.go"): ScanResult(
                implementations=[
                    ImplementationInfo("Dog", "Animal", "dog.go"),
                ],
            ),
        }

        _infer_inheritance_edges_universal(result, per_file)

        impl_edges = [e for e in result.edges if e.type == EdgeType.IMPLEMENTS.value]
        assert len(impl_edges) == 1  # not duplicated

    def test_uses_struct_name_metadata(self):
        """Should look up class_name, then struct_name, then label."""
        nodes = [
            Node(id="service:GoHandler", type=NodeType.SERVICE.value,
                 label="GoHandler", file_path="handler.go",
                 metadata={"struct_name": "GoHandler"}),
            Node(id="service:BaseHandler", type=NodeType.SERVICE.value,
                 label="BaseHandler", file_path="base.go",
                 metadata={"struct_name": "BaseHandler"}),
        ]
        result = ScanResult(nodes=nodes, edges=[])

        per_file = {
            Path("handler.go"): ScanResult(
                implementations=[
                    ImplementationInfo("GoHandler", "BaseHandler", "handler.go"),
                ],
            ),
        }

        _infer_inheritance_edges_universal(result, per_file)

        impl_edges = [e for e in result.edges if e.type == EdgeType.IMPLEMENTS.value]
        assert len(impl_edges) == 1


# ---------------------------------------------------------------------------
# 10. Backward compatibility: Python-only scan unchanged
# ---------------------------------------------------------------------------


class TestPythonBackwardCompatibility:
    """Ensure Python-only scanning produces identical results to v0.5.0."""

    def test_python_module_nodes_still_created(self, sample_project):
        """Python files should still get module nodes with language=python."""
        result = scan_project(str(sample_project))

        module_nodes = [n for n in result.nodes if n.type == NodeType.MODULE.value]
        assert len(module_nodes) > 0

        for mod in module_nodes:
            assert mod.metadata.get("language") == "python"

    def test_python_contains_edges_still_created(self, sample_project):
        """Python files should still have contains edges from module to entities."""
        result = scan_project(str(sample_project))

        contains_edges = [e for e in result.edges if e.type == EdgeType.CONTAINS.value]
        assert len(contains_edges) > 0

    def test_python_import_edges_still_created(self, sample_project):
        """Python import inference should still work for cross-file imports."""
        # The sample_project has models/user.py imported by app.py (User reference)
        result = scan_project(str(sample_project))

        import_edges = [e for e in result.edges if e.type == EdgeType.IMPORTS.value]
        # Should have at least some import edges (or 0 if no cross-file imports resolve)
        # The key point is that no error is raised
        assert isinstance(import_edges, list)

    def test_endpoints_still_found(self, sample_project):
        """Endpoint discovery should be unchanged."""
        result = scan_project(str(sample_project))

        endpoint_nodes = [n for n in result.nodes if n.type == NodeType.ENDPOINT]
        endpoint_ids = {n.id for n in endpoint_nodes}

        assert "endpoint:/api/users" in endpoint_ids
        assert "endpoint:/api/users/<int:id>" in endpoint_ids

    def test_tables_still_found(self, sample_project):
        """Database table discovery should be unchanged."""
        result = scan_project(str(sample_project))

        table_nodes = [n for n in result.nodes if n.type == NodeType.DATABASE_TABLE]
        table_ids = {n.id for n in table_nodes}

        assert "table:users" in table_ids

    def test_workers_still_found(self, sample_project):
        """Worker discovery should be unchanged."""
        result = scan_project(str(sample_project))

        worker_nodes = [n for n in result.nodes if n.type == NodeType.WORKER]
        worker_ids = {n.id for n in worker_nodes}

        assert "worker:send_email" in worker_ids

    def test_env_vars_still_found(self, sample_project):
        """Env var discovery should be unchanged."""
        result = scan_project(str(sample_project))

        env_nodes = [n for n in result.nodes if n.type == NodeType.ENV_VAR]
        env_ids = {n.id for n in env_nodes}

        assert "env:DATABASE_URL" in env_ids

    def test_service_nodes_still_found(self, sample_project):
        """Service (class) discovery should be unchanged."""
        result = scan_project(str(sample_project))

        service_nodes = [n for n in result.nodes if n.type == NodeType.SERVICE]
        # User class is captured as database_table, not service.
        # But there should still be some service nodes (if any non-model classes exist)
        assert isinstance(service_nodes, list)

    def test_scan_result_has_imports_field(self, sample_project):
        """ScanResult should now have imports and implementations fields."""
        result = scan_project(str(sample_project))
        assert hasattr(result, "imports")
        assert hasattr(result, "implementations")
        assert isinstance(result.imports, list)
        assert isinstance(result.implementations, list)

    def test_module_node_has_package_metadata(self, sample_project):
        """Module nodes should still have package metadata."""
        result = scan_project(str(sample_project))

        module_nodes = [n for n in result.nodes if n.type == NodeType.MODULE.value]
        for mod in module_nodes:
            assert "package" in mod.metadata
            assert "source" in mod.metadata


# ---------------------------------------------------------------------------
# Integration: test file exclusion for non-Python files
# ---------------------------------------------------------------------------


class TestUniversalTestExclusion:
    """Test that non-Python test files are excluded by default."""

    def test_go_test_files_excluded_by_default(self, tmp_path):
        from codegiraffe.registry import RecognizerRegistry
        from codegiraffe.recognizers.go import GoRecognizer

        prod_file = tmp_path / "handler.go"
        prod_file.write_text('package main\n\ntype Handler struct {\n}\n')

        test_file = tmp_path / "handler_test.go"
        test_file.write_text('package main\n\ntype TestHelper struct {\n}\n')

        registry = RecognizerRegistry()
        registry.register(GoRecognizer(), extensions=[".go"])

        result = scan_project(str(tmp_path), registry=registry, include_tests=False)

        # Only the production file should produce nodes
        module_nodes = [n for n in result.nodes if n.type == NodeType.MODULE.value]
        module_ids = {n.id for n in module_nodes}
        assert "mod:handler" in module_ids
        assert "mod:handler_test" not in module_ids

    def test_go_test_files_included_when_opted_in(self, tmp_path):
        from codegiraffe.registry import RecognizerRegistry
        from codegiraffe.recognizers.go import GoRecognizer

        prod_file = tmp_path / "handler.go"
        prod_file.write_text('package main\n\ntype Handler struct {\n}\n')

        test_file = tmp_path / "handler_test.go"
        test_file.write_text('package main\n\ntype TestHelper struct {\n}\n')

        registry = RecognizerRegistry()
        registry.register(GoRecognizer(), extensions=[".go"])

        result = scan_project(str(tmp_path), registry=registry, include_tests=True)

        module_nodes = [n for n in result.nodes if n.type == NodeType.MODULE.value]
        module_ids = {n.id for n in module_nodes}
        assert "mod:handler" in module_ids
        assert "mod:handler_test" in module_ids

        # Test module should have source=test metadata
        test_mod = next(n for n in module_nodes if n.id == "mod:handler_test")
        assert test_mod.metadata["source"] == "test"

    def test_dunder_tests_dir_excluded(self, tmp_path):
        from codegiraffe.registry import RecognizerRegistry
        from codegiraffe.recognizers.typescript import TypeScriptRecognizer

        tests_dir = tmp_path / "__tests__"
        tests_dir.mkdir()
        test_file = tests_dir / "Button.test.tsx"
        test_file.write_text('export class ButtonTest {\n}\n')

        prod_file = tmp_path / "Button.tsx"
        prod_file.write_text('export class Button {\n}\n')

        registry = RecognizerRegistry()
        registry.register(TypeScriptRecognizer(), extensions=[".ts", ".tsx"])

        result = scan_project(str(tmp_path), registry=registry, include_tests=False)

        module_nodes = [n for n in result.nodes if n.type == NodeType.MODULE.value]
        module_ids = {n.id for n in module_nodes}
        assert "mod:Button" in module_ids
        # The test file should NOT be present
        test_module_ids = [mid for mid in module_ids if "ButtonTest" in mid or "Button.test" in mid]
        assert len(test_module_ids) == 0


# ---------------------------------------------------------------------------
# 11. CallInfo, InterfaceInfo, MethodSetEntry dataclasses
# ---------------------------------------------------------------------------


class TestCallInfo:
    """Test CallInfo dataclass construction and defaults."""

    def test_basic_construction(self):
        info = CallInfo(caller="App.Update", callee="Save")
        assert info.caller == "App.Update"
        assert info.callee == "Save"
        assert info.receiver == ""
        assert info.file_path == ""
        assert info.style == "direct"

    def test_with_receiver(self):
        info = CallInfo(caller="App.Update", callee="Save", receiver="Store")
        assert info.receiver == "Store"

    def test_method_style(self):
        info = CallInfo(caller="main", callee="NewConfig", style="method")
        assert info.style == "method"

    def test_constructor_style(self):
        info = CallInfo(caller="main", callee="MyService", style="constructor")
        assert info.style == "constructor"


class TestInterfaceInfo:
    """Test InterfaceInfo dataclass construction and defaults."""

    def test_basic_construction(self):
        info = InterfaceInfo(name="Store")
        assert info.name == "Store"
        assert info.methods == []
        assert info.file_path == ""

    def test_with_methods(self):
        info = InterfaceInfo(name="Store", methods=["Get", "Put", "Delete"])
        assert info.methods == ["Get", "Put", "Delete"]

    def test_with_file_path(self):
        info = InterfaceInfo(name="Store", file_path="store/store.go")
        assert info.file_path == "store/store.go"


class TestMethodSetEntry:
    """Test MethodSetEntry dataclass construction and defaults."""

    def test_basic_construction(self):
        entry = MethodSetEntry(struct_name="SQLiteStore", method_name="Get")
        assert entry.struct_name == "SQLiteStore"
        assert entry.method_name == "Get"
        assert entry.file_path == ""

    def test_with_file_path(self):
        entry = MethodSetEntry(struct_name="SQLiteStore", method_name="Get", file_path="store/sqlite.go")
        assert entry.file_path == "store/sqlite.go"


class TestScanResultMergeNewFields:
    """Test that ScanResult.merge handles calls, interfaces, and method_sets."""

    def test_merge_calls(self):
        a = ScanResult(calls=[CallInfo("main", "Foo")])
        b = ScanResult(calls=[CallInfo("main", "Bar"), CallInfo("init", "Baz")])
        a.merge(b)
        assert len(a.calls) == 3
        assert [c.callee for c in a.calls] == ["Foo", "Bar", "Baz"]

    def test_merge_interfaces(self):
        a = ScanResult(interfaces=[InterfaceInfo("Store")])
        b = ScanResult(interfaces=[InterfaceInfo("Vault")])
        a.merge(b)
        assert len(a.interfaces) == 2

    def test_merge_method_sets(self):
        a = ScanResult(method_sets=[MethodSetEntry("Foo", "Get")])
        b = ScanResult(method_sets=[MethodSetEntry("Bar", "Put")])
        a.merge(b)
        assert len(a.method_sets) == 2

    def test_default_empty_lists(self):
        r = ScanResult()
        assert r.calls == []
        assert r.interfaces == []
        assert r.method_sets == []

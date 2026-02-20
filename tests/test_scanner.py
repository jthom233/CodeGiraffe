"""Tests for the codebase scanner (codegiraffe.scanner)."""

import pytest
from pathlib import Path

from codegiraffe.scanner import (
    scan_project,
    PythonRecognizer,
    ScanResult,
    _file_to_module_path,
    _is_test_file,
)
from codegiraffe.schema import NodeType, EdgeType


class TestScanFindsEndpoints:
    """test_scan_finds_endpoints -- verify Flask routes are discovered."""

    def test_scan_finds_endpoints(self, sample_project):
        result = scan_project(str(sample_project))

        endpoint_nodes = [n for n in result.nodes if n.type == NodeType.ENDPOINT]
        endpoint_ids = {n.id for n in endpoint_nodes}

        assert "endpoint:/api/users" in endpoint_ids
        assert "endpoint:/api/users/<int:id>" in endpoint_ids
        assert len(endpoint_ids) >= 2

    def test_endpoint_has_file_path(self, sample_project):
        result = scan_project(str(sample_project))

        endpoint_nodes = [n for n in result.nodes if n.type == NodeType.ENDPOINT]
        for node in endpoint_nodes:
            assert node.file_path is not None
            assert node.file_path != ""


class TestScanFindsTables:
    """test_scan_finds_tables -- verify SQLAlchemy models are discovered."""

    def test_scan_finds_tables(self, sample_project):
        result = scan_project(str(sample_project))

        table_nodes = [n for n in result.nodes if n.type == NodeType.DATABASE_TABLE]
        table_ids = {n.id for n in table_nodes}

        assert "table:users" in table_ids

    def test_table_has_class_name_metadata(self, sample_project):
        result = scan_project(str(sample_project))

        table_nodes = [n for n in result.nodes if n.type == NodeType.DATABASE_TABLE]
        users_table = [n for n in table_nodes if n.id == "table:users"]
        assert len(users_table) == 1
        assert users_table[0].metadata.get("class_name") == "User"


class TestScanFindsWorkers:
    """test_scan_finds_workers -- verify Celery tasks are discovered."""

    def test_scan_finds_workers(self, sample_project):
        result = scan_project(str(sample_project))

        worker_nodes = [n for n in result.nodes if n.type == NodeType.WORKER]
        worker_ids = {n.id for n in worker_nodes}

        assert "worker:send_email" in worker_ids

    def test_worker_has_function_metadata(self, sample_project):
        result = scan_project(str(sample_project))

        worker_nodes = [n for n in result.nodes if n.type == NodeType.WORKER]
        send_email = [n for n in worker_nodes if n.id == "worker:send_email"]
        assert len(send_email) == 1
        assert send_email[0].metadata.get("function") == "send_email"


class TestScanFindsEnvVars:
    """test_scan_finds_env_vars -- verify os.getenv calls are discovered."""

    def test_scan_finds_env_vars(self, sample_project):
        result = scan_project(str(sample_project))

        env_nodes = [n for n in result.nodes if n.type == NodeType.ENV_VAR]
        env_ids = {n.id for n in env_nodes}

        assert "env:DATABASE_URL" in env_ids


class TestScanFindsExternalApis:
    """test_scan_finds_external_apis -- verify requests calls are discovered."""

    def test_scan_finds_external_apis(self, sample_project):
        result = scan_project(str(sample_project))

        api_nodes = [n for n in result.nodes if n.type == NodeType.EXTERNAL_API]
        api_ids = {n.id for n in api_nodes}

        assert "api:https://api.sendgrid.com/v3/mail/send" in api_ids

    def test_external_api_has_url_metadata(self, sample_project):
        result = scan_project(str(sample_project))

        api_nodes = [n for n in result.nodes if n.type == NodeType.EXTERNAL_API]
        sendgrid = [n for n in api_nodes if "sendgrid" in n.id]
        assert len(sendgrid) == 1
        assert "url" in sendgrid[0].metadata


class TestScanSkipsIgnoredDirs:
    """test_scan_skips_ignored_dirs -- create a .git dir with .py files,
    verify they're skipped."""

    def test_scan_skips_git_dir(self, sample_project):
        # Create a .git directory with a Python file
        git_dir = sample_project / ".git"
        git_dir.mkdir()
        (git_dir / "hooks.py").write_text('''
from flask import Flask
app = Flask(__name__)

@app.route("/api/secret", methods=["GET"])
def secret():
    pass
''')

        result = scan_project(str(sample_project))
        endpoint_ids = {n.id for n in result.nodes if n.type == NodeType.ENDPOINT}

        assert "endpoint:/api/secret" not in endpoint_ids

    def test_scan_skips_pycache(self, sample_project):
        pycache_dir = sample_project / "__pycache__"
        pycache_dir.mkdir()
        (pycache_dir / "cached.py").write_text('''
@shared_task
def cached_task():
    pass
''')

        result = scan_project(str(sample_project))
        worker_ids = {n.id for n in result.nodes if n.type == NodeType.WORKER}

        assert "worker:cached_task" not in worker_ids

    def test_scan_skips_venv(self, sample_project):
        venv_dir = sample_project / ".venv"
        venv_dir.mkdir()
        (venv_dir / "vendored.py").write_text('''
class VendoredService:
    pass
''')

        result = scan_project(str(sample_project))
        service_ids = {n.id for n in result.nodes if n.type == NodeType.SERVICE}

        assert "service:VendoredService" not in service_ids

    def test_scan_skips_obj_dir(self, tmp_path):
        """MSBuild obj/ output directory must be excluded from scanning."""
        obj_dir = tmp_path / "obj" / "Debug"
        obj_dir.mkdir(parents=True)
        (obj_dir / "generated.py").write_text('''
class GeneratedService:
    pass
''')

        result = scan_project(str(tmp_path))
        service_ids = {n.id for n in result.nodes if n.type == NodeType.SERVICE}

        assert "service:GeneratedService" not in service_ids

    def test_scan_skips_bin_dir(self, tmp_path):
        """MSBuild bin/ output directory must be excluded from scanning."""
        bin_dir = tmp_path / "bin" / "Release"
        bin_dir.mkdir(parents=True)
        (bin_dir / "compiled.py").write_text('''
class CompiledService:
    pass
''')

        result = scan_project(str(tmp_path))
        service_ids = {n.id for n in result.nodes if n.type == NodeType.SERVICE}

        assert "service:CompiledService" not in service_ids


class TestScanEmptyProject:
    """test_scan_empty_project -- empty dir returns empty ScanResult."""

    def test_scan_empty_project(self, tmp_path):
        result = scan_project(str(tmp_path))

        assert isinstance(result, ScanResult)
        assert len(result.nodes) == 0
        assert len(result.edges) == 0

    def test_scan_project_with_no_python_files(self, tmp_path):
        (tmp_path / "readme.txt").write_text("hello")
        (tmp_path / "data.csv").write_text("a,b,c")

        result = scan_project(str(tmp_path))

        assert isinstance(result, ScanResult)
        assert len(result.nodes) == 0
        assert len(result.edges) == 0


# ---------------------------------------------------------------------------
# _file_to_module_path tests
# ---------------------------------------------------------------------------


class TestFileToModulePath:
    """Tests for _file_to_module_path helper."""

    def test_src_layout(self):
        result = _file_to_module_path(Path("/project/src/pkg/mod.py"), "/project")
        assert result == "pkg.mod"

    def test_flat_layout(self):
        result = _file_to_module_path(Path("/project/pkg/mod.py"), "/project")
        assert result == "pkg.mod"

    def test_init_file(self):
        result = _file_to_module_path(
            Path("/project/src/pkg/__init__.py"), "/project"
        )
        assert result == "pkg"

    def test_nested_packages(self):
        result = _file_to_module_path(
            Path("/project/src/pkg/sub/deep.py"), "/project"
        )
        assert result == "pkg.sub.deep"

    def test_top_level_module(self):
        result = _file_to_module_path(Path("/project/src/app.py"), "/project")
        assert result == "app"

    def test_flat_nested(self):
        result = _file_to_module_path(
            Path("/project/pkg/sub/mod.py"), "/project"
        )
        assert result == "pkg.sub.mod"


# ---------------------------------------------------------------------------
# _is_test_file tests
# ---------------------------------------------------------------------------


class TestIsTestFile:
    """Tests for _is_test_file helper."""

    def test_test_prefix(self):
        assert _is_test_file(Path("test_foo.py")) is True

    def test_test_suffix(self):
        assert _is_test_file(Path("foo_test.py")) is True

    def test_conftest(self):
        assert _is_test_file(Path("conftest.py")) is True

    def test_regular_file(self):
        assert _is_test_file(Path("foo.py")) is False

    def test_testing_file(self):
        assert _is_test_file(Path("testing.py")) is False

    def test_nested_path_test_prefix(self):
        assert _is_test_file(Path("tests/test_bar.py")) is True

    def test_nested_path_regular(self):
        assert _is_test_file(Path("src/utils.py")) is False


# ---------------------------------------------------------------------------
# Module node tests (T046-T049)
# ---------------------------------------------------------------------------


class TestModuleNodes:
    """Tests for module node creation and contains edges during scanning."""

    def test_module_node_creation(self, tmp_path):
        """T046: Scanning a .py file creates a module node with id=mod:<dotted.path>."""
        pkg_dir = tmp_path / "src" / "pkg"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "__init__.py").write_text("")
        (pkg_dir / "mod.py").write_text("class Foo:\n    pass\n")

        result = scan_project(str(tmp_path))
        module_ids = {n.id for n in result.nodes if n.type == NodeType.MODULE}

        assert "mod:pkg.mod" in module_ids

    def test_init_creates_package_module(self, tmp_path):
        """T047: __init__.py creates a package-level module node."""
        pkg_dir = tmp_path / "src" / "pkg"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "__init__.py").write_text("")
        (pkg_dir / "mod.py").write_text("class Foo:\n    pass\n")

        result = scan_project(str(tmp_path))
        module_ids = {n.id for n in result.nodes if n.type == NodeType.MODULE}

        assert "mod:pkg" in module_ids

    def test_contains_edges(self, tmp_path):
        """T048: Contains edge exists from module to entities defined in that file."""
        pkg_dir = tmp_path / "src" / "pkg"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "__init__.py").write_text("")
        (pkg_dir / "mod.py").write_text("class Foo:\n    pass\n")

        result = scan_project(str(tmp_path))

        contains_edges = [
            e for e in result.edges if e.type == EdgeType.CONTAINS
        ]
        contains_pairs = {(e.source, e.target) for e in contains_edges}

        assert ("mod:pkg.mod", "service:Foo") in contains_pairs

    def test_module_metadata(self, tmp_path):
        """T049: Module node has file_path and correct package metadata."""
        pkg_dir = tmp_path / "src" / "pkg"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "__init__.py").write_text("")
        (pkg_dir / "mod.py").write_text("class Foo:\n    pass\n")

        result = scan_project(str(tmp_path))
        mod_nodes = [n for n in result.nodes if n.id == "mod:pkg.mod"]

        assert len(mod_nodes) == 1
        mod_node = mod_nodes[0]
        assert mod_node.file_path is not None
        assert "mod.py" in mod_node.file_path
        assert mod_node.metadata.get("package") == "pkg"


# ---------------------------------------------------------------------------
# Test file exclusion tests (T010-T013)
# ---------------------------------------------------------------------------


class TestTestFileExclusion:
    """Tests for test file exclusion during scanning."""

    def test_scanner_excludes_tests_dir_by_default(self, tmp_path):
        """T010: Scanner excludes files under tests/ directory by default."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "app.py").write_text(
            "class AppService:\n    pass\n"
        )

        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_app.py").write_text(
            "class TestAppService:\n    pass\n"
        )

        result = scan_project(str(tmp_path))
        node_ids = {n.id for n in result.nodes}

        assert "service:AppService" in node_ids
        assert "service:TestAppService" not in node_ids

    def test_scanner_excludes_test_prefix_files(self, tmp_path):
        """T011: Scanner excludes test_*.py and *_test.py files even outside test directories."""
        (tmp_path / "service.py").write_text(
            "class RealService:\n    pass\n"
        )

        (tmp_path / "test_service.py").write_text(
            "class TestRealService:\n    pass\n"
        )
        (tmp_path / "service_test.py").write_text(
            "class ServiceTestHelper:\n    pass\n"
        )

        result = scan_project(str(tmp_path))
        node_ids = {n.id for n in result.nodes}

        assert "service:RealService" in node_ids
        assert "service:TestRealService" not in node_ids
        assert "service:ServiceTestHelper" not in node_ids

    def test_scanner_excludes_conftest_files(self, tmp_path):
        """T012: Scanner excludes conftest.py files."""
        (tmp_path / "app.py").write_text(
            "class AppService:\n    pass\n"
        )
        (tmp_path / "conftest.py").write_text(
            "class FixtureHelper:\n    pass\n"
        )

        result = scan_project(str(tmp_path))
        node_ids = {n.id for n in result.nodes}

        assert "service:AppService" in node_ids
        assert "service:FixtureHelper" not in node_ids

    def test_include_tests_tags_nodes_with_source_test(self, tmp_path):
        """T013: include_tests=True scans test files but tags nodes with source: test."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "app.py").write_text(
            "class AppService:\n    pass\n"
        )

        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_app.py").write_text(
            "class TestAppService:\n    pass\n"
        )

        result = scan_project(str(tmp_path), include_tests=True)
        node_ids = {n.id for n in result.nodes}

        assert "service:AppService" in node_ids
        assert "service:TestAppService" in node_ids

        test_node = [n for n in result.nodes if n.id == "service:TestAppService"][0]
        assert test_node.metadata.get("source") == "test"

        app_node = [n for n in result.nodes if n.id == "service:AppService"][0]
        assert app_node.metadata.get("source") != "test"


# ---------------------------------------------------------------------------
# String filtering tests (T014-T019)
# ---------------------------------------------------------------------------


class TestStringFiltering:
    """Tests for _strip_strings_and_comments() and false-positive prevention."""

    def test_strip_triple_quoted_strings(self):
        """T014: _strip_strings_and_comments removes triple-quoted strings."""
        from codegiraffe.scanner import _strip_strings_and_comments

        text = "'''fake = \"test\"'''\nreal = True"
        cleaned = _strip_strings_and_comments(text)
        assert "fake" not in cleaned
        assert "real" in cleaned

    def test_strip_single_line_comments(self):
        """T015: _strip_strings_and_comments removes single-line comments."""
        from codegiraffe.scanner import _strip_strings_and_comments

        text = '# os.getenv("FAKE")\nos.getenv("REAL")'
        cleaned = _strip_strings_and_comments(text)
        assert "FAKE" not in cleaned
        assert "os.getenv" in cleaned

    def test_strip_quoted_strings(self):
        """T016: _strip_strings_and_comments removes quoted strings."""
        from codegiraffe.scanner import _strip_strings_and_comments

        text = """x = "os.getenv('FAKE')"\nos.getenv("REAL")"""
        cleaned = _strip_strings_and_comments(text)
        assert "FAKE" not in cleaned

    def test_no_false_route_in_docstring(self):
        """T017: PythonRecognizer does NOT detect @app.route inside a docstring."""
        code = '''
def handler():
    """
    Example usage:
    @app.route("/fake")
    def fake_handler():
        pass
    """
    pass

@app.route("/real")
def real_handler():
    pass
'''
        recognizer = PythonRecognizer()
        result = recognizer.recognize(Path("example.py"), code)
        node_ids = {n.id for n in result.nodes}

        assert "endpoint:/real" in node_ids
        assert "endpoint:/fake" not in node_ids

    def test_no_false_class_in_string(self):
        """T018: PythonRecognizer does NOT detect class inside a triple-quoted string."""
        code = '''
description = """
class FakeService:
    pass
"""

class RealService:
    pass
'''
        recognizer = PythonRecognizer()
        result = recognizer.recognize(Path("example.py"), code)
        node_ids = {n.id for n in result.nodes}

        assert "service:RealService" in node_ids
        assert "service:FakeService" not in node_ids

    def test_no_false_env_var_in_comment(self):
        """T019: PythonRecognizer does NOT detect os.getenv inside a comment."""
        code = '''
# old code: os.getenv("FAKE_KEY")
real_value = os.getenv("REAL_KEY")
'''
        recognizer = PythonRecognizer()
        result = recognizer.recognize(Path("example.py"), code)
        node_ids = {n.id for n in result.nodes}

        assert "env:REAL_KEY" in node_ids
        assert "env:FAKE_KEY" not in node_ids


# ---------------------------------------------------------------------------
# Import detection tests (T024-T029)
# ---------------------------------------------------------------------------


class TestImportDetection:
    """Tests for import-based dependency graph edges."""

    def test_from_import_creates_imports_edge(self, tmp_path):
        """T024: 'from pkg.graph import ArchGraph' creates an imports edge
        from source module to mod:pkg.graph with symbols metadata."""
        src = tmp_path / "src"
        pkg = src / "pkg"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("")
        (pkg / "graph.py").write_text("class ArchGraph:\n    pass\n")
        (pkg / "server.py").write_text("from pkg.graph import ArchGraph\n")

        result = scan_project(str(tmp_path))

        imports_edges = [
            e for e in result.edges if e.type == EdgeType.IMPORTS
        ]
        assert len(imports_edges) >= 1

        # Find the edge from server to graph
        edge = next(
            (e for e in imports_edges
             if e.source == "mod:pkg.server" and e.target == "mod:pkg.graph"),
            None,
        )
        assert edge is not None, (
            f"Expected imports edge from mod:pkg.server to mod:pkg.graph, "
            f"got: {[(e.source, e.target) for e in imports_edges]}"
        )
        assert "ArchGraph" in edge.metadata.get("symbols", [])

    def test_stdlib_import_excluded(self, tmp_path):
        """T025: 'import os' and 'import sys' do NOT create import edges."""
        src = tmp_path / "src"
        pkg = src / "pkg"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("")
        (pkg / "utils.py").write_text("import os\nimport sys\n")

        result = scan_project(str(tmp_path))

        imports_edges = [
            e for e in result.edges if e.type == EdgeType.IMPORTS
        ]
        assert len(imports_edges) == 0

    def test_third_party_import_excluded(self, tmp_path):
        """T026: 'import requests' does NOT create an import edge."""
        src = tmp_path / "src"
        pkg = src / "pkg"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("")
        (pkg / "client.py").write_text("import requests\n")

        result = scan_project(str(tmp_path))

        imports_edges = [
            e for e in result.edges if e.type == EdgeType.IMPORTS
        ]
        assert len(imports_edges) == 0

    def test_relative_import_resolves(self, tmp_path):
        """T027: 'from . import graph' resolves relative import correctly."""
        src = tmp_path / "src"
        pkg = src / "pkg"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("")
        (pkg / "graph.py").write_text("class Foo:\n    pass\n")
        (pkg / "server.py").write_text("from . import graph\n")

        result = scan_project(str(tmp_path))

        imports_edges = [
            e for e in result.edges if e.type == EdgeType.IMPORTS
        ]
        edge = next(
            (e for e in imports_edges
             if e.source == "mod:pkg.server" and e.target == "mod:pkg.graph"),
            None,
        )
        assert edge is not None, (
            f"Expected imports edge from mod:pkg.server to mod:pkg.graph, "
            f"got: {[(e.source, e.target) for e in imports_edges]}"
        )

    def test_multiple_imports_same_module_merged(self, tmp_path):
        """T028: Multiple imports from same module produce ONE edge with
        combined symbols list."""
        src = tmp_path / "src"
        pkg = src / "pkg"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("")
        (pkg / "graph.py").write_text(
            "class ArchGraph:\n    pass\n\nclass GraphData:\n    pass\n"
        )
        (pkg / "server.py").write_text(
            "from pkg.graph import ArchGraph\nfrom pkg.graph import GraphData\n"
        )

        result = scan_project(str(tmp_path))

        imports_edges = [
            e for e in result.edges
            if e.type == EdgeType.IMPORTS
            and e.source == "mod:pkg.server"
            and e.target == "mod:pkg.graph"
        ]
        assert len(imports_edges) == 1, (
            f"Expected exactly 1 imports edge, got {len(imports_edges)}"
        )
        symbols = imports_edges[0].metadata.get("symbols", [])
        assert "ArchGraph" in symbols
        assert "GraphData" in symbols

    def test_self_import_excluded(self, tmp_path):
        """T029: A module importing itself should not create an edge."""
        src = tmp_path / "src"
        pkg = src / "pkg"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("")
        (pkg / "graph.py").write_text(
            "from pkg.graph import something\nclass ArchGraph:\n    pass\n"
        )

        result = scan_project(str(tmp_path))

        imports_edges = [
            e for e in result.edges
            if e.type == EdgeType.IMPORTS
            and e.source == "mod:pkg.graph"
            and e.target == "mod:pkg.graph"
        ]
        assert len(imports_edges) == 0, (
            "Self-import edge should not be created"
        )


# ---------------------------------------------------------------------------
# Inheritance detection tests (T037-T040)
# ---------------------------------------------------------------------------


class TestInheritanceDetection:
    """Tests for inheritance and protocol relationship detection."""

    def test_single_inheritance_creates_implements_edge(self, tmp_path):
        """T037: class SQLiteStorage(StorageBackend): creates implements edge."""
        pkg_dir = tmp_path / "src" / "pkg"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "__init__.py").write_text("")
        (pkg_dir / "base.py").write_text("class StorageBackend:\n    pass\n")
        (pkg_dir / "sqlite.py").write_text(
            "class SQLiteStorage(StorageBackend):\n    pass\n"
        )

        result = scan_project(str(tmp_path))

        implements_edges = [
            e for e in result.edges if e.type == EdgeType.IMPLEMENTS
        ]
        edge_pairs = {(e.source, e.target) for e in implements_edges}

        assert ("service:SQLiteStorage", "service:StorageBackend") in edge_pairs

    def test_multiple_inheritance_creates_two_implements_edges(self, tmp_path):
        """T038: class MyClass(ParentA, ParentB): creates two implements edges."""
        pkg_dir = tmp_path / "src" / "pkg"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "__init__.py").write_text("")
        (pkg_dir / "mod.py").write_text(
            "class ParentA:\n    pass\n\n"
            "class ParentB:\n    pass\n\n"
            "class MyClass(ParentA, ParentB):\n    pass\n"
        )

        result = scan_project(str(tmp_path))

        implements_edges = [
            e for e in result.edges if e.type == EdgeType.IMPLEMENTS
        ]
        edge_pairs = {(e.source, e.target) for e in implements_edges}

        assert ("service:MyClass", "service:ParentA") in edge_pairs
        assert ("service:MyClass", "service:ParentB") in edge_pairs

    def test_cross_file_inheritance_resolution(self, tmp_path):
        """T039: Base class in different file creates cross-file implements edge."""
        pkg_dir = tmp_path / "src" / "pkg"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "__init__.py").write_text("")
        (pkg_dir / "base.py").write_text("class StorageBackend:\n    pass\n")
        (pkg_dir / "json_storage.py").write_text(
            "class JSONStorage(StorageBackend):\n    pass\n"
        )

        result = scan_project(str(tmp_path))

        implements_edges = [
            e for e in result.edges if e.type == EdgeType.IMPLEMENTS
        ]
        edge_pairs = {(e.source, e.target) for e in implements_edges}

        assert ("service:JSONStorage", "service:StorageBackend") in edge_pairs

        # Verify cross_file metadata
        cross_file_edge = [
            e for e in implements_edges
            if e.source == "service:JSONStorage"
            and e.target == "service:StorageBackend"
        ][0]
        assert cross_file_edge.metadata.get("cross_file") is True

    def test_external_base_class_no_implements_edge(self, tmp_path):
        """T040: External base class (e.g., BaseModel) does NOT create implements edge."""
        pkg_dir = tmp_path / "src" / "pkg"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "__init__.py").write_text("")
        (pkg_dir / "models.py").write_text(
            "class User(BaseModel):\n    pass\n"
        )

        result = scan_project(str(tmp_path))

        implements_edges = [
            e for e in result.edges if e.type == EdgeType.IMPLEMENTS
        ]

        # No implements edge should exist because BaseModel is not defined
        # in any project file
        assert len([
            e for e in implements_edges
            if e.source == "service:User"
        ]) == 0

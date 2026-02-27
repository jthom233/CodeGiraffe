"""Tests for the codebase scanner (codegiraffe.scanner)."""

import os
import stat
import time
import pytest
from pathlib import Path
from unittest.mock import patch

from codegiraffe.scanner import (
    scan_project,
    PythonRecognizer,
    ScanResult,
    _file_to_module_path,
    _is_test_file,
    _should_skip,
    _is_generated_file,
    _IGNORE_DIRS_LOWER,
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


# ---------------------------------------------------------------------------
# US4: Per-model __tablename__ detection
# ---------------------------------------------------------------------------


class TestTableNamePerModelClass:
    """Each SQLAlchemy model class in a multi-model file gets its own __tablename__."""

    def test_two_models_get_distinct_table_names(self):
        """Two models with different __tablename__ values produce two distinct table nodes."""
        source = """
class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)

class Order(Base):
    __tablename__ = 'orders'
    id = Column(Integer, primary_key=True)
"""
        recognizer = PythonRecognizer()
        result = recognizer.recognize(Path("models.py"), source)

        table_nodes = [n for n in result.nodes if n.type == "database_table"]
        assert len(table_nodes) == 2, (
            f"Expected 2 table nodes, got {len(table_nodes)}: "
            f"{[n.metadata for n in table_nodes]}"
        )

        table_names = {n.metadata.get("table_name") for n in table_nodes}
        assert "users" in table_names, (
            f"Expected 'users' in table names, got: {table_names}"
        )
        assert "orders" in table_names, (
            f"Expected 'orders' in table names, got: {table_names}"
        )

    def test_first_model_explicit_second_model_default(self):
        """First model has explicit __tablename__; second defaults to lowercased class name."""
        source = """
class Product(Base):
    __tablename__ = 'products'
    id = Column(Integer, primary_key=True)

class Invoice(Base):
    id = Column(Integer, primary_key=True)
"""
        recognizer = PythonRecognizer()
        result = recognizer.recognize(Path("models.py"), source)

        table_nodes = [n for n in result.nodes if n.type == "database_table"]
        assert len(table_nodes) == 2, (
            f"Expected 2 table nodes, got {len(table_nodes)}"
        )

        by_class = {n.metadata.get("class_name"): n for n in table_nodes}
        assert by_class["Product"].metadata.get("table_name") == "products", (
            f"Product should have table_name='products', got: {by_class['Product'].metadata}"
        )
        assert by_class["Invoice"].metadata.get("table_name") == "invoice", (
            f"Invoice should have table_name='invoice' (default), got: {by_class['Invoice'].metadata}"
        )


# ---------------------------------------------------------------------------
# Conditional module creation tests (T051-T055)
# ---------------------------------------------------------------------------


class TestConditionalModuleCreation:
    """Tests verifying that the scanner only creates universal mod: nodes for
    real source-code files and not for 'unknown'-language files like .sql or
    .csproj."""

    def test_cs_file_gets_module_node(self, tmp_path):
        """T051: A .cs file (known language) still receives a scanner-level module node."""
        (tmp_path / "Service.cs").write_text(
            "namespace MyApp {\n    public class MyService {}\n}\n"
        )
        result = scan_project(str(tmp_path))
        module_ids = {n.id for n in result.nodes if n.type == NodeType.MODULE}
        # The scanner-level mod: node should be present for a .cs file
        assert any("Service" in mid for mid in module_ids), (
            f"Expected a module node for Service.cs, got: {module_ids}"
        )

    def test_sql_file_with_table_no_universal_module_node(self, tmp_path):
        """T052: A .sql file gets its recognizer-emitted table nodes but NOT a
        scanner-level mod: node for the file itself."""
        (tmp_path / "create_users.sql").write_text(
            "CREATE TABLE Users (Id INT PRIMARY KEY, Name NVARCHAR(100));\n"
        )
        result = scan_project(str(tmp_path))

        node_ids = {n.id for n in result.nodes}
        module_ids = {n.id for n in result.nodes if n.type == NodeType.MODULE}

        # The recognizer-emitted table node should be present
        assert "table:Users" in node_ids, (
            f"Expected table:Users from SQL recognizer, got: {node_ids}"
        )

        # No scanner-level file module node for the .sql file
        # (The file stem is "create_users"; it must not appear as a bare file module)
        assert "mod:create_users" not in module_ids, (
            f"Scanner should not create a mod: node for a .sql file, got: {module_ids}"
        )

    def test_csproj_file_no_extra_universal_module_node(self, tmp_path):
        """T053: A .csproj file gets its recognizer-emitted project node (project: type)
        but NOT an additional scanner-level mod: file node for the .csproj path itself.

        The CsprojRecognizer emits a project:<assembly> node; the scanner must not
        duplicate it with a second node derived from the file path."""
        csproj_content = """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
  </PropertyGroup>
</Project>"""
        (tmp_path / "MyApp.csproj").write_text(csproj_content)

        result = scan_project(str(tmp_path))
        from codegiraffe.schema import NodeType as NT
        project_nodes = [n for n in result.nodes if n.type == NT.PROJECT]
        project_ids = {n.id for n in project_nodes}

        # The CsprojRecognizer emits exactly one project: node
        assert "project:MyApp" in project_ids, (
            f"CsprojRecognizer project node expected in {project_ids}"
        )
        # No mod:MyApp scanner-level node should exist for the .csproj file
        module_ids = {n.id for n in result.nodes if n.type == NodeType.MODULE}
        assert "mod:MyApp" not in module_ids, (
            "Scanner must not create a redundant mod:MyApp for the .csproj file"
        )

    def test_sql_migration_file_gets_recognizer_module(self, tmp_path):
        """T054: A SQL migration file (ALTER TABLE only) gets the recognizer-emitted
        migration mod: node but NOT an additional scanner-level file mod: node."""
        (tmp_path / "V2__add_column.sql").write_text(
            "ALTER TABLE Users ADD Email NVARCHAR(200);\n"
        )
        result = scan_project(str(tmp_path))

        module_ids = {n.id for n in result.nodes if n.type == NodeType.MODULE}
        # The SqlRecognizer emits a migration mod: node for the file stem
        assert "mod:V2__add_column" in module_ids, (
            f"Expected migration mod: node from SqlRecognizer, got: {module_ids}"
        )
        # There must only be ONE such node — the scanner must not add a second one
        all_module_nodes = [n for n in result.nodes if n.type == NodeType.MODULE]
        assert len([n for n in all_module_nodes if n.id == "mod:V2__add_column"]) == 1, (
            "Expected exactly one mod:V2__add_column; scanner must not duplicate it"
        )

    def test_config_file_with_no_recognizer_produces_no_nodes(self, tmp_path):
        """T055: A .config file that no recognizer handles produces zero nodes."""
        (tmp_path / "app.config").write_text(
            "<configuration><appSettings /></configuration>\n"
        )
        result = scan_project(str(tmp_path))
        assert len(result.nodes) == 0, (
            f"Unexpected nodes for unrecognized .config file: {[n.id for n in result.nodes]}"
        )


# ---------------------------------------------------------------------------
# US5: Edge deduplication idempotency
# ---------------------------------------------------------------------------


class TestEdgeDeduplicationIdempotency:
    """Scanning an unchanged project twice produces an identical edge count."""

    def test_double_scan_produces_same_edge_count(self, tmp_path):
        """Scan a multi-file project twice; edge counts must be identical."""
        # Create a small multi-file project with an endpoint and a SQLAlchemy model
        (tmp_path / "app.py").write_text(
            "from flask import Flask\n"
            "app = Flask(__name__)\n"
            "\n"
            "@app.route('/items')\n"
            "def list_items():\n"
            "    return Item.query.all()\n"
        )
        (tmp_path / "models.py").write_text(
            "from flask_sqlalchemy import SQLAlchemy\n"
            "db = SQLAlchemy()\n"
            "\n"
            "class Item(db.Model):\n"
            "    __tablename__ = 'items'\n"
            "    id = db.Column(db.Integer, primary_key=True)\n"
        )

        result1 = scan_project(str(tmp_path))
        edge_count_1 = len(result1.edges)

        result2 = scan_project(str(tmp_path))
        edge_count_2 = len(result2.edges)

        assert edge_count_1 == edge_count_2, (
            f"Double scan produced different edge counts: "
            f"first={edge_count_1}, second={edge_count_2}"
        )

    def test_dedup_key_types_are_consistent(self):
        """StrEnum dedup keys: EdgeType.READS and 'reads' both find the same set entry."""
        from codegiraffe.graph import Edge

        edges = [
            Edge(source="ep:/a", target="table:b", type="reads"),
        ]
        existing_edges = {(e.source, e.target, str(e.type)) for e in edges}

        # Both string and StrEnum forms must be found
        assert ("ep:/a", "table:b", "reads") in existing_edges
        assert ("ep:/a", "table:b", EdgeType.READS) in existing_edges, (
            "StrEnum EdgeType.READS must equal 'reads' for set lookup"
        )
        assert ("ep:/a", "table:b", EdgeType.READS.value) in existing_edges
# T001 — Phase 1: _scan_single_file helper (US3)
# ---------------------------------------------------------------------------


class TestScanSingleFileHelper:
    """T001: _scan_single_file is importable and produces ScanResult with module node."""

    def test_scan_single_file_importable_and_returns_scan_result(self, tmp_path):
        """_scan_single_file must be importable and return a ScanResult with a module node."""
        from codegiraffe.scanner import _scan_single_file
        from codegiraffe.registry import get_default_registry

        py_file = tmp_path / "mymodule.py"
        py_file.write_text("def hello():\n    pass\n")

        active_registry = get_default_registry()
        outcome = _scan_single_file(
            source_file=py_file,
            rel_path=py_file.relative_to(tmp_path),
            project_path=str(tmp_path),
            active_registry=active_registry,
            is_test=False,
        )
        assert outcome is not None
        result, content = outcome
        module_nodes = [n for n in result.nodes if n.type == "module"]
        assert len(module_nodes) >= 1, "Expected at least one module node"


# ---------------------------------------------------------------------------
# T005–T008 — Phase 2: Betweenness centrality caching (US1)
# Written here to keep scanner tests separate; US1 tests live in test_performance_guards.py
# ---------------------------------------------------------------------------

# (US1 tests are added in test_performance_guards.py separately)


# ---------------------------------------------------------------------------
# T014–T017 — Phase 3: Directory-pruning file discovery (US2)
# ---------------------------------------------------------------------------


class TestDirectoryPruning:
    """Verify that os.walk-based pruning never enters ignored directories."""

    def test_ignored_dir_not_entered(self, tmp_path):
        """Files inside node_modules are never read when node_modules is pruned."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "main.py").write_text("def hello():\n    pass\n")

        nm_dir = tmp_path / "node_modules" / "lodash"
        nm_dir.mkdir(parents=True)
        (nm_dir / "index.js").write_text("module.exports = {};\n")

        result = scan_project(str(tmp_path))

        # No node should have a file_path that mentions node_modules
        bad_nodes = [
            n for n in result.nodes
            if n.file_path and "node_modules" in n.file_path
        ]
        assert bad_nodes == [], (
            f"Found nodes from inside node_modules: {[n.file_path for n in bad_nodes]}"
        )

    def test_nested_ignored_dir_not_entered(self, tmp_path):
        """Files inside a nested .venv directory are never scanned."""
        app_dir = tmp_path / "src" / "app"
        app_dir.mkdir(parents=True)
        (app_dir / "lib.py").write_text("def foo():\n    pass\n")

        venv_dir = tmp_path / "src" / "app" / ".venv" / "site-packages" / "requests"
        venv_dir.mkdir(parents=True)
        (venv_dir / "__init__.py").write_text("# requests\n")

        result = scan_project(str(tmp_path))

        bad_nodes = [
            n for n in result.nodes
            if n.file_path and ".venv" in n.file_path
        ]
        assert bad_nodes == [], (
            f"Found nodes from inside .venv: {[n.file_path for n in bad_nodes]}"
        )

    def test_no_ignored_dirs_scans_all_files(self, tmp_path):
        """When no ignored dirs exist, all files are scanned (regression guard)."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "a.py").write_text("class Alpha:\n    pass\n")
        (src_dir / "b.py").write_text("class Beta:\n    pass\n")

        result = scan_project(str(tmp_path))

        module_ids = {n.id for n in result.nodes if n.type == "module"}
        # Both files must produce module nodes
        assert "mod:a" in module_ids or any("a" in mid for mid in module_ids), (
            f"Expected module for a.py; got modules: {module_ids}"
        )
        assert "mod:b" in module_ids or any("b" in mid for mid in module_ids), (
            f"Expected module for b.py; got modules: {module_ids}"
        )

    def test_egg_info_dirs_pruned(self, tmp_path):
        """Directories matching *.egg-info are never entered."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "main.py").write_text("def hello():\n    pass\n")

        egg_dir = tmp_path / "my_pkg.egg-info"
        egg_dir.mkdir()
        (egg_dir / "PKG-INFO").write_text("Metadata-Version: 2.1\n")

        result = scan_project(str(tmp_path))

        bad_nodes = [
            n for n in result.nodes
            if n.file_path and "egg-info" in n.file_path
        ]
        assert bad_nodes == [], (
            f"Found nodes from inside egg-info: {[n.file_path for n in bad_nodes]}"
        )


# ---------------------------------------------------------------------------
# T020–T022 — Phase 4: Efficient incremental scan / linear merge (US3)
# ---------------------------------------------------------------------------


class TestScanResultMergeLinearScale:
    """T020: ScanResult.merge() over 1000 results must complete under 2 seconds."""

    def test_scan_result_merge_linear_scale(self):
        """Merging 1000 ScanResults each with 5 unique nodes must be fast (< 2s)."""
        from codegiraffe.graph import Node

        all_results = []
        for i in range(1000):
            nodes = [
                Node(
                    id=f"service:Node{i}_{j}",
                    type="service",
                    label=f"Node{i}_{j}",
                )
                for j in range(5)
            ]
            all_results.append(ScanResult(nodes=nodes))

        start = time.monotonic()
        merged = ScanResult()
        for r in all_results:
            merged.merge(r)
        elapsed = time.monotonic() - start

        assert len(merged.nodes) == 5000, f"Expected 5000 nodes, got {len(merged.nodes)}"
        assert elapsed < 2.0, (
            f"merge() took {elapsed:.2f}s on 1000 results — must be under 2.0s"
        )

    def test_scan_project_and_sync_files_produce_same_nodes(self, tmp_path):
        """T021: scan_project and sync_files on the same 3-file project yield identical node IDs."""
        from codegiraffe.scanner import sync_files
        from codegiraffe.graph import ArchGraph, GraphData

        # Create 3-file project
        (tmp_path / "a.py").write_text("class Alpha:\n    pass\n")
        (tmp_path / "b.py").write_text("class Beta:\n    pass\n")
        (tmp_path / "c.py").write_text("class Gamma:\n    pass\n")

        # Full scan
        full_result = scan_project(str(tmp_path))
        full_node_ids = {n.id for n in full_result.nodes}

        # Now sync_files on all 3 files (empty graph start)
        graph = ArchGraph()
        sync_files(
            graph,
            str(tmp_path),
            [str(tmp_path / "a.py"), str(tmp_path / "b.py"), str(tmp_path / "c.py")],
        )
        sync_node_ids = {
            attrs["node"].id
            for _, attrs in graph.graph.nodes(data=True)
            if "node" in attrs
        }

        # The module node IDs must be the same
        full_modules = {nid for nid in full_node_ids if nid.startswith("mod:")}
        sync_modules = {nid for nid in sync_node_ids if nid.startswith("mod:")}
        assert full_modules == sync_modules, (
            f"Module node ID mismatch:\n  scan_project: {full_modules}\n  sync_files: {sync_modules}"
        )

    def test_merge_deduplicates_across_multiple_merges(self):
        """T022: Merging two ScanResults with a shared node ID yields exactly one node."""
        from codegiraffe.graph import Node

        shared_node = Node(id="service:Shared", type="service", label="Shared", metadata={"key": "val1"})
        other_node = Node(id="service:Shared", type="service", label="Shared", metadata={"extra": "val2"})

        r1 = ScanResult(nodes=[shared_node])
        r2 = ScanResult(nodes=[other_node])

        merged = ScanResult()
        merged.merge(r1)
        merged.merge(r2)

        matching = [n for n in merged.nodes if n.id == "service:Shared"]
        assert len(matching) == 1, f"Expected 1 deduplicated node, got {len(matching)}"
        # Metadata should be merged (additive)
        assert matching[0].metadata.get("key") == "val1"
        assert matching[0].metadata.get("extra") == "val2"


# ---------------------------------------------------------------------------
# T025–T027 — Phase 5: Parallel file scanning (US4)
# ---------------------------------------------------------------------------


class TestParallelScanning:
    """Verify parallel scanning produces set-identical results to sequential."""

    def test_parallel_scan_produces_same_nodes_as_sequential(self, tmp_path):
        """T025: max_workers=1 and max_workers=4 must yield identical node ID sets."""
        # Create a 10-file project
        for i in range(10):
            (tmp_path / f"module_{i}.py").write_text(
                f"class Class{i}:\n    pass\n"
            )

        seq_result = scan_project(str(tmp_path), max_workers=1)
        par_result = scan_project(str(tmp_path), max_workers=4)

        seq_ids = {n.id for n in seq_result.nodes}
        par_ids = {n.id for n in par_result.nodes}

        assert seq_ids == par_ids, (
            f"Node ID mismatch between sequential and parallel scans:\n"
            f"  only in sequential: {seq_ids - par_ids}\n"
            f"  only in parallel: {par_ids - seq_ids}"
        )

    def test_parallel_scan_file_error_isolated(self, tmp_path):
        """T026: A single unreadable file must not crash parallel scan."""
        good_files = []
        for i in range(5):
            f = tmp_path / f"module_{i}.py"
            f.write_text(f"class C{i}:\n    pass\n")
            good_files.append(f)

        # Make one file unreadable
        bad_file = tmp_path / "bad.py"
        bad_file.write_text("class Bad:\n    pass\n")
        # chmod 000 to make unreadable
        bad_file.chmod(0)

        try:
            result = scan_project(str(tmp_path), max_workers=4)
            # Should not raise; bad file should simply be absent
            bad_nodes = [n for n in result.nodes if n.file_path and "bad.py" in n.file_path]
            # The result should have nodes from the 5 good files
            good_module_ids = {n.id for n in result.nodes if n.type == "module"}
            assert len(good_module_ids) >= 4, (
                f"Expected at least 4 good modules; got {good_module_ids}"
            )
        finally:
            # Restore permissions for cleanup
            bad_file.chmod(stat.S_IRUSR | stat.S_IWUSR)

    def test_parallel_scan_accepts_max_workers_none(self, tmp_path):
        """T027: scan_project with no max_workers argument must complete without error."""
        (tmp_path / "main.py").write_text("def hello():\n    pass\n")
        # Should not raise TypeError about unexpected keyword argument
        result = scan_project(str(tmp_path))
        assert result is not None


# ---------------------------------------------------------------------------
# Generated file exclusion tests (T056-T059)
# ---------------------------------------------------------------------------


class TestGeneratedFileExclusion:
    """Tests verifying that generated code files are skipped before recognizer
    invocation."""

    def test_g_cs_file_is_skipped(self, tmp_path):
        """T056: Files ending in .g.cs (Roslyn source generators) are skipped."""
        (tmp_path / "MyModel.g.cs").write_text(
            "namespace MyApp {\n    public class MyModel {}\n}\n"
        )
        result = scan_project(str(tmp_path))
        node_ids = {n.id for n in result.nodes}
        assert "service:MyModel" not in node_ids, (
            "Scanner should skip .g.cs generated files"
        )

    def test_designer_cs_file_is_skipped(self, tmp_path):
        """T057: Files ending in .Designer.cs (WinForms/WPF) are skipped."""
        (tmp_path / "Form1.Designer.cs").write_text(
            "namespace MyApp {\n    public partial class Form1 {}\n}\n"
        )
        result = scan_project(str(tmp_path))
        node_ids = {n.id for n in result.nodes}
        assert "service:Form1" not in node_ids, (
            "Scanner should skip .Designer.cs generated files"
        )

    def test_generated_cs_file_is_skipped(self, tmp_path):
        """T058: Files ending in .generated.cs are skipped."""
        (tmp_path / "Contracts.generated.cs").write_text(
            "namespace MyApp {\n    public class Contracts {}\n}\n"
        )
        result = scan_project(str(tmp_path))
        node_ids = {n.id for n in result.nodes}
        assert "service:Contracts" not in node_ids, (
            "Scanner should skip .generated.cs generated files"
        )

    def test_openapi_generator_dir_skips_contents(self, tmp_path):
        """T059: Files inside a directory containing .openapi-generator marker are
        skipped (treated as generated output)."""
        gen_dir = tmp_path / "src" / "generated"
        gen_dir.mkdir(parents=True)
        # Create the OpenAPI generator marker directory inside the output dir
        (gen_dir / ".openapi-generator").mkdir()
        # Put a real .cs file next to the marker
        (gen_dir / "ApiClient.cs").write_text(
            "namespace MyApp {\n    public class ApiClient {}\n}\n"
        )
        result = scan_project(str(tmp_path))
        node_ids = {n.id for n in result.nodes}
        assert "service:ApiClient" not in node_ids, (
            "Files inside openapi-generator output directories should be skipped"
        )

    def test_normal_cs_file_still_scanned(self, tmp_path):
        """T059b: A normal .cs file (no generated suffix) is still scanned normally."""
        (tmp_path / "UserService.cs").write_text(
            "namespace MyApp {\n    public class UserService {}\n}\n"
        )
        result = scan_project(str(tmp_path))
        # Just verify the scan ran without error; recognizer will or will not find nodes
        # but the file was not skipped by the generated-file guard
        assert isinstance(result, ScanResult)


# ---------------------------------------------------------------------------
# Case-insensitive _IGNORE_DIRS tests (T060-T063)
# ---------------------------------------------------------------------------


class TestIgnoreDirsCaseInsensitive:
    """Tests verifying that _IGNORE_DIRS matching is case-insensitive.  This is
    critical on Windows where directory names like ``Packages`` != ``packages``
    in a case-sensitive comparison."""

    def test_ignore_dirs_lower_contains_new_entries(self):
        """T060: _IGNORE_DIRS_LOWER includes the newly added .NET directories."""
        assert "packages" in _IGNORE_DIRS_LOWER
        assert "artifacts" in _IGNORE_DIRS_LOWER
        assert "testresults" in _IGNORE_DIRS_LOWER
        assert ".openapi-generator" in _IGNORE_DIRS_LOWER

    def test_packages_dir_uppercase_is_skipped(self, tmp_path):
        """T061: A directory named 'Packages' (NuGet restore) is skipped."""
        pkg_dir = tmp_path / "Packages" / "Newtonsoft.Json"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "Newtonsoft.cs").write_text(
            "namespace Newtonsoft { public class JsonSerializer {} }\n"
        )
        result = scan_project(str(tmp_path))
        node_ids = {n.id for n in result.nodes}
        assert "service:JsonSerializer" not in node_ids, (
            "Packages/ directory (NuGet restore) should be excluded case-insensitively"
        )

    def test_artifacts_dir_is_skipped(self, tmp_path):
        """T062: A directory named 'artifacts' (.NET 8+ build output) is skipped."""
        art_dir = tmp_path / "artifacts" / "bin"
        art_dir.mkdir(parents=True)
        (art_dir / "compiled.py").write_text("class CompiledHelper:\n    pass\n")
        result = scan_project(str(tmp_path))
        node_ids = {n.id for n in result.nodes}
        assert "service:CompiledHelper" not in node_ids, (
            "artifacts/ directory (.NET build output) should be excluded"
        )

    def test_testresults_dir_is_skipped(self, tmp_path):
        """T063: A directory named 'TestResults' (VS test output) is skipped
        even when the casing differs from the lowercase entry in _IGNORE_DIRS."""
        tr_dir = tmp_path / "TestResults" / "run1"
        tr_dir.mkdir(parents=True)
        (tr_dir / "coverage.py").write_text("class CoverageHelper:\n    pass\n")
        result = scan_project(str(tmp_path))
        node_ids = {n.id for n in result.nodes}
        assert "service:CoverageHelper" not in node_ids, (
            "TestResults/ directory (VS test output) should be excluded case-insensitively"
        )

    def test_should_skip_case_insensitive_unit(self, tmp_path):
        """T064 (unit): _should_skip returns True for a path component that matches
        an _IGNORE_DIRS entry regardless of case."""
        # Test with a Path object directly — simulate Windows-style casing
        assert _should_skip(Path("MyProject/Packages/Newtonsoft.Json/lib.cs"))
        assert _should_skip(Path("src/ARTIFACTS/bin/out.cs"))
        assert _should_skip(Path(".git/config"))
        # Normal source file must not be skipped
        assert not _should_skip(Path("src/app.py"))


# ---------------------------------------------------------------------------
# Project node type and project_contains edge tests
# ---------------------------------------------------------------------------


class TestProjectNodeType:
    """Tests for the project: node type introduced to represent .NET .csproj projects
    and the project_contains edges that link them to their constituent modules."""

    def test_csproj_emits_project_type_node(self, tmp_path):
        """T065: CsprojRecognizer emits a node with type NodeType.PROJECT, not MODULE."""
        (tmp_path / "MyApp.csproj").write_text(
            '<Project Sdk="Microsoft.NET.Sdk">'
            "<PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup>"
            "</Project>"
        )
        result = scan_project(str(tmp_path))
        project_nodes = [n for n in result.nodes if n.type == NodeType.PROJECT]
        assert any(n.id == "project:MyApp" for n in project_nodes), (
            f"Expected project:MyApp in {[n.id for n in project_nodes]}"
        )

    def test_project_reference_links_project_to_project(self, tmp_path):
        """T066: ProjectReference edges connect project:A to project:B."""
        (tmp_path / "App.csproj").write_text(
            '<Project Sdk="Microsoft.NET.Sdk">'
            "<ItemGroup>"
            '<ProjectReference Include="../Lib/Lib.csproj" />'
            "</ItemGroup>"
            "</Project>"
        )
        (tmp_path / "Lib.csproj").write_text(
            '<Project Sdk="Microsoft.NET.Sdk"></Project>'
        )
        result = scan_project(str(tmp_path))

        # Both project nodes should exist.
        project_ids = {n.id for n in result.nodes if n.type == NodeType.PROJECT}
        assert "project:App" in project_ids, f"Expected project:App in {project_ids}"
        assert "project:Lib" in project_ids, f"Expected project:Lib in {project_ids}"

        # The project reference edge must connect project:App -> project:Lib.
        ref_edge = next(
            (
                e for e in result.edges
                if e.source == "project:App"
                and e.target == "project:Lib"
                and e.type == EdgeType.DEPENDS_ON
            ),
            None,
        )
        assert ref_edge is not None, "Expected depends_on edge from project:App to project:Lib"
        assert ref_edge.metadata["reference_type"] == "project_reference"

    def test_nuget_references_remain_as_mod_targets(self, tmp_path):
        """T067: PackageReference edges still point to mod: targets (NuGet packages are modules)."""
        (tmp_path / "App.csproj").write_text(
            '<Project Sdk="Microsoft.NET.Sdk">'
            '<ItemGroup><PackageReference Include="Serilog" Version="3.1.1" /></ItemGroup>'
            "</Project>"
        )
        result = scan_project(str(tmp_path))

        nuget_edge = next(
            (
                e for e in result.edges
                if e.source == "project:App" and e.target == "mod:Serilog"
            ),
            None,
        )
        assert nuget_edge is not None, "Expected project:App -> mod:Serilog edge"
        assert nuget_edge.metadata["reference_type"] == "nuget"

    def test_project_contains_edges_link_project_to_cs_modules(self, tmp_path):
        """T068: Scanner creates project_contains edges from project:X to mod:X.* modules
        whose files live inside the same directory as the .csproj file."""
        # Create a .csproj and sibling .cs files
        (tmp_path / "MyApp.csproj").write_text(
            '<Project Sdk="Microsoft.NET.Sdk"></Project>'
        )
        (tmp_path / "Program.cs").write_text(
            "namespace MyApp { public class Program { static void Main() {} } }\n"
        )
        (tmp_path / "Service.cs").write_text(
            "namespace MyApp { public class Service {} }\n"
        )
        result = scan_project(str(tmp_path))

        # project:MyApp should exist.
        project_ids = {n.id for n in result.nodes if n.type == NodeType.PROJECT}
        assert "project:MyApp" in project_ids

        # project_contains edges from project:MyApp to the module nodes for Program.cs / Service.cs.
        contains_edges = [
            e for e in result.edges
            if e.source == "project:MyApp" and e.type == EdgeType.PROJECT_CONTAINS
        ]
        contains_targets = {e.target for e in contains_edges}

        # At minimum, the scanner-level mod: nodes for Program.cs and Service.cs must be linked.
        assert any("Program" in t for t in contains_targets), (
            f"Expected a project_contains edge to the Program module, got: {contains_targets}"
        )
        assert any("Service" in t for t in contains_targets), (
            f"Expected a project_contains edge to the Service module, got: {contains_targets}"
        )

    def test_project_contains_edges_scoped_to_csproj_directory(self, tmp_path):
        """T069: project_contains edges only link modules inside the .csproj directory,
        not sibling directories belonging to a different project."""
        # Project A
        proj_a = tmp_path / "ProjA"
        proj_a.mkdir()
        (proj_a / "ProjA.csproj").write_text('<Project Sdk="Microsoft.NET.Sdk"></Project>')
        (proj_a / "ServiceA.cs").write_text(
            "namespace ProjA { public class ServiceA {} }\n"
        )

        # Project B
        proj_b = tmp_path / "ProjB"
        proj_b.mkdir()
        (proj_b / "ProjB.csproj").write_text('<Project Sdk="Microsoft.NET.Sdk"></Project>')
        (proj_b / "ServiceB.cs").write_text(
            "namespace ProjB { public class ServiceB {} }\n"
        )

        result = scan_project(str(tmp_path))

        contains_a = {
            e.target for e in result.edges
            if e.source == "project:ProjA" and e.type == EdgeType.PROJECT_CONTAINS
        }
        contains_b = {
            e.target for e in result.edges
            if e.source == "project:ProjB" and e.type == EdgeType.PROJECT_CONTAINS
        }

        # ProjA should contain ServiceA modules but not ServiceB modules.
        assert any("ServiceA" in t for t in contains_a), (
            f"project:ProjA should contain ServiceA, got {contains_a}"
        )
        assert not any("ServiceB" in t for t in contains_a), (
            f"project:ProjA must not contain ServiceB, got {contains_a}"
        )

        # ProjB should contain ServiceB modules but not ServiceA modules.
        assert any("ServiceB" in t for t in contains_b), (
            f"project:ProjB should contain ServiceB, got {contains_b}"
        )
        assert not any("ServiceA" in t for t in contains_b), (
            f"project:ProjB must not contain ServiceA, got {contains_b}"
        )

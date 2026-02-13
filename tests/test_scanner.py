"""Tests for the codebase scanner (codegiraffe.scanner)."""

import pytest
from pathlib import Path

from codegiraffe.scanner import scan_project, PythonRecognizer, ScanResult
from codegiraffe.types import NodeType, EdgeType


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

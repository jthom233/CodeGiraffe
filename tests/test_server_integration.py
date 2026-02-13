"""Server integration tests for the 8 new MCP tools in Code Giraffe.

Tests the versioning tools (history, diff, snapshot, restore),
federation tools (federate, cross_query, cross_edges), and the
cypher tool through the server-level function interface.
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

import codegiraffe.server as server_module
from codegiraffe.server import (
    codegiraffe_init,
    codegiraffe_sync,
    codegiraffe_history,
    codegiraffe_diff,
    codegiraffe_snapshot,
    codegiraffe_restore,
    codegiraffe_federate,
    codegiraffe_cross_query,
    codegiraffe_cross_edges,
    codegiraffe_cypher,
)
from codegiraffe.storage import JSONStorage
from codegiraffe.versioning import VersionStore
from codegiraffe.federation import GraphFederation


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_server_state():
    """Reset server module globals before each test to avoid cross-test pollution."""
    server_module._graph = None
    server_module._storage = JSONStorage()
    server_module._version_store = VersionStore()
    server_module._federation = GraphFederation()
    yield
    # Clean up after the test as well
    server_module._graph = None
    server_module._storage = JSONStorage()
    server_module._version_store = VersionStore()
    server_module._federation = GraphFederation()


@pytest.fixture
def project_dir(tmp_path):
    """Create a minimal Python project for testing."""
    py_file = tmp_path / "app.py"
    py_file.write_text('''
from flask import Flask
app = Flask(__name__)

@app.route("/api/users")
def get_users():
    return []
''')
    return str(tmp_path)


@pytest.fixture
def second_project_dir(tmp_path):
    """Create a second minimal Python project for federation testing."""
    repo_b = tmp_path / "repo-b"
    repo_b.mkdir()
    py_file = repo_b / "service.py"
    py_file.write_text('''
import requests

def call_auth():
    return requests.get("https://auth.example.com/api/verify")

class PaymentService:
    def process(self):
        pass
''')
    return str(repo_b)


# ---------------------------------------------------------------------------
# Versioning tool tests
# ---------------------------------------------------------------------------


class TestHistory:
    def test_history_after_init(self, project_dir):
        """Init a project, call history, verify it returns a list with at least 1 entry."""
        codegiraffe_init(project_dir)
        result = codegiraffe_history(project_dir)
        history = json.loads(result)

        assert isinstance(history, list)
        assert len(history) >= 1
        # The init creates a version entry
        entry = history[0]
        assert "version_id" in entry
        assert "message" in entry
        assert "timestamp" in entry
        assert entry["message"] == "Init"

    def test_history_empty_before_init(self, tmp_path):
        """Call history on uninitiated project, verify it returns an empty list."""
        result = codegiraffe_history(str(tmp_path))
        history = json.loads(result)
        assert history == []


class TestSnapshot:
    def test_snapshot_creates_version(self, project_dir):
        """Init, snapshot with message, verify returned JSON has version_id and message."""
        codegiraffe_init(project_dir)
        result = codegiraffe_snapshot(project_dir, message="Before refactor")
        data = json.loads(result)

        assert "version_id" in data
        assert data["message"] == "Before refactor"
        assert "timestamp" in data

    def test_history_shows_snapshot(self, project_dir):
        """Init, snapshot, history, verify history includes the snapshot."""
        codegiraffe_init(project_dir)
        codegiraffe_snapshot(project_dir, message="My snapshot")
        result = codegiraffe_history(project_dir)
        history = json.loads(result)

        # Should have at least 2 entries: init + snapshot
        assert len(history) >= 2
        messages = [entry["message"] for entry in history]
        assert "My snapshot" in messages


class TestDiff:
    def test_diff_returns_version_diff(self, project_dir):
        """Init, snapshot, diff on the snapshot version."""
        codegiraffe_init(project_dir)
        snap_result = codegiraffe_snapshot(project_dir, message="Snap")
        snap_data = json.loads(snap_result)
        version_id = snap_data["version_id"]

        result = codegiraffe_diff(project_dir, version_a=version_id)
        diff_data = json.loads(result)

        # A snapshot diffs against itself, so the diff should have the expected keys
        assert "nodes_added" in diff_data
        assert "nodes_removed" in diff_data
        assert "edges_added" in diff_data
        assert "edges_removed" in diff_data


class TestRestore:
    def test_restore_returns_not_supported(self, project_dir):
        """Init, restore, verify it returns the 'not supported' message."""
        codegiraffe_init(project_dir)
        result = codegiraffe_restore(project_dir, version_id=1)

        assert "not yet supported" in result
        assert "backup snapshot" in result.lower() or "backup" in result.lower()


# ---------------------------------------------------------------------------
# Federation tool tests
# ---------------------------------------------------------------------------


class TestFederate:
    def test_federate_two_projects(self, tmp_path):
        """Create two temp dirs with Python files, init both, federate, verify JSON result."""
        # Create repo A
        repo_a = tmp_path / "repo-a"
        repo_a.mkdir()
        (repo_a / "app.py").write_text('''
from flask import Flask
app = Flask(__name__)

@app.route("/api/users")
def get_users():
    return []
''')

        # Create repo B
        repo_b = tmp_path / "repo-b"
        repo_b.mkdir()
        (repo_b / "service.py").write_text('''
import requests

class PaymentService:
    def process(self):
        pass
''')

        # Init both
        codegiraffe_init(str(repo_a))
        # Reset _graph so second init does not reuse the first project's cached graph
        server_module._graph = None
        codegiraffe_init(str(repo_b))

        result = codegiraffe_federate([str(repo_a), str(repo_b)])
        data = json.loads(result)

        assert "registered_repos" in data
        assert "repo-a" in data["registered_repos"]
        assert "repo-b" in data["registered_repos"]
        assert "total_nodes" in data
        assert "total_edges" in data


class TestCrossQuery:
    def test_cross_query_requires_federation(self):
        """Call cross_query without federating, verify error or empty result."""
        # No repos are registered, so querying a node should fail or return empty
        result = codegiraffe_cross_query(node_id="repo:nonexistent::service:Foo", depth=1)

        # When the federation is empty, the unified graph has no nodes,
        # so the query should return an empty GraphData
        data = json.loads(result)
        assert len(data.get("nodes", {})) == 0


class TestCrossEdges:
    def test_cross_edges_after_federate(self, tmp_path):
        """Federate two projects, call cross_edges, verify returns JSON array."""
        # Create repo A
        repo_a = tmp_path / "repo-a"
        repo_a.mkdir()
        (repo_a / "app.py").write_text('''
from flask import Flask
app = Flask(__name__)

@app.route("/api/users")
def get_users():
    return []
''')

        # Create repo B
        repo_b = tmp_path / "repo-b"
        repo_b.mkdir()
        (repo_b / "service.py").write_text('''
class PaymentService:
    def process(self):
        pass
''')

        # Init both repos
        codegiraffe_init(str(repo_a))
        server_module._graph = None
        codegiraffe_init(str(repo_b))

        # Federate
        codegiraffe_federate([str(repo_a), str(repo_b)])

        # Call cross_edges
        result = codegiraffe_cross_edges()
        data = json.loads(result)

        # Should be a JSON array (possibly empty since there are no manual cross-repo edges)
        assert isinstance(data, list)


# ---------------------------------------------------------------------------
# Neo4j / Cypher tool test
# ---------------------------------------------------------------------------


class TestCypher:
    def test_cypher_without_neo4j(self, project_dir):
        """Call cypher tool, verify it returns the 'not installed' error."""
        result = codegiraffe_cypher(project_dir, query="MATCH (n) RETURN n LIMIT 1")

        # neo4j is not installed in the dev environment, so either:
        # - ImportError from Neo4jStorage constructor (HAS_NEO4J=False), or
        # - The server catches the ImportError and returns an error message
        assert "not installed" in result.lower() or "error" in result.lower()


# ---------------------------------------------------------------------------
# Init variations
# ---------------------------------------------------------------------------


class TestInitVariations:
    def test_init_with_scanner_mode_regex(self, project_dir):
        """Init with scanner_mode='regex' (default), verify success."""
        result = codegiraffe_init(project_dir, scanner_mode="regex")

        assert "Initialized graph" in result
        assert "nodes" in result.lower()

    def test_init_with_backend_neo4j_error(self, project_dir):
        """Init with backend='neo4j', verify error about neo4j not installed."""
        result = codegiraffe_init(project_dir, backend="neo4j")

        # Should fail because neo4j driver is not installed
        assert "error" in result.lower()
        assert "neo4j" in result.lower() or "not installed" in result.lower()


# ---------------------------------------------------------------------------
# Sync + versioning test
# ---------------------------------------------------------------------------


class TestSyncVersioning:
    def test_sync_creates_version(self, project_dir):
        """Init, sync, check history has 2 entries (init + sync)."""
        codegiraffe_init(project_dir)
        codegiraffe_sync(project_dir)

        result = codegiraffe_history(project_dir)
        history = json.loads(result)

        assert len(history) >= 2
        messages = [entry["message"] for entry in history]
        assert "Init" in messages
        assert "Sync" in messages

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
    codegiraffe_add_contract,
    codegiraffe_add_relation,
    codegiraffe_blast_radius,
    codegiraffe_context_for,
    codegiraffe_contracts,
    codegiraffe_cross_edges,
    codegiraffe_cross_query,
    codegiraffe_cycles,
    codegiraffe_cypher,
    codegiraffe_diff,
    codegiraffe_federate,
    codegiraffe_history,
    codegiraffe_hotspots,
    codegiraffe_init,
    codegiraffe_restore,
    codegiraffe_risk_assessment,
    codegiraffe_snapshot,
    codegiraffe_sync,
    codegiraffe_validate_contracts,
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


# ---------------------------------------------------------------------------
# include_tests parameter tests
# ---------------------------------------------------------------------------


class TestIncludeTests:
    def test_init_accepts_include_tests(self, tmp_path):
        """T023: codegiraffe_init accepts include_tests parameter."""
        (tmp_path / "app.py").write_text("class AppService:\n    pass\n")
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_app.py").write_text("class TestAppService:\n    pass\n")

        # Without include_tests (default)
        result = codegiraffe_init(str(tmp_path))
        assert "Initialized graph" in result

    def test_init_with_include_tests_true(self, tmp_path):
        """T023: codegiraffe_init with include_tests=True includes test nodes."""
        (tmp_path / "app.py").write_text("class AppService:\n    pass\n")
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_app.py").write_text("class TestAppService:\n    pass\n")

        result = codegiraffe_init(str(tmp_path), include_tests=True)
        assert "Initialized graph" in result

    def test_sync_accepts_include_tests(self, tmp_path):
        """T023: codegiraffe_sync accepts include_tests parameter."""
        (tmp_path / "app.py").write_text("class AppService:\n    pass\n")

        codegiraffe_init(str(tmp_path))
        result = codegiraffe_sync(str(tmp_path), include_tests=False)
        assert "Sync complete" in result


# ---------------------------------------------------------------------------
# Blast radius tool tests (v0.7.0)
# ---------------------------------------------------------------------------


class TestBlastRadiusTool:
    """Tests for the codegiraffe_blast_radius MCP tool."""

    def _build_chain_project(self, tmp_path):
        """Create a project with a chain: A -> B -> C -> D."""
        (tmp_path / "app.py").write_text(
            "class AppService:\n    pass\n"
        )
        project_path = str(tmp_path)
        codegiraffe_init(project_path)
        # Build a chain manually: A -> B -> C -> D
        codegiraffe_add_relation(project_path, "A", "B", "calls")
        codegiraffe_add_relation(project_path, "B", "C", "calls")
        codegiraffe_add_relation(project_path, "C", "D", "calls")
        return project_path

    def test_blast_radius_returns_markdown(self, tmp_path):
        """Blast radius returns a markdown impact report."""
        project_path = self._build_chain_project(tmp_path)
        result = codegiraffe_blast_radius(project_path, node_id="A")
        assert "## Impact Analysis" in result

    def test_blast_radius_missing_node(self, tmp_path):
        """Blast radius handles missing node gracefully (no exception)."""
        (tmp_path / "app.py").write_text("class AppService:\n    pass\n")
        project_path = str(tmp_path)
        codegiraffe_init(project_path)
        result = codegiraffe_blast_radius(project_path, node_id="nonexistent_node")
        # Should return an error string, not raise an exception
        assert isinstance(result, str)
        assert "not found" in result.lower()

    def test_blast_radius_with_upstream(self, tmp_path):
        """Blast radius with include_upstream=True adds upstream section."""
        project_path = self._build_chain_project(tmp_path)
        result = codegiraffe_blast_radius(
            project_path, node_id="B", include_upstream=True
        )
        assert "## Impact Analysis" in result
        # Upstream section should appear since A -> B exists
        assert "Upstream" in result

    def test_blast_radius_with_max_depth(self, tmp_path):
        """Blast radius with max_depth limits results."""
        project_path = self._build_chain_project(tmp_path)
        # A -> B -> C -> D: max_depth=1 from A should only reach B
        result_limited = codegiraffe_blast_radius(
            project_path, node_id="A", max_depth=1
        )
        result_full = codegiraffe_blast_radius(
            project_path, node_id="A"
        )
        assert "## Impact Analysis" in result_limited
        assert "## Impact Analysis" in result_full
        # The limited version should have fewer downstream nodes
        # D is 3 hops away, so it should be excluded at max_depth=1
        assert "D" not in result_limited or result_limited.count("D") < result_full.count("D")


# ---------------------------------------------------------------------------
# Risk assessment tool tests (v0.7.0)
# ---------------------------------------------------------------------------


class TestRiskAssessmentTool:
    """Tests for the codegiraffe_risk_assessment MCP tool."""

    def test_risk_assessment_default(self, tmp_path):
        """Risk assessment returns top-10 markdown report."""
        (tmp_path / "app.py").write_text(
            "class AppService:\n    pass\n\n"
            "class UserService:\n    pass\n"
        )
        project_path = str(tmp_path)
        codegiraffe_init(project_path)
        codegiraffe_add_relation(project_path, "A", "B", "calls")
        codegiraffe_add_relation(project_path, "B", "C", "calls")

        result = codegiraffe_risk_assessment(project_path)
        assert "## Risk Assessment Report" in result
        assert "**Graph size:**" in result
        assert "**Nodes assessed:**" in result

    def test_risk_assessment_specific_nodes(self, tmp_path):
        """Risk assessment with specific node_ids returns only those nodes."""
        (tmp_path / "app.py").write_text("class AppService:\n    pass\n")
        project_path = str(tmp_path)
        codegiraffe_init(project_path)
        codegiraffe_add_relation(project_path, "A", "B", "calls")
        codegiraffe_add_relation(project_path, "B", "C", "calls")

        result = codegiraffe_risk_assessment(project_path, node_ids=["A"])
        assert "## Risk Assessment Report" in result
        # Only node A should be assessed
        assert "**Nodes assessed:** 1" in result

    def test_risk_assessment_empty_graph(self, tmp_path):
        """Risk assessment on empty graph returns appropriate message."""
        # Create an empty directory with no Python files
        project_path = str(tmp_path)
        codegiraffe_init(project_path)
        # The graph may have some scanned nodes, but if the graph is truly
        # empty we should get the right message. Let's force an empty graph.
        server_module._graph = None
        from codegiraffe.graph import ArchGraph, GraphData
        empty_data = GraphData(project_path=project_path)
        empty_graph = ArchGraph(empty_data)
        server_module._graph = empty_graph

        result = codegiraffe_risk_assessment(project_path)
        assert "Graph is empty" in result


# ---------------------------------------------------------------------------
# Cycles tool tests (v0.7.0)
# ---------------------------------------------------------------------------


class TestCyclesTool:
    """Tests for the codegiraffe_cycles MCP tool."""

    def test_no_cycles(self, tmp_path):
        """No cycles returns appropriate message."""
        (tmp_path / "app.py").write_text("class AppService:\n    pass\n")
        project_path = str(tmp_path)
        codegiraffe_init(project_path)
        # Add a simple chain (no cycles): A -> B -> C
        codegiraffe_add_relation(project_path, "A", "B", "calls")
        codegiraffe_add_relation(project_path, "B", "C", "calls")

        result = codegiraffe_cycles(project_path)
        assert "No circular dependencies detected." == result

    def test_with_cycles(self, tmp_path):
        """Cycles tool detects and formats cycles in markdown."""
        (tmp_path / "app.py").write_text("class AppService:\n    pass\n")
        project_path = str(tmp_path)
        codegiraffe_init(project_path)
        # Create a cycle: X -> Y -> Z -> X
        codegiraffe_add_relation(project_path, "X", "Y", "calls")
        codegiraffe_add_relation(project_path, "Y", "Z", "calls")
        codegiraffe_add_relation(project_path, "Z", "X", "calls")

        result = codegiraffe_cycles(project_path)
        assert "## Circular Dependencies" in result
        assert "cycle(s) detected" in result


# ---------------------------------------------------------------------------
# Enhanced context_for tool tests (v0.7.0)
# ---------------------------------------------------------------------------


class TestEnhancedContextFor:
    """Tests for the enhanced codegiraffe_context_for with include_impact."""

    def test_context_for_default_unchanged(self, project_dir):
        """Default behavior (include_impact=False) is unchanged."""
        codegiraffe_init(project_dir)
        result = codegiraffe_context_for(project_dir, task="user API")
        data = json.loads(result)
        # Should still return valid GraphData JSON
        assert "nodes" in data
        assert "edges" in data
        # No impact metadata by default
        for node_data in data.get("nodes", {}).values():
            meta = node_data.get("metadata", {})
            assert "_blast_radius_count" not in meta
            assert "_risk_score" not in meta

    def test_context_for_with_impact(self, project_dir):
        """include_impact=True augments nodes with _blast_radius_count and _risk_score."""
        codegiraffe_init(project_dir)
        result = codegiraffe_context_for(
            project_dir, task="user API", include_impact=True
        )
        data = json.loads(result)
        assert "nodes" in data
        # All returned nodes should have impact metadata
        for node_data in data.get("nodes", {}).values():
            meta = node_data.get("metadata", {})
            assert "_blast_radius_count" in meta
            assert "_risk_score" in meta


# ---------------------------------------------------------------------------
# Enhanced hotspots tool tests (v0.7.0)
# ---------------------------------------------------------------------------


class TestEnhancedHotspots:
    """Tests for the enhanced codegiraffe_hotspots with metrics parameter."""

    def _build_project(self, tmp_path):
        """Create a project with several nodes and edges."""
        (tmp_path / "app.py").write_text(
            "class AppService:\n    pass\n\n"
            "class UserService:\n    pass\n"
        )
        project_path = str(tmp_path)
        codegiraffe_init(project_path)
        codegiraffe_add_relation(project_path, "A", "B", "calls")
        codegiraffe_add_relation(project_path, "B", "C", "calls")
        codegiraffe_add_relation(project_path, "A", "C", "calls")
        codegiraffe_add_relation(project_path, "C", "D", "calls")
        return project_path

    def test_hotspots_default_unchanged(self, tmp_path):
        """Default behavior (metrics='degree') unchanged."""
        project_path = self._build_project(tmp_path)
        result = codegiraffe_hotspots(project_path)
        data = json.loads(result)
        assert isinstance(data, list)
        assert len(data) > 0
        # Each entry has node_id, label, type, score
        for item in data:
            assert "node_id" in item
            assert "label" in item
            assert "type" in item
            assert "score" in item

    def test_hotspots_betweenness(self, tmp_path):
        """metrics='betweenness' returns results ranked by betweenness centrality."""
        project_path = self._build_project(tmp_path)
        result = codegiraffe_hotspots(project_path, metrics="betweenness")
        data = json.loads(result)
        assert isinstance(data, list)
        assert len(data) > 0
        for item in data:
            assert "node_id" in item
            assert "score" in item

    def test_hotspots_combined(self, tmp_path):
        """metrics='combined' returns results."""
        project_path = self._build_project(tmp_path)
        result = codegiraffe_hotspots(project_path, metrics="combined")
        data = json.loads(result)
        assert isinstance(data, list)
        assert len(data) > 0
        for item in data:
            assert "node_id" in item
            assert "score" in item


class TestContractTools:
    """Tests for the contract MCP tools."""

    def _init_project(self, tmp_path):
        """Create a minimal project with a couple of service nodes."""
        (tmp_path / "app.py").write_text(
            "class AppService:\n    pass\n"
        )
        project_path = str(tmp_path)
        codegiraffe_init(project_path)
        # Add some service nodes to act as producer/consumers
        codegiraffe_add_relation(project_path, "svc-orders", "svc-payments", "calls")
        codegiraffe_add_relation(project_path, "svc-orders", "svc-inventory", "calls")
        return project_path

    def test_contracts_tool_returns_markdown(self, tmp_path):
        """Add a contract and verify the contracts tool returns markdown."""
        project_path = self._init_project(tmp_path)
        codegiraffe_add_contract(
            project_path,
            name="OrderCreated",
            contract_type="event",
            producer="svc-orders",
            consumers="svc-payments,svc-inventory",
        )
        result = codegiraffe_contracts(project_path)
        assert "## Contracts" in result
        assert "OrderCreated" in result

    def test_contracts_tool_no_contracts_helpful_message(self, tmp_path):
        """No contracts returns a helpful message mentioning codegiraffe_add_contract."""
        (tmp_path / "app.py").write_text("class Svc:\n    pass\n")
        project_path = str(tmp_path)
        codegiraffe_init(project_path)
        result = codegiraffe_contracts(project_path)
        assert "codegiraffe_add_contract" in result

    def test_contracts_tool_filter_by_type(self, tmp_path):
        """Filter contracts by type returns only matching contracts."""
        project_path = self._init_project(tmp_path)
        codegiraffe_add_contract(
            project_path,
            name="OrderCreated",
            contract_type="event",
            producer="svc-orders",
            consumers="svc-payments",
        )
        codegiraffe_add_contract(
            project_path,
            name="OrderAPI",
            contract_type="api",
            producer="svc-orders",
            consumers="svc-inventory",
        )
        # Filter by api only
        result = codegiraffe_contracts(project_path, contract_type="api")
        assert "OrderAPI" in result
        assert "OrderCreated" not in result

    def test_validate_contracts_tool_valid(self, tmp_path):
        """Validate returns valid contracts when producer/consumers exist."""
        project_path = self._init_project(tmp_path)
        codegiraffe_add_contract(
            project_path,
            name="OrderCreated",
            contract_type="event",
            producer="svc-orders",
            consumers="svc-payments,svc-inventory",
        )
        result = codegiraffe_validate_contracts(project_path)
        assert "## Contract Validation Report" in result
        assert "Valid" in result

    def test_add_contract_creates_nodes_and_edges(self, tmp_path):
        """Adding a contract creates the contract node with correct metadata and edges."""
        project_path = self._init_project(tmp_path)
        codegiraffe_add_contract(
            project_path,
            name="PaymentSchema",
            contract_type="data",
            producer="svc-payments",
            consumers="svc-orders",
            version="1.0.0",
        )
        # Reload graph and inspect
        from codegiraffe.server import _ensure_graph
        graph = _ensure_graph(project_path)

        # Contract node exists
        assert "contract:PaymentSchema" in graph.graph
        node_data = graph.graph.nodes["contract:PaymentSchema"].get("node")
        assert node_data is not None
        assert node_data.type == "contract"
        assert node_data.metadata["contract_type"] == "data"
        assert node_data.metadata["producer"] == "svc-payments"
        assert "svc-orders" in node_data.metadata["consumers"]
        assert node_data.metadata["version"] == "1.0.0"
        assert node_data.metadata["status"] == "active"
        assert node_data.manual is True

        # Produces edge exists
        edge_data = graph.graph.edges.get(
            ("svc-payments", "contract:PaymentSchema"), {}
        )
        edge_obj = edge_data.get("edge")
        assert edge_obj is not None
        assert edge_obj.type == "produces"

        # Consumes_contract edge exists
        edge_data = graph.graph.edges.get(
            ("svc-orders", "contract:PaymentSchema"), {}
        )
        edge_obj = edge_data.get("edge")
        assert edge_obj is not None
        assert edge_obj.type == "consumes_contract"

    def test_add_contract_invalid_type_returns_error(self, tmp_path):
        """Invalid contract_type returns an error string, does not crash."""
        project_path = self._init_project(tmp_path)
        result = codegiraffe_add_contract(
            project_path,
            name="BadContract",
            contract_type="invalid_type",
            producer="svc-orders",
            consumers="svc-payments",
        )
        assert "Error" in result
        assert "invalid_type" in result

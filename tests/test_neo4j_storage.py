"""Tests for the Neo4j storage backend (codegiraffe.neo4j_storage).

All tests mock the neo4j driver -- no running Neo4j instance required.
"""

from __future__ import annotations

import hashlib
import json
from unittest.mock import MagicMock, patch

import pytest

from codegiraffe.graph import Edge, GraphData, Node
from codegiraffe.neo4j_storage import Neo4jStorage, is_available
from codegiraffe.schema import EdgeType, NodeType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def graph_data():
    """Standard graph data for testing save/load round-trips."""
    return GraphData(
        nodes={
            "endpoint:/api/users": Node(
                id="endpoint:/api/users",
                type=NodeType.ENDPOINT,
                label="GET /api/users",
                file_path="app.py",
            ),
            "table:users": Node(
                id="table:users",
                type=NodeType.DATABASE_TABLE,
                label="users table",
            ),
        },
        edges=[
            Edge(
                source="endpoint:/api/users",
                target="table:users",
                type=EdgeType.READS,
            ),
        ],
        project_path="/tmp/myproject",
        last_scan="2025-01-15T10:30:00+00:00",
        schema_version="1.0",
    )


@pytest.fixture
def complex_graph_data():
    """Graph data with metadata, manual flags, and None file_path."""
    return GraphData(
        nodes={
            "service:Auth": Node(
                id="service:Auth",
                type=NodeType.SERVICE,
                label="Auth Service",
                file_path="services/auth.py",
                metadata={"framework": "flask", "version": "2.0"},
                manual=True,
            ),
            "table:sessions": Node(
                id="table:sessions",
                type=NodeType.DATABASE_TABLE,
                label="sessions table",
                metadata={"engine": "postgres"},
                manual=False,
            ),
            "env:SECRET_KEY": Node(
                id="env:SECRET_KEY",
                type=NodeType.ENV_VAR,
                label="SECRET_KEY",
                file_path=None,
                metadata={},
                manual=False,
            ),
        },
        edges=[
            Edge(
                source="service:Auth",
                target="table:sessions",
                type=EdgeType.READS,
                metadata={"query": "SELECT * FROM sessions"},
                manual=False,
            ),
            Edge(
                source="service:Auth",
                target="env:SECRET_KEY",
                type=EdgeType.DEPENDS_ON,
                metadata={"required": True},
                manual=True,
            ),
        ],
        project_path="/tmp/complex_project",
        last_scan="2025-01-15T10:30:00+00:00",
        schema_version="1.0",
    )


@pytest.fixture
def mock_driver():
    """Create a mock Neo4j driver with session context-manager support."""
    driver = MagicMock()
    session = MagicMock()
    tx = MagicMock()

    # session as context manager
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)

    # session.begin_transaction() returns tx directly (not as context manager)
    session.begin_transaction.return_value = tx

    return driver, session, tx


@pytest.fixture
def storage(mock_driver):
    """Create a Neo4jStorage with a mocked driver injected directly."""
    driver, _, _ = mock_driver
    with patch("codegiraffe.neo4j_storage.HAS_NEO4J", True):
        s = Neo4jStorage(uri="neo4j://test:7687", auth=("neo4j", "test"))
    # Inject the mock driver directly, bypassing _get_driver's lazy init
    s._driver = driver
    return s


# ---------------------------------------------------------------------------
# Test: is_available
# ---------------------------------------------------------------------------

class TestIsAvailable:
    """is_available() reports whether the neo4j driver package is importable."""

    def test_is_available_returns_bool(self):
        result = is_available()
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# Test: ImportError when neo4j not installed
# ---------------------------------------------------------------------------

class TestImportGuard:
    """Neo4jStorage raises ImportError when neo4j driver is absent."""

    def test_raises_import_error_when_neo4j_unavailable(self):
        with patch("codegiraffe.neo4j_storage.HAS_NEO4J", False):
            with pytest.raises(ImportError, match="Neo4j driver not installed"):
                Neo4jStorage()


# ---------------------------------------------------------------------------
# Test: Connection configuration
# ---------------------------------------------------------------------------

class TestConnectionConfig:
    """Neo4jStorage reads connection parameters from env vars or constructor args."""

    def test_reads_env_vars(self):
        env = {
            "NEO4J_URI": "neo4j://custom:7687",
            "NEO4J_USER": "admin",
            "NEO4J_PASSWORD": "secret123",
        }
        with patch("codegiraffe.neo4j_storage.HAS_NEO4J", True):
            with patch.dict("os.environ", env, clear=False):
                s = Neo4jStorage()
                assert s._uri == "neo4j://custom:7687"
                assert s._auth == ("admin", "secret123")

    def test_uses_defaults_when_env_vars_missing(self):
        with patch("codegiraffe.neo4j_storage.HAS_NEO4J", True):
            with patch.dict("os.environ", {}, clear=True):
                s = Neo4jStorage()
                assert s._uri == "neo4j://localhost:7687"
                assert s._auth == ("neo4j", "")

    def test_explicit_uri_and_auth_override_env(self):
        env = {
            "NEO4J_URI": "neo4j://env:7687",
            "NEO4J_USER": "envuser",
            "NEO4J_PASSWORD": "envpass",
        }
        with patch("codegiraffe.neo4j_storage.HAS_NEO4J", True):
            with patch.dict("os.environ", env, clear=False):
                s = Neo4jStorage(uri="neo4j://explicit:7687", auth=("u", "p"))
                assert s._uri == "neo4j://explicit:7687"
                assert s._auth == ("u", "p")


# ---------------------------------------------------------------------------
# Test: _project_label
# ---------------------------------------------------------------------------

class TestProjectLabel:
    """_project_label produces consistent, Neo4j-safe labels."""

    def test_consistent_label(self):
        label1 = Neo4jStorage._project_label("/tmp/myproject")
        label2 = Neo4jStorage._project_label("/tmp/myproject")
        assert label1 == label2

    def test_different_paths_produce_different_labels(self):
        label1 = Neo4jStorage._project_label("/tmp/project_a")
        label2 = Neo4jStorage._project_label("/tmp/project_b")
        assert label1 != label2

    def test_label_starts_with_prefix(self):
        label = Neo4jStorage._project_label("/some/path")
        assert label.startswith("CG_")

    def test_label_uses_sha256_prefix(self):
        path = "/tmp/myproject"
        expected_hash = hashlib.sha256(path.encode()).hexdigest()[:12]
        label = Neo4jStorage._project_label(path)
        assert label == f"CG_{expected_hash}"

    def test_label_is_neo4j_safe(self):
        """Label should only contain alphanumeric chars and underscores."""
        label = Neo4jStorage._project_label("/a/path/with spaces/and-dashes")
        assert label.replace("_", "").isalnum()


# ---------------------------------------------------------------------------
# Test: exists()
# ---------------------------------------------------------------------------

class TestExists:
    """exists() returns True/False based on node count in Neo4j."""

    def test_exists_returns_true_when_nodes_present(self, storage, mock_driver):
        _, session, _ = mock_driver
        record = MagicMock()
        record.__getitem__ = MagicMock(return_value=True)
        result = MagicMock()
        result.single.return_value = record
        session.run.return_value = result

        assert storage.exists("/tmp/myproject") is True

    def test_exists_returns_false_when_no_nodes(self, storage, mock_driver):
        _, session, _ = mock_driver
        record = MagicMock()
        record.__getitem__ = MagicMock(return_value=False)
        result = MagicMock()
        result.single.return_value = record
        session.run.return_value = result

        assert storage.exists("/tmp/myproject") is False

    def test_exists_returns_false_on_exception(self, storage, mock_driver):
        _, session, _ = mock_driver
        session.run.side_effect = Exception("Connection refused")

        assert storage.exists("/tmp/myproject") is False


# ---------------------------------------------------------------------------
# Test: load()
# ---------------------------------------------------------------------------

class TestLoad:
    """load() returns None when no data exists, GraphData otherwise."""

    def test_load_returns_none_when_no_data(self, storage, mock_driver):
        _, session, _ = mock_driver

        # exists check returns False
        record = MagicMock()
        record.__getitem__ = MagicMock(return_value=False)
        exists_result = MagicMock()
        exists_result.single.return_value = record
        session.run.return_value = exists_result

        result = storage.load("/tmp/myproject")
        assert result is None

    def test_load_returns_graph_data(self, storage, mock_driver, graph_data):
        _, session, _ = mock_driver

        # First call: exists check -> True
        exists_record = MagicMock()
        exists_record.__getitem__ = MagicMock(return_value=True)
        exists_result = MagicMock()
        exists_result.single.return_value = exists_record

        # Second call: meta query
        meta_record = MagicMock()
        meta_record.data.return_value = {
            "meta": {
                "project_path": "/tmp/myproject",
                "last_scan": "2025-01-15T10:30:00+00:00",
                "schema_version": "1.0",
            }
        }
        meta_result = MagicMock()
        meta_result.single.return_value = meta_record

        # Third call: nodes query
        node1_record = MagicMock()
        node1_record.data.return_value = {
            "n": {
                "id": "endpoint:/api/users",
                "type": "endpoint",
                "label": "GET /api/users",
                "file_path": "app.py",
                "metadata": "{}",
                "manual": False,
            }
        }
        node2_record = MagicMock()
        node2_record.data.return_value = {
            "n": {
                "id": "table:users",
                "type": "database_table",
                "label": "users table",
                "file_path": None,
                "metadata": "{}",
                "manual": False,
            }
        }
        nodes_result = MagicMock()
        nodes_result.__iter__ = MagicMock(
            return_value=iter([node1_record, node2_record])
        )

        # Fourth call: edges query
        edge_record = MagicMock()
        edge_record.data.return_value = {
            "source": "endpoint:/api/users",
            "target": "table:users",
            "type": "reads",
            "metadata": "{}",
            "manual": False,
        }
        edges_result = MagicMock()
        edges_result.__iter__ = MagicMock(return_value=iter([edge_record]))

        # Wire up session.run to return correct results for each call
        session.run.side_effect = [
            exists_result,
            meta_result,
            nodes_result,
            edges_result,
        ]

        loaded = storage.load("/tmp/myproject")

        assert loaded is not None
        assert set(loaded.nodes.keys()) == {
            "endpoint:/api/users",
            "table:users",
        }
        assert loaded.nodes["endpoint:/api/users"].label == "GET /api/users"
        assert loaded.nodes["endpoint:/api/users"].file_path == "app.py"
        assert loaded.nodes["table:users"].file_path is None
        assert len(loaded.edges) == 1
        assert loaded.edges[0].source == "endpoint:/api/users"
        assert loaded.edges[0].target == "table:users"
        assert loaded.edges[0].type == "reads"
        assert loaded.project_path == "/tmp/myproject"
        assert loaded.last_scan == "2025-01-15T10:30:00+00:00"
        assert loaded.schema_version == "1.0"

    def test_load_returns_none_on_exception(self, storage, mock_driver):
        _, session, _ = mock_driver
        session.run.side_effect = Exception("Connection lost")

        result = storage.load("/tmp/myproject")
        assert result is None


# ---------------------------------------------------------------------------
# Test: save()
# ---------------------------------------------------------------------------

class TestSave:
    """save() calls correct Cypher operations."""

    def test_save_executes_cypher(self, storage, mock_driver, graph_data):
        _, session, tx = mock_driver

        storage.save("/tmp/myproject", graph_data)

        # Verify the transaction was started
        assert session.begin_transaction.called

    def test_save_clears_existing_data(self, storage, mock_driver, graph_data):
        _, session, tx = mock_driver

        storage.save("/tmp/myproject", graph_data)

        # The first operation in the transaction should be a DETACH DELETE
        all_run_calls = tx.run.call_args_list
        assert len(all_run_calls) > 0

        first_query = all_run_calls[0][0][0]
        assert "DETACH DELETE" in first_query

    def test_save_creates_meta_node(self, storage, mock_driver, graph_data):
        _, session, tx = mock_driver

        storage.save("/tmp/myproject", graph_data)

        all_queries = [c[0][0] for c in tx.run.call_args_list]
        meta_queries = [q for q in all_queries if "Meta" in q]
        # Should have at least the delete and create for Meta
        assert len(meta_queries) >= 1, "Should create a metadata node"

    def test_save_creates_nodes(self, storage, mock_driver, graph_data):
        _, session, tx = mock_driver

        storage.save("/tmp/myproject", graph_data)

        all_queries = [c[0][0] for c in tx.run.call_args_list]
        node_queries = [
            q for q in all_queries if "UNWIND" in q and "node" in q.lower()
        ]
        assert len(node_queries) >= 1, "Should batch-create nodes"

    def test_save_creates_edges(self, storage, mock_driver, graph_data):
        _, session, tx = mock_driver

        storage.save("/tmp/myproject", graph_data)

        all_queries = [c[0][0] for c in tx.run.call_args_list]
        edge_queries = [
            q for q in all_queries if "UNWIND" in q and "edge" in q.lower()
        ]
        assert len(edge_queries) >= 1, "Should batch-create edges"

    def test_save_commits_transaction(self, storage, mock_driver, graph_data):
        _, session, tx = mock_driver

        storage.save("/tmp/myproject", graph_data)

        tx.commit.assert_called_once()

    def test_save_rolls_back_on_error(self, storage, mock_driver, graph_data):
        _, session, tx = mock_driver
        tx.run.side_effect = RuntimeError("Cypher error")

        with pytest.raises(RuntimeError, match="Cypher error"):
            storage.save("/tmp/myproject", graph_data)

        tx.rollback.assert_called_once()


# ---------------------------------------------------------------------------
# Test: run_cypher()
# ---------------------------------------------------------------------------

class TestRunCypher:
    """run_cypher() executes and returns results."""

    def test_run_cypher_returns_results(self, storage, mock_driver):
        _, session, _ = mock_driver

        record1 = MagicMock()
        record1.data.return_value = {"name": "Auth", "count": 5}
        record2 = MagicMock()
        record2.data.return_value = {"name": "Users", "count": 3}
        result = MagicMock()
        result.__iter__ = MagicMock(return_value=iter([record1, record2]))
        session.run.return_value = result

        rows = storage.run_cypher("MATCH (n) RETURN n.name AS name, count(*) AS count")

        assert len(rows) == 2
        assert rows[0] == {"name": "Auth", "count": 5}
        assert rows[1] == {"name": "Users", "count": 3}

    def test_run_cypher_with_empty_result(self, storage, mock_driver):
        _, session, _ = mock_driver

        result = MagicMock()
        result.__iter__ = MagicMock(return_value=iter([]))
        session.run.return_value = result

        rows = storage.run_cypher("MATCH (n:Nonexistent) RETURN n")
        assert rows == []


# ---------------------------------------------------------------------------
# Test: close()
# ---------------------------------------------------------------------------

class TestClose:
    """close() shuts down the driver connection."""

    def test_close_closes_driver(self, storage, mock_driver):
        driver, _, _ = mock_driver
        storage.close()
        driver.close.assert_called_once()

    def test_close_sets_driver_to_none(self, storage, mock_driver):
        storage.close()
        assert storage._driver is None

    def test_close_idempotent(self, storage, mock_driver):
        driver, _, _ = mock_driver
        storage.close()
        storage.close()  # Should not raise
        # Only one close call because _driver is None after first close
        driver.close.assert_called_once()


# ---------------------------------------------------------------------------
# Test: save/load round-trip (mocked)
# ---------------------------------------------------------------------------

class TestRoundTrip:
    """Verify data transformation logic through save+load with mocked driver."""

    def test_round_trip_node_serialization(self, complex_graph_data):
        """Verify that node data is serialized correctly for Neo4j storage."""
        # Test the label generation is consistent
        label = Neo4jStorage._project_label("/tmp/complex_project")
        assert label == Neo4jStorage._project_label("/tmp/complex_project")

        # Verify node data can be JSON-serialized for metadata
        for node in complex_graph_data.nodes.values():
            meta_json = json.dumps(node.metadata)
            assert json.loads(meta_json) == node.metadata

    def test_round_trip_edge_serialization(self, complex_graph_data):
        """Verify that edge data is serialized correctly for Neo4j storage."""
        for edge in complex_graph_data.edges:
            meta_json = json.dumps(edge.metadata)
            assert json.loads(meta_json) == edge.metadata

    def test_save_passes_correct_node_properties(self, storage, mock_driver, complex_graph_data):
        """Verify that save passes correct property maps for nodes."""
        _, session, tx = mock_driver

        storage.save("/tmp/complex_project", complex_graph_data)

        # Find the UNWIND nodes call and inspect its parameters
        found = False
        for c in tx.run.call_args_list:
            query = c[0][0]
            if "UNWIND" in query and "node" in query.lower():
                # Parameters are passed as kwargs
                params = c[1].get("nodes")
                if params is not None:
                    found = True
                    assert len(params) == 3
                    ids = {n["id"] for n in params}
                    assert ids == {"service:Auth", "table:sessions", "env:SECRET_KEY"}
                    # Verify manual flag is preserved
                    auth_node = next(n for n in params if n["id"] == "service:Auth")
                    assert auth_node["manual"] is True
                    # Verify metadata is JSON-serialized
                    assert isinstance(auth_node["metadata"], str)
                    assert json.loads(auth_node["metadata"]) == {
                        "framework": "flask",
                        "version": "2.0",
                    }
                break
        assert found, "Should have found a UNWIND nodes query"

    def test_save_passes_correct_edge_properties(self, storage, mock_driver, complex_graph_data):
        """Verify that save passes correct property maps for edges."""
        _, session, tx = mock_driver

        storage.save("/tmp/complex_project", complex_graph_data)

        # Find the UNWIND edges call and inspect its parameters
        found = False
        for c in tx.run.call_args_list:
            query = c[0][0]
            if "UNWIND" in query and "edge" in query.lower():
                params = c[1].get("edges")
                if params is not None:
                    found = True
                    assert len(params) == 2
                    reads_edge = next(e for e in params if e["type"] == "reads")
                    assert reads_edge["source"] == "service:Auth"
                    assert reads_edge["target"] == "table:sessions"
                    assert reads_edge["manual"] is False
                    depends_edge = next(e for e in params if e["type"] == "depends_on")
                    assert depends_edge["manual"] is True
                    assert isinstance(depends_edge["metadata"], str)
                    assert json.loads(depends_edge["metadata"]) == {"required": True}
                break
        assert found, "Should have found a UNWIND edges query"

    def test_save_empty_graph(self, storage, mock_driver):
        """Saving an empty graph should not attempt UNWIND for nodes/edges."""
        _, session, tx = mock_driver
        empty_data = GraphData()

        storage.save("/tmp/empty", empty_data)

        all_queries = [c[0][0] for c in tx.run.call_args_list]
        unwind_queries = [q for q in all_queries if "UNWIND" in q]
        assert len(unwind_queries) == 0, "Empty graph should skip UNWIND queries"
        # But should still delete and create meta
        assert any("DETACH DELETE" in q for q in all_queries)
        tx.commit.assert_called_once()

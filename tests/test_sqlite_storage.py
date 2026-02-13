"""Tests for the SQLite storage layer (codegiraffe.sqlite_storage)."""

import sqlite3

import pytest

from codegiraffe.graph import Edge, GraphData, Node
from codegiraffe.schema import EdgeType, NodeType
from codegiraffe.sqlite_storage import DB_FILENAME, STORAGE_DIR, SQLiteStorage


@pytest.fixture
def storage():
    return SQLiteStorage()


@pytest.fixture
def graph_data():
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
        schema_version="1.0",
    )


class TestSQLiteStorageSaveAndLoad:
    """Save GraphData to SQLite, load it back, verify nodes and edges match."""

    def test_save_and_load(self, storage, graph_data, tmp_path):
        project = str(tmp_path)
        storage.save(project, graph_data)
        loaded = storage.load(project)

        assert loaded is not None
        assert set(loaded.nodes.keys()) == set(graph_data.nodes.keys())

        for nid in graph_data.nodes:
            assert loaded.nodes[nid].id == graph_data.nodes[nid].id
            assert loaded.nodes[nid].type == graph_data.nodes[nid].type
            assert loaded.nodes[nid].label == graph_data.nodes[nid].label

        assert len(loaded.edges) == len(graph_data.edges)
        for orig, restored in zip(graph_data.edges, loaded.edges):
            assert orig.source == restored.source
            assert orig.target == restored.target
            assert orig.type == restored.type

    def test_save_and_load_preserves_schema_version(self, storage, graph_data, tmp_path):
        project = str(tmp_path)
        storage.save(project, graph_data)
        loaded = storage.load(project)
        assert loaded is not None
        assert loaded.schema_version == graph_data.schema_version

    def test_save_and_load_empty_graph(self, storage, tmp_path):
        project = str(tmp_path)
        empty_data = GraphData()
        storage.save(project, empty_data)
        loaded = storage.load(project)

        assert loaded is not None
        assert len(loaded.nodes) == 0
        assert len(loaded.edges) == 0


class TestSQLiteStorageExists:
    """exists returns False when no DB, True after save."""

    def test_exists_false(self, storage, tmp_path):
        project = str(tmp_path)
        assert storage.exists(project) is False

    def test_exists_true(self, storage, graph_data, tmp_path):
        project = str(tmp_path)
        storage.save(project, graph_data)
        assert storage.exists(project) is True


class TestSQLiteStorageLoadMissing:
    """load returns None when no file exists."""

    def test_load_missing(self, storage, tmp_path):
        project = str(tmp_path / "nonexistent_project")
        result = storage.load(project)
        assert result is None

    def test_load_missing_file_but_dir_exists(self, storage, tmp_path):
        """The .codegiraffe dir exists but graph.db does not."""
        codegiraffe_dir = tmp_path / STORAGE_DIR
        codegiraffe_dir.mkdir()
        result = storage.load(str(tmp_path))
        assert result is None


class TestSQLiteStorageLoadCorrupted:
    """Corrupted DB file returns None without crashing."""

    def test_load_corrupted_db(self, storage, tmp_path):
        db_path = tmp_path / STORAGE_DIR / DB_FILENAME
        db_path.parent.mkdir(parents=True)
        db_path.write_text("this is not a sqlite database!!!", encoding="utf-8")

        result = storage.load(str(tmp_path))
        assert result is None

    def test_load_empty_file(self, storage, tmp_path):
        """Empty file should return None, not crash."""
        db_path = tmp_path / STORAGE_DIR / DB_FILENAME
        db_path.parent.mkdir(parents=True)
        db_path.write_bytes(b"")

        result = storage.load(str(tmp_path))
        assert result is None


class TestSQLiteStorageRoundTrip:
    """Save complex graph with metadata and manual flags, load back, verify all fields."""

    def test_round_trip_with_metadata_and_manual(self, storage, tmp_path):
        project = str(tmp_path)

        data = GraphData(
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

        storage.save(project, data)
        loaded = storage.load(project)

        assert loaded is not None

        # Verify all nodes
        assert set(loaded.nodes.keys()) == {"service:Auth", "table:sessions", "env:SECRET_KEY"}

        auth_node = loaded.nodes["service:Auth"]
        assert auth_node.type == NodeType.SERVICE
        assert auth_node.label == "Auth Service"
        assert auth_node.file_path == "services/auth.py"
        assert auth_node.metadata == {"framework": "flask", "version": "2.0"}
        assert auth_node.manual is True

        sessions_node = loaded.nodes["table:sessions"]
        assert sessions_node.type == NodeType.DATABASE_TABLE
        assert sessions_node.metadata == {"engine": "postgres"}
        assert sessions_node.manual is False

        env_node = loaded.nodes["env:SECRET_KEY"]
        assert env_node.file_path is None
        assert env_node.manual is False

        # Verify all edges
        assert len(loaded.edges) == 2

        reads_edge = next(e for e in loaded.edges if e.type == EdgeType.READS)
        assert reads_edge.source == "service:Auth"
        assert reads_edge.target == "table:sessions"
        assert reads_edge.metadata == {"query": "SELECT * FROM sessions"}
        assert reads_edge.manual is False

        depends_edge = next(e for e in loaded.edges if e.type == EdgeType.DEPENDS_ON)
        assert depends_edge.source == "service:Auth"
        assert depends_edge.target == "env:SECRET_KEY"
        assert depends_edge.metadata == {"required": True}
        assert depends_edge.manual is True

        # Verify metadata
        assert loaded.project_path == "/tmp/complex_project"
        assert loaded.last_scan == "2025-01-15T10:30:00+00:00"
        assert loaded.schema_version == "1.0"

    def test_round_trip_preserves_file_path_none(self, storage, tmp_path):
        """Nodes with file_path=None should round-trip correctly."""
        project = str(tmp_path)
        data = GraphData(
            nodes={
                "queue:jobs": Node(
                    id="queue:jobs",
                    type=NodeType.QUEUE,
                    label="Job queue",
                    file_path=None,
                ),
            },
            edges=[],
            project_path=project,
        )

        storage.save(project, data)
        loaded = storage.load(project)

        assert loaded is not None
        assert loaded.nodes["queue:jobs"].file_path is None


class TestSQLiteStorageOverwrite:
    """Save twice, second save replaces first."""

    def test_overwrite(self, storage, tmp_path):
        project = str(tmp_path)

        # First save
        data1 = GraphData(
            nodes={
                "endpoint:/api/v1": Node(
                    id="endpoint:/api/v1",
                    type=NodeType.ENDPOINT,
                    label="v1 endpoint",
                ),
            },
            edges=[],
            project_path=project,
        )
        storage.save(project, data1)

        # Second save with different data
        data2 = GraphData(
            nodes={
                "endpoint:/api/v2": Node(
                    id="endpoint:/api/v2",
                    type=NodeType.ENDPOINT,
                    label="v2 endpoint",
                ),
                "table:orders": Node(
                    id="table:orders",
                    type=NodeType.DATABASE_TABLE,
                    label="orders",
                ),
            },
            edges=[
                Edge(
                    source="endpoint:/api/v2",
                    target="table:orders",
                    type=EdgeType.WRITES,
                ),
            ],
            project_path=project,
        )
        storage.save(project, data2)

        loaded = storage.load(project)

        assert loaded is not None
        assert set(loaded.nodes.keys()) == {"endpoint:/api/v2", "table:orders"}
        assert "endpoint:/api/v1" not in loaded.nodes
        assert len(loaded.edges) == 1
        assert loaded.edges[0].source == "endpoint:/api/v2"


class TestSQLiteStorageIndexes:
    """Verify indexes exist after save."""

    def test_indexes_exist(self, storage, graph_data, tmp_path):
        project = str(tmp_path)
        storage.save(project, graph_data)

        db_path = tmp_path / STORAGE_DIR / DB_FILENAME
        conn = sqlite3.connect(str(db_path))

        # Query sqlite_master for index names
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name"
        )
        index_names = {row[0] for row in cursor}
        conn.close()

        expected_indexes = {
            "idx_nodes_type",
            "idx_nodes_file_path",
            "idx_edges_source",
            "idx_edges_target",
            "idx_edges_type",
        }
        assert expected_indexes.issubset(index_names)


class TestSQLiteStorageCreatesDirectory:
    """Verify .codegiraffe dir is created on save."""

    def test_creates_directory(self, storage, graph_data, tmp_path):
        project = str(tmp_path)
        codegiraffe_dir = tmp_path / STORAGE_DIR

        assert not codegiraffe_dir.exists()

        storage.save(project, graph_data)

        assert codegiraffe_dir.exists()
        assert codegiraffe_dir.is_dir()

        db_file = codegiraffe_dir / DB_FILENAME
        assert db_file.exists()
        assert db_file.is_file()

    def test_save_idempotent_with_existing_dir(self, storage, graph_data, tmp_path):
        """Saving twice should not raise even if the dir already exists."""
        project = str(tmp_path)
        storage.save(project, graph_data)
        storage.save(project, graph_data)  # Should not raise

        assert storage.exists(project)

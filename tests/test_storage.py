"""Tests for the storage layer (codegiraffe.storage)."""

import json
import pytest
from pathlib import Path

from codegiraffe.graph import Node, Edge, GraphData
from codegiraffe.storage import JSONStorage, STORAGE_DIR, GRAPH_FILENAME
from codegiraffe.schema import NodeType, EdgeType


@pytest.fixture
def storage():
    return JSONStorage()


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


class TestSaveAndLoad:
    """test_save_and_load -- save GraphData, load it back, verify equal."""

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


class TestExistsFalse:
    """test_exists_false -- no file, exists returns False."""

    def test_exists_false(self, storage, tmp_path):
        project = str(tmp_path)
        assert storage.exists(project) is False


class TestExistsTrue:
    """test_exists_true -- after save, exists returns True."""

    def test_exists_true(self, storage, graph_data, tmp_path):
        project = str(tmp_path)
        storage.save(project, graph_data)
        assert storage.exists(project) is True


class TestLoadMissing:
    """test_load_missing -- load from nonexistent path returns None."""

    def test_load_missing(self, storage, tmp_path):
        project = str(tmp_path / "nonexistent_project")
        result = storage.load(project)
        assert result is None

    def test_load_missing_file_but_dir_exists(self, storage, tmp_path):
        """The .codegiraffe dir exists but graph.json does not."""
        codegiraffe_dir = tmp_path / STORAGE_DIR
        codegiraffe_dir.mkdir()
        result = storage.load(str(tmp_path))
        assert result is None


class TestLoadCorruptedJson:
    """test_load_corrupted_json -- write garbage to graph.json,
    load returns None without crashing."""

    def test_load_corrupted_json(self, storage, tmp_path):
        graph_path = tmp_path / STORAGE_DIR / GRAPH_FILENAME
        graph_path.parent.mkdir(parents=True)
        graph_path.write_text("this is not json at all!!!", encoding="utf-8")

        result = storage.load(str(tmp_path))
        assert result is None

    def test_load_invalid_json_structure(self, storage, tmp_path):
        """Valid JSON but not a valid GraphData structure."""
        graph_path = tmp_path / STORAGE_DIR / GRAPH_FILENAME
        graph_path.parent.mkdir(parents=True)
        graph_path.write_text(json.dumps({"nodes": "not_a_dict"}), encoding="utf-8")

        result = storage.load(str(tmp_path))
        assert result is None

    def test_load_empty_file(self, storage, tmp_path):
        """Empty file should return None, not crash."""
        graph_path = tmp_path / STORAGE_DIR / GRAPH_FILENAME
        graph_path.parent.mkdir(parents=True)
        graph_path.write_text("", encoding="utf-8")

        result = storage.load(str(tmp_path))
        assert result is None


class TestCreatesDirectory:
    """test_creates_directory -- verify .codegiraffe dir is created on save."""

    def test_creates_directory(self, storage, graph_data, tmp_path):
        project = str(tmp_path)
        codegiraffe_dir = tmp_path / STORAGE_DIR

        assert not codegiraffe_dir.exists()

        storage.save(project, graph_data)

        assert codegiraffe_dir.exists()
        assert codegiraffe_dir.is_dir()

        graph_file = codegiraffe_dir / GRAPH_FILENAME
        assert graph_file.exists()
        assert graph_file.is_file()

    def test_save_idempotent_with_existing_dir(self, storage, graph_data, tmp_path):
        """Saving twice should not raise even if the dir already exists."""
        project = str(tmp_path)
        storage.save(project, graph_data)
        storage.save(project, graph_data)  # Should not raise

        assert storage.exists(project)


# ---------------------------------------------------------------------------
# US2: Atomic JSON writes
# ---------------------------------------------------------------------------


class TestAtomicJSONWrite:
    """JSONStorage.save() is atomic — interrupted save leaves the original file intact."""

    def test_original_file_survives_interrupted_save(self, storage, graph_data, tmp_path, monkeypatch):
        """Monkeypatching os.replace to raise leaves the original file readable."""
        import codegiraffe.storage as _storage_module

        project = str(tmp_path)
        # First save — creates the original file
        storage.save(project, graph_data)

        graph_b = GraphData(
            nodes={
                "mod:changed": Node(id="mod:changed", type="module", label="changed"),
            },
            edges=[],
            project_path=project,
        )

        def raise_oserror(src, dst):
            raise OSError("Simulated crash mid-save")

        monkeypatch.setattr(_storage_module.os, "replace", raise_oserror)

        with pytest.raises(OSError):
            storage.save(project, graph_b)

        # Original file must still be loadable
        reloaded = storage.load(project)
        assert reloaded is not None
        assert "endpoint:/api/users" in reloaded.nodes

    def test_normal_save_replaces_file_atomically(self, storage, graph_data, tmp_path):
        """Save graph A then graph B; load returns graph B; no .tmp files remain."""
        project = str(tmp_path)
        storage.save(project, graph_data)

        graph_b = GraphData(
            nodes={
                "mod:new": Node(id="mod:new", type="module", label="new"),
            },
            edges=[],
            project_path=project,
        )
        storage.save(project, graph_b)

        loaded = storage.load(project)
        assert loaded is not None
        assert "mod:new" in loaded.nodes
        assert "endpoint:/api/users" not in loaded.nodes

        # No .tmp files should remain
        from codegiraffe.storage import STORAGE_DIR
        cg_dir = tmp_path / STORAGE_DIR
        tmp_files = list(cg_dir.glob("*.tmp"))
        assert tmp_files == [], f"Unexpected .tmp files: {tmp_files}"

    def test_first_save_leaves_no_corrupt_file_on_failure(self, storage, graph_data, tmp_path, monkeypatch):
        """On a fresh directory, interrupted save leaves no corrupt graph.json."""
        import codegiraffe.storage as _storage_module
        from codegiraffe.storage import STORAGE_DIR, GRAPH_FILENAME

        project = str(tmp_path)

        def raise_oserror(src, dst):
            raise OSError("Simulated crash")

        monkeypatch.setattr(_storage_module.os, "replace", raise_oserror)

        with pytest.raises(OSError):
            storage.save(project, graph_data)

        # graph.json must NOT exist — clean failure
        graph_file = tmp_path / STORAGE_DIR / GRAPH_FILENAME
        assert not graph_file.exists(), "graph.json must not exist after a failed first save"

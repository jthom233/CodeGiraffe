"""Tests for graph schema evolution and versioning (codegiraffe.versioning).

Tests are written FIRST per project constitution principle VI (Test-First).
"""
from __future__ import annotations

import json

import pytest
from pathlib import Path

from codegiraffe.graph import GraphData, Node, Edge
from codegiraffe.versioning import GraphDiff, GraphVersion, VersionStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_graph_data():
    return GraphData(
        nodes={
            "service:A": Node(id="service:A", type="service", label="A", file_path="a.py"),
            "endpoint:/api": Node(id="endpoint:/api", type="endpoint", label="/api", file_path="b.py"),
        },
        edges=[
            Edge(source="service:A", target="endpoint:/api", type="calls"),
        ],
        project_path="/test",
    )


@pytest.fixture
def extended_graph_data():
    """A graph with an extra node and edge compared to sample_graph_data."""
    return GraphData(
        nodes={
            "service:A": Node(id="service:A", type="service", label="A", file_path="a.py"),
            "endpoint:/api": Node(id="endpoint:/api", type="endpoint", label="/api", file_path="b.py"),
            "table:users": Node(id="table:users", type="database_table", label="users", file_path="c.py"),
        },
        edges=[
            Edge(source="service:A", target="endpoint:/api", type="calls"),
            Edge(source="endpoint:/api", target="table:users", type="reads"),
        ],
        project_path="/test",
    )


@pytest.fixture
def store():
    return VersionStore()


# ---------------------------------------------------------------------------
# GraphDiff tests
# ---------------------------------------------------------------------------

class TestGraphDiff:
    def test_create_empty_diff(self):
        diff = GraphDiff()
        assert diff.nodes_added == []
        assert diff.nodes_removed == []
        assert diff.edges_added == []
        assert diff.edges_removed == []
        assert diff.attrs_changed == {}

    def test_create_diff_with_values(self):
        diff = GraphDiff(
            nodes_added=["service:B"],
            nodes_removed=["service:A"],
            edges_added=[("service:B", "endpoint:/api", "calls")],
            edges_removed=[("service:A", "endpoint:/api", "calls")],
            attrs_changed={"service:A": {"label": {"old": "A", "new": "A-renamed"}}},
        )
        assert diff.nodes_added == ["service:B"]
        assert diff.nodes_removed == ["service:A"]
        assert len(diff.edges_added) == 1
        assert diff.edges_added[0] == ("service:B", "endpoint:/api", "calls")
        assert len(diff.edges_removed) == 1
        assert diff.attrs_changed["service:A"]["label"]["old"] == "A"

    def test_diff_serialization_round_trip(self):
        diff = GraphDiff(
            nodes_added=["service:B"],
            nodes_removed=["service:A"],
            edges_added=[("service:B", "endpoint:/api", "calls")],
            edges_removed=[("service:A", "endpoint:/api", "calls")],
            attrs_changed={"endpoint:/api": {"type": {"old": "endpoint", "new": "service"}}},
        )
        data = diff.to_dict()
        restored = GraphDiff.from_dict(data)

        assert restored.nodes_added == diff.nodes_added
        assert restored.nodes_removed == diff.nodes_removed
        assert restored.edges_added == diff.edges_added
        assert restored.edges_removed == diff.edges_removed
        assert restored.attrs_changed == diff.attrs_changed

    def test_diff_edges_serialized_as_lists(self):
        """When serialized to JSON, edge tuples become lists."""
        diff = GraphDiff(
            edges_added=[("a", "b", "calls")],
        )
        data = diff.to_dict()
        # In dict form, edge tuples become lists
        assert data["edges_added"] == [["a", "b", "calls"]]

    def test_diff_from_dict_converts_edge_lists_to_tuples(self):
        """from_dict must convert edge lists back to tuples."""
        raw = {
            "nodes_added": [],
            "nodes_removed": [],
            "edges_added": [["x", "y", "reads"]],
            "edges_removed": [["a", "b", "writes"]],
            "attrs_changed": {},
        }
        diff = GraphDiff.from_dict(raw)
        assert diff.edges_added == [("x", "y", "reads")]
        assert diff.edges_removed == [("a", "b", "writes")]


# ---------------------------------------------------------------------------
# GraphVersion tests
# ---------------------------------------------------------------------------

class TestGraphVersion:
    def test_create_version(self):
        diff = GraphDiff(nodes_added=["service:X"])
        version = GraphVersion(
            version_id=1,
            timestamp="2026-01-15T12:00:00+00:00",
            message="Initial scan",
            diff=diff,
        )
        assert version.version_id == 1
        assert version.message == "Initial scan"
        assert version.diff.nodes_added == ["service:X"]

    def test_version_serialization_round_trip(self):
        diff = GraphDiff(
            nodes_added=["service:X"],
            edges_added=[("service:X", "endpoint:/api", "calls")],
        )
        version = GraphVersion(
            version_id=42,
            timestamp="2026-01-15T12:00:00+00:00",
            message="Added service X",
            diff=diff,
        )
        data = version.to_dict()
        restored = GraphVersion.from_dict(data)

        assert restored.version_id == version.version_id
        assert restored.timestamp == version.timestamp
        assert restored.message == version.message
        assert restored.diff.nodes_added == version.diff.nodes_added
        assert restored.diff.edges_added == version.diff.edges_added

    def test_version_json_round_trip(self):
        """Full JSON serialize/deserialize round-trip."""
        diff = GraphDiff(
            nodes_added=["a"],
            edges_removed=[("x", "y", "calls")],
            attrs_changed={"a": {"label": {"old": "old", "new": "new"}}},
        )
        version = GraphVersion(version_id=1, timestamp="ts", message="msg", diff=diff)
        json_str = json.dumps(version.to_dict())
        restored = GraphVersion.from_dict(json.loads(json_str))
        assert restored.diff.nodes_added == ["a"]
        assert restored.diff.edges_removed == [("x", "y", "calls")]
        assert restored.diff.attrs_changed == {"a": {"label": {"old": "old", "new": "new"}}}


# ---------------------------------------------------------------------------
# compute_diff tests
# ---------------------------------------------------------------------------

class TestComputeDiff:
    def test_empty_to_populated(self, store, sample_graph_data):
        old = GraphData()
        diff = store.compute_diff(old, sample_graph_data)

        assert sorted(diff.nodes_added) == sorted(["service:A", "endpoint:/api"])
        assert diff.nodes_removed == []
        assert len(diff.edges_added) == 1
        assert diff.edges_added[0] == ("service:A", "endpoint:/api", "calls")
        assert diff.edges_removed == []

    def test_populated_to_empty(self, store, sample_graph_data):
        new = GraphData()
        diff = store.compute_diff(sample_graph_data, new)

        assert diff.nodes_added == []
        assert sorted(diff.nodes_removed) == sorted(["service:A", "endpoint:/api"])
        assert diff.edges_added == []
        assert len(diff.edges_removed) == 1
        assert diff.edges_removed[0] == ("service:A", "endpoint:/api", "calls")

    def test_no_changes(self, store, sample_graph_data):
        diff = store.compute_diff(sample_graph_data, sample_graph_data)

        assert diff.nodes_added == []
        assert diff.nodes_removed == []
        assert diff.edges_added == []
        assert diff.edges_removed == []
        assert diff.attrs_changed == {}

    def test_node_added(self, store, sample_graph_data, extended_graph_data):
        diff = store.compute_diff(sample_graph_data, extended_graph_data)

        assert diff.nodes_added == ["table:users"]
        assert diff.nodes_removed == []
        assert len(diff.edges_added) == 1
        assert diff.edges_added[0] == ("endpoint:/api", "table:users", "reads")

    def test_node_removed(self, store, sample_graph_data, extended_graph_data):
        diff = store.compute_diff(extended_graph_data, sample_graph_data)

        assert diff.nodes_added == []
        assert diff.nodes_removed == ["table:users"]
        assert diff.edges_removed == [("endpoint:/api", "table:users", "reads")]

    def test_attrs_changed_type(self, store):
        old = GraphData(
            nodes={
                "service:A": Node(id="service:A", type="service", label="A", file_path="a.py"),
            },
        )
        new = GraphData(
            nodes={
                "service:A": Node(id="service:A", type="endpoint", label="A", file_path="a.py"),
            },
        )
        diff = store.compute_diff(old, new)

        assert "service:A" in diff.attrs_changed
        assert diff.attrs_changed["service:A"]["type"] == {"old": "service", "new": "endpoint"}

    def test_attrs_changed_label(self, store):
        old = GraphData(
            nodes={
                "service:A": Node(id="service:A", type="service", label="A", file_path="a.py"),
            },
        )
        new = GraphData(
            nodes={
                "service:A": Node(id="service:A", type="service", label="A-renamed", file_path="a.py"),
            },
        )
        diff = store.compute_diff(old, new)

        assert "service:A" in diff.attrs_changed
        assert diff.attrs_changed["service:A"]["label"] == {"old": "A", "new": "A-renamed"}

    def test_attrs_changed_file_path(self, store):
        old = GraphData(
            nodes={
                "service:A": Node(id="service:A", type="service", label="A", file_path="a.py"),
            },
        )
        new = GraphData(
            nodes={
                "service:A": Node(id="service:A", type="service", label="A", file_path="b.py"),
            },
        )
        diff = store.compute_diff(old, new)

        assert "service:A" in diff.attrs_changed
        assert diff.attrs_changed["service:A"]["file_path"] == {"old": "a.py", "new": "b.py"}

    def test_attrs_changed_manual_flag(self, store):
        old = GraphData(
            nodes={
                "service:A": Node(id="service:A", type="service", label="A", manual=False),
            },
        )
        new = GraphData(
            nodes={
                "service:A": Node(id="service:A", type="service", label="A", manual=True),
            },
        )
        diff = store.compute_diff(old, new)

        assert "service:A" in diff.attrs_changed
        assert diff.attrs_changed["service:A"]["manual"] == {"old": False, "new": True}

    def test_attrs_changed_multiple_fields(self, store):
        old = GraphData(
            nodes={
                "service:A": Node(id="service:A", type="service", label="A", file_path="a.py"),
            },
        )
        new = GraphData(
            nodes={
                "service:A": Node(id="service:A", type="endpoint", label="B", file_path="a.py"),
            },
        )
        diff = store.compute_diff(old, new)

        assert "service:A" in diff.attrs_changed
        assert "type" in diff.attrs_changed["service:A"]
        assert "label" in diff.attrs_changed["service:A"]
        assert "file_path" not in diff.attrs_changed["service:A"]

    def test_no_attrs_changed_for_unchanged_nodes(self, store):
        """Nodes present in both graphs with identical attrs should not appear."""
        data = GraphData(
            nodes={
                "service:A": Node(id="service:A", type="service", label="A", file_path="a.py"),
            },
        )
        diff = store.compute_diff(data, data)
        assert diff.attrs_changed == {}

    def test_both_empty_graphs(self, store):
        diff = store.compute_diff(GraphData(), GraphData())
        assert diff.nodes_added == []
        assert diff.nodes_removed == []
        assert diff.edges_added == []
        assert diff.edges_removed == []
        assert diff.attrs_changed == {}

    def test_edge_comparison_uses_source_target_type(self, store):
        """Two edges with same source/target but different type are distinct."""
        old = GraphData(
            nodes={
                "a": Node(id="a", type="service", label="a"),
                "b": Node(id="b", type="service", label="b"),
            },
            edges=[Edge(source="a", target="b", type="calls")],
        )
        new = GraphData(
            nodes={
                "a": Node(id="a", type="service", label="a"),
                "b": Node(id="b", type="service", label="b"),
            },
            edges=[Edge(source="a", target="b", type="reads")],
        )
        diff = store.compute_diff(old, new)
        assert diff.edges_added == [("a", "b", "reads")]
        assert diff.edges_removed == [("a", "b", "calls")]


# ---------------------------------------------------------------------------
# add_version tests
# ---------------------------------------------------------------------------

class TestAddVersion:
    def test_add_first_version(self, store, tmp_path, sample_graph_data):
        old = GraphData()
        version = store.add_version(str(tmp_path), old, sample_graph_data, "Initial scan")

        assert version.version_id == 1
        assert version.message == "Initial scan"
        assert len(version.diff.nodes_added) == 2
        assert version.timestamp  # non-empty

    def test_auto_increment_version_id(self, store, tmp_path, sample_graph_data, extended_graph_data):
        old = GraphData()
        v1 = store.add_version(str(tmp_path), old, sample_graph_data, "v1")
        v2 = store.add_version(str(tmp_path), sample_graph_data, extended_graph_data, "v2")

        assert v1.version_id == 1
        assert v2.version_id == 2

    def test_auto_increment_after_reload(self, store, tmp_path, sample_graph_data, extended_graph_data):
        """IDs keep incrementing across store instances."""
        old = GraphData()
        store.add_version(str(tmp_path), old, sample_graph_data, "v1")

        # Create a new store instance
        store2 = VersionStore()
        v2 = store2.add_version(str(tmp_path), sample_graph_data, extended_graph_data, "v2")
        assert v2.version_id == 2

    def test_timestamp_is_utc_iso(self, store, tmp_path, sample_graph_data):
        old = GraphData()
        version = store.add_version(str(tmp_path), old, sample_graph_data, "test")

        # Should contain timezone info (UTC)
        assert "+" in version.timestamp or "Z" in version.timestamp
        # Should be parseable as ISO format
        from datetime import datetime
        datetime.fromisoformat(version.timestamp)

    def test_prunes_old_versions(self, tmp_path, sample_graph_data):
        small_store = VersionStore(max_versions=3)
        data = GraphData()

        for i in range(5):
            new_data = GraphData(
                nodes={f"node:{i}": Node(id=f"node:{i}", type="service", label=str(i))},
            )
            small_store.add_version(str(tmp_path), data, new_data, f"version {i+1}")
            data = new_data

        versions = small_store.load_versions(str(tmp_path))
        assert len(versions) == 3
        # Should keep the most recent 3
        assert versions[0].version_id == 3
        assert versions[-1].version_id == 5

    def test_creates_codegiraffe_directory(self, store, tmp_path, sample_graph_data):
        old = GraphData()
        store.add_version(str(tmp_path), old, sample_graph_data, "test")

        versions_file = tmp_path / ".codegiraffe" / "versions.json"
        assert versions_file.exists()


# ---------------------------------------------------------------------------
# load_versions / save_versions round-trip tests
# ---------------------------------------------------------------------------

class TestLoadSaveVersions:
    def test_round_trip(self, store, tmp_path):
        versions = [
            GraphVersion(
                version_id=1,
                timestamp="2026-01-15T12:00:00+00:00",
                message="First",
                diff=GraphDiff(nodes_added=["a"]),
            ),
            GraphVersion(
                version_id=2,
                timestamp="2026-01-15T13:00:00+00:00",
                message="Second",
                diff=GraphDiff(nodes_removed=["a"], edges_added=[("x", "y", "calls")]),
            ),
        ]
        store.save_versions(str(tmp_path), versions)
        loaded = store.load_versions(str(tmp_path))

        assert len(loaded) == 2
        assert loaded[0].version_id == 1
        assert loaded[0].diff.nodes_added == ["a"]
        assert loaded[1].version_id == 2
        assert loaded[1].diff.edges_added == [("x", "y", "calls")]

    def test_load_empty_when_no_file(self, store, tmp_path):
        loaded = store.load_versions(str(tmp_path))
        assert loaded == []

    def test_load_handles_corrupted_file(self, store, tmp_path):
        versions_path = tmp_path / ".codegiraffe" / "versions.json"
        versions_path.parent.mkdir(parents=True)
        versions_path.write_text("not valid json!!!", encoding="utf-8")

        loaded = store.load_versions(str(tmp_path))
        assert loaded == []

    def test_save_creates_directory(self, store, tmp_path):
        versions = [
            GraphVersion(
                version_id=1,
                timestamp="ts",
                message="test",
                diff=GraphDiff(),
            ),
        ]
        store.save_versions(str(tmp_path), versions)
        assert (tmp_path / ".codegiraffe" / "versions.json").exists()


# ---------------------------------------------------------------------------
# get_version tests
# ---------------------------------------------------------------------------

class TestGetVersion:
    def test_get_existing_version(self, store, tmp_path, sample_graph_data):
        old = GraphData()
        store.add_version(str(tmp_path), old, sample_graph_data, "v1")
        store.add_version(str(tmp_path), sample_graph_data, sample_graph_data, "v2")

        v = store.get_version(str(tmp_path), 1)
        assert v is not None
        assert v.version_id == 1
        assert v.message == "v1"

    def test_get_nonexistent_version(self, store, tmp_path, sample_graph_data):
        old = GraphData()
        store.add_version(str(tmp_path), old, sample_graph_data, "v1")

        v = store.get_version(str(tmp_path), 999)
        assert v is None

    def test_get_version_from_empty_history(self, store, tmp_path):
        v = store.get_version(str(tmp_path), 1)
        assert v is None


# ---------------------------------------------------------------------------
# get_history tests
# ---------------------------------------------------------------------------

class TestGetHistory:
    def test_get_history_returns_summaries(self, store, tmp_path, sample_graph_data, extended_graph_data):
        old = GraphData()
        store.add_version(str(tmp_path), old, sample_graph_data, "Initial scan")
        store.add_version(str(tmp_path), sample_graph_data, extended_graph_data, "Added table")

        history = store.get_history(str(tmp_path))

        assert len(history) == 2
        # Each entry should have summary fields
        h1 = history[0]
        assert h1["version_id"] == 1
        assert h1["message"] == "Initial scan"
        assert "timestamp" in h1
        assert "nodes_added" in h1
        assert "nodes_removed" in h1
        assert "edges_added" in h1
        assert "edges_removed" in h1
        assert "attrs_changed" in h1

    def test_get_history_counts_are_correct(self, store, tmp_path, sample_graph_data, extended_graph_data):
        old = GraphData()
        store.add_version(str(tmp_path), old, sample_graph_data, "v1")
        store.add_version(str(tmp_path), sample_graph_data, extended_graph_data, "v2")

        history = store.get_history(str(tmp_path))

        # v1: empty -> sample (2 nodes added, 1 edge added)
        assert history[0]["nodes_added"] == 2
        assert history[0]["nodes_removed"] == 0
        assert history[0]["edges_added"] == 1
        assert history[0]["edges_removed"] == 0

        # v2: sample -> extended (1 node added, 1 edge added)
        assert history[1]["nodes_added"] == 1
        assert history[1]["nodes_removed"] == 0
        assert history[1]["edges_added"] == 1
        assert history[1]["edges_removed"] == 0

    def test_get_history_empty(self, store, tmp_path):
        history = store.get_history(str(tmp_path))
        assert history == []

    def test_get_history_attrs_changed_count(self, store, tmp_path):
        old = GraphData(
            nodes={"a": Node(id="a", type="service", label="A")},
        )
        new = GraphData(
            nodes={"a": Node(id="a", type="endpoint", label="B")},
        )
        store.add_version(str(tmp_path), old, new, "changed attrs")

        history = store.get_history(str(tmp_path))
        assert history[0]["attrs_changed"] == 1  # 1 node with changed attrs

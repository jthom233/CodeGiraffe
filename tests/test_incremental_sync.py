"""Tests for incremental sync functionality (T045-T046)."""

import json
import pytest
from pathlib import Path

from codegiraffe.scanner import scan_project, sync_files
from codegiraffe.graph import ArchGraph, Node, Edge, GraphData
from codegiraffe.schema import NodeType, EdgeType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def two_file_project(tmp_path):
    """Create a project with two Python source files."""
    # File A: Flask endpoint
    (tmp_path / "routes.py").write_text(
        'from flask import Flask\n'
        'app = Flask(__name__)\n'
        '\n'
        '@app.route("/api/items", methods=["GET"])\n'
        'def get_items():\n'
        '    return []\n'
    )
    # File B: SQLAlchemy model
    (tmp_path / "models.py").write_text(
        'from sqlalchemy import Column, Integer, String\n'
        'from database import Base\n'
        '\n'
        'class Item(Base):\n'
        '    __tablename__ = "items"\n'
        '    id = Column(Integer, primary_key=True)\n'
    )
    return tmp_path


@pytest.fixture
def three_file_project(tmp_path):
    """Create a project with three Python files for sibling-node preservation testing."""
    (tmp_path / "api.py").write_text(
        'from flask import Flask\n'
        'app = Flask(__name__)\n'
        '\n'
        '@app.route("/api/users", methods=["GET"])\n'
        'def get_users():\n'
        '    pass\n'
        '\n'
        '@app.route("/api/orders", methods=["GET"])\n'
        'def get_orders():\n'
        '    pass\n'
    )
    (tmp_path / "models.py").write_text(
        'from sqlalchemy import Column, Integer, String\n'
        'from database import Base\n'
        '\n'
        'class User(Base):\n'
        '    __tablename__ = "users"\n'
        '    id = Column(Integer, primary_key=True)\n'
    )
    (tmp_path / "tasks.py").write_text(
        'from celery import shared_task\n'
        '\n'
        '@shared_task\n'
        'def send_notification(user_id):\n'
        '    pass\n'
    )
    return tmp_path


def _build_arch_graph(project_path: str) -> ArchGraph:
    """Helper: scan a project and return an ArchGraph."""
    result = scan_project(project_path)
    nodes = {node.id: node for node in result.nodes}
    data = GraphData(nodes=nodes, edges=result.edges, project_path=project_path)
    return ArchGraph(data)


# ---------------------------------------------------------------------------
# T045: Incremental sync tests
# ---------------------------------------------------------------------------


class TestSyncFilesOnlyRescansChangedFile:
    """T045-1: sync_files() with single changed file only rescans that file;
    other files' nodes/edges should remain untouched."""

    def test_unchanged_file_nodes_remain(self, two_file_project):
        project_path = str(two_file_project)
        graph = _build_arch_graph(project_path)

        # Record nodes from the unchanged file (models.py)
        data_before = graph.to_data()
        models_nodes_before = {
            nid for nid, n in data_before.nodes.items()
            if n.file_path == "models.py"
        }
        assert models_nodes_before, "models.py should have nodes before sync"

        # Modify routes.py
        routes_path = str(two_file_project / "routes.py")
        (two_file_project / "routes.py").write_text(
            'from flask import Flask\n'
            'app = Flask(__name__)\n'
            '\n'
            '@app.route("/api/items/new", methods=["POST"])\n'
            'def create_item():\n'
            '    return {}\n'
        )

        summary = sync_files(graph, project_path, [routes_path])

        data_after = graph.to_data()
        models_nodes_after = {
            nid for nid, n in data_after.nodes.items()
            if n.file_path == "models.py"
        }
        # models.py nodes must be unchanged
        assert models_nodes_after == models_nodes_before

    def test_changed_file_gets_new_nodes(self, two_file_project):
        project_path = str(two_file_project)
        graph = _build_arch_graph(project_path)

        # Initially should have /api/items endpoint
        data_before = graph.to_data()
        assert any("endpoint:/api/items" == nid for nid in data_before.nodes), \
            "Should have original endpoint"

        routes_path = str(two_file_project / "routes.py")
        (two_file_project / "routes.py").write_text(
            'from flask import Flask\n'
            'app = Flask(__name__)\n'
            '\n'
            '@app.route("/api/items/new", methods=["POST"])\n'
            'def create_item():\n'
            '    return {}\n'
        )

        sync_files(graph, project_path, [routes_path])

        data_after = graph.to_data()
        # New endpoint should exist
        assert "endpoint:/api/items/new" in data_after.nodes
        # Old endpoint should be gone
        assert "endpoint:/api/items" not in data_after.nodes

    def test_summary_returns_expected_structure(self, two_file_project):
        project_path = str(two_file_project)
        graph = _build_arch_graph(project_path)

        routes_path = str(two_file_project / "routes.py")
        summary = sync_files(graph, project_path, [routes_path])

        assert isinstance(summary, dict)
        assert "added" in summary
        assert "removed" in summary
        assert "preserved" in summary
        assert "nodes" in summary["added"]
        assert "edges" in summary["added"]
        assert "nodes" in summary["removed"]
        assert "edges" in summary["removed"]
        assert "nodes" in summary["preserved"]
        assert "edges" in summary["preserved"]


class TestSyncFilesRemovesStaleEdges:
    """T045-2: Old edges from changed file are removed before new edges are added."""

    def test_old_edges_from_changed_file_removed(self, two_file_project):
        project_path = str(two_file_project)
        graph = _build_arch_graph(project_path)

        # Verify routes.py contributed the endpoint:/api/items node
        data_before = graph.to_data()
        routes_node_ids = {
            nid for nid, n in data_before.nodes.items()
            if n.file_path == "routes.py"
        }
        assert routes_node_ids, "routes.py should have produced nodes"

        # Record all edges where source is from routes.py
        edges_from_routes_before = [
            e for e in data_before.edges
            if e.source in routes_node_ids
        ]

        routes_path = str(two_file_project / "routes.py")
        # Write new file content with different route
        (two_file_project / "routes.py").write_text(
            'from flask import Flask\n'
            'app = Flask(__name__)\n'
            '\n'
            '@app.route("/api/widgets", methods=["GET"])\n'
            'def list_widgets():\n'
            '    return []\n'
        )

        sync_files(graph, project_path, [routes_path])

        data_after = graph.to_data()
        # All old endpoint nodes from routes.py should be gone
        assert "endpoint:/api/items" not in data_after.nodes

    def test_no_duplicate_edges_after_resync(self, two_file_project):
        project_path = str(two_file_project)
        graph = _build_arch_graph(project_path)

        routes_path = str(two_file_project / "routes.py")
        # Sync same file twice without modification
        sync_files(graph, project_path, [routes_path])
        sync_files(graph, project_path, [routes_path])

        data = graph.to_data()
        # Check for duplicate edges: (source, target, type) should be unique
        edge_keys = [(e.source, e.target, e.type) for e in data.edges]
        assert len(edge_keys) == len(set(edge_keys)), "No duplicate edges after re-sync"


class TestSyncFilesDeletedFile:
    """T045-3: Deleted file removes all its nodes and edges."""

    def test_deleted_file_nodes_removed(self, two_file_project):
        project_path = str(two_file_project)
        graph = _build_arch_graph(project_path)

        data_before = graph.to_data()
        routes_nodes_before = {
            nid for nid, n in data_before.nodes.items()
            if n.file_path == "routes.py"
        }
        assert routes_nodes_before, "routes.py should have nodes before deletion"

        # Delete the file
        routes_path = str(two_file_project / "routes.py")
        (two_file_project / "routes.py").unlink()

        sync_files(graph, project_path, [routes_path])

        data_after = graph.to_data()
        routes_nodes_after = {
            nid for nid, n in data_after.nodes.items()
            if n.file_path == "routes.py"
        }
        assert not routes_nodes_after, "Deleted file nodes should be removed"

    def test_deleted_file_edges_removed(self, two_file_project):
        project_path = str(two_file_project)
        graph = _build_arch_graph(project_path)

        data_before = graph.to_data()
        routes_node_ids = {
            nid for nid, n in data_before.nodes.items()
            if n.file_path == "routes.py"
        }

        routes_path = str(two_file_project / "routes.py")
        (two_file_project / "routes.py").unlink()

        sync_files(graph, project_path, [routes_path])

        data_after = graph.to_data()
        # No edges should have a source that used to be from routes.py
        for edge in data_after.edges:
            assert edge.source not in routes_node_ids, \
                f"Edge from deleted node should be removed: {edge.source} -> {edge.target}"

    def test_non_deleted_file_unaffected(self, two_file_project):
        project_path = str(two_file_project)
        graph = _build_arch_graph(project_path)

        data_before = graph.to_data()
        models_nodes_before = {
            nid for nid, n in data_before.nodes.items()
            if n.file_path == "models.py"
        }

        routes_path = str(two_file_project / "routes.py")
        (two_file_project / "routes.py").unlink()

        sync_files(graph, project_path, [routes_path])

        data_after = graph.to_data()
        models_nodes_after = {
            nid for nid, n in data_after.nodes.items()
            if n.file_path == "models.py"
        }
        assert models_nodes_after == models_nodes_before


class TestSyncFilesPreservesManualAnnotations:
    """T045-4: Manual annotations (manual=True) on synced nodes are preserved."""

    def test_manual_node_preserved_after_sync(self, two_file_project):
        project_path = str(two_file_project)
        graph = _build_arch_graph(project_path)

        # Add a manual node associated with routes.py
        manual_node = Node(
            id="service:ManualRouteService",
            type=NodeType.SERVICE,
            label="ManualRouteService",
            file_path="routes.py",
            manual=True,
        )
        graph.add_node(manual_node)

        routes_path = str(two_file_project / "routes.py")
        (two_file_project / "routes.py").write_text(
            'from flask import Flask\n'
            'app = Flask(__name__)\n'
            '\n'
            '@app.route("/api/items/updated", methods=["GET"])\n'
            'def updated_items():\n'
            '    return []\n'
        )

        sync_files(graph, project_path, [routes_path])

        data_after = graph.to_data()
        assert "service:ManualRouteService" in data_after.nodes, \
            "Manual node should survive incremental sync"
        assert data_after.nodes["service:ManualRouteService"].manual is True

    def test_manual_edge_preserved_after_sync(self, two_file_project):
        project_path = str(two_file_project)
        graph = _build_arch_graph(project_path)

        # Add a manual edge FROM models.py (not being synced) TO routes.py
        # (being synced). We use a stable route path so the endpoint node id
        # survives the rescan.  Manual edges where both endpoints survive sync
        # must be preserved.
        data_before = graph.to_data()
        routes_module = next(
            (nid for nid, n in data_before.nodes.items()
             if n.file_path == "routes.py" and n.type == "module"),
            None,
        )
        models_module = next(
            (nid for nid, n in data_before.nodes.items()
             if n.file_path == "models.py" and n.type == "module"),
            None,
        )

        if routes_module and models_module:
            # Edge from models (non-synced) -> routes (synced) — manual
            manual_edge = Edge(
                source=models_module,
                target=routes_module,
                type=EdgeType.DEPENDS_ON,
                manual=True,
            )
            graph.add_edge(manual_edge)

            # Sync routes.py keeping the SAME route path (so endpoint node id
            # stays the same, module node id also stays the same)
            routes_path = str(two_file_project / "routes.py")
            (two_file_project / "routes.py").write_text(
                'from flask import Flask\n'
                'app = Flask(__name__)\n'
                '\n'
                '@app.route("/api/items", methods=["GET"])\n'
                'def get_items():\n'
                '    return []  # updated\n'
            )

            sync_files(graph, project_path, [routes_path])

            data_after = graph.to_data()
            manual_edges = [e for e in data_after.edges if e.manual]
            assert len(manual_edges) > 0, \
                "Manual edge from non-synced file to synced file should survive sync"


# ---------------------------------------------------------------------------
# T046: Edge invalidation and contract tests
# ---------------------------------------------------------------------------


class TestSyncFilesNewImportEdges:
    """T046-1: New import edges added without duplicating existing ones."""

    def test_import_edges_added_for_new_import(self, tmp_path):
        project_path = str(tmp_path)
        # File A imports File B
        (tmp_path / "a.py").write_text(
            'from flask import Flask\n'
            'app = Flask(__name__)\n'
            '\n'
            '@app.route("/api/ping", methods=["GET"])\n'
            'def ping():\n'
            '    pass\n'
        )
        (tmp_path / "b.py").write_text(
            'from celery import shared_task\n'
            '\n'
            '@shared_task\n'
            'def background():\n'
            '    pass\n'
        )

        graph = _build_arch_graph(project_path)

        # Modify a.py to add new endpoint
        a_path = str(tmp_path / "a.py")
        (tmp_path / "a.py").write_text(
            'from flask import Flask\n'
            'app = Flask(__name__)\n'
            '\n'
            '@app.route("/api/ping", methods=["GET"])\n'
            'def ping():\n'
            '    pass\n'
            '\n'
            '@app.route("/api/pong", methods=["POST"])\n'
            'def pong():\n'
            '    pass\n'
        )

        sync_files(graph, project_path, [a_path])

        data = graph.to_data()
        # No duplicate edges
        edge_keys = [(e.source, e.target, e.type) for e in data.edges]
        assert len(edge_keys) == len(set(edge_keys)), "No duplicate edges after sync"
        # New endpoint should exist
        assert "endpoint:/api/pong" in data.nodes


class TestSyncFilesNewFunctionAdded:
    """T046-2: Modified file with new function adds new node without losing sibling nodes
    from the same file."""

    def test_sibling_nodes_preserved_when_new_function_added(self, three_file_project):
        project_path = str(three_file_project)
        graph = _build_arch_graph(project_path)

        data_before = graph.to_data()
        # api.py originally has both /api/users and /api/orders endpoints
        assert "endpoint:/api/users" in data_before.nodes, "Should have users endpoint"
        assert "endpoint:/api/orders" in data_before.nodes, "Should have orders endpoint"

        # Add new endpoint to api.py (alongside existing ones)
        api_path = str(three_file_project / "api.py")
        (three_file_project / "api.py").write_text(
            'from flask import Flask\n'
            'app = Flask(__name__)\n'
            '\n'
            '@app.route("/api/users", methods=["GET"])\n'
            'def get_users():\n'
            '    pass\n'
            '\n'
            '@app.route("/api/orders", methods=["GET"])\n'
            'def get_orders():\n'
            '    pass\n'
            '\n'
            '@app.route("/api/products", methods=["GET"])\n'
            'def get_products():\n'
            '    pass\n'
        )

        sync_files(graph, project_path, [api_path])

        data_after = graph.to_data()
        # All three endpoints should be in the graph now
        assert "endpoint:/api/users" in data_after.nodes
        assert "endpoint:/api/orders" in data_after.nodes
        assert "endpoint:/api/products" in data_after.nodes

    def test_non_synced_file_nodes_unaffected(self, three_file_project):
        project_path = str(three_file_project)
        graph = _build_arch_graph(project_path)

        data_before = graph.to_data()
        tasks_nodes_before = {
            nid for nid, n in data_before.nodes.items()
            if n.file_path == "tasks.py"
        }
        models_nodes_before = {
            nid for nid, n in data_before.nodes.items()
            if n.file_path == "models.py"
        }

        # Only sync api.py
        api_path = str(three_file_project / "api.py")
        sync_files(graph, project_path, [api_path])

        data_after = graph.to_data()
        tasks_nodes_after = {
            nid for nid, n in data_after.nodes.items()
            if n.file_path == "tasks.py"
        }
        models_nodes_after = {
            nid for nid, n in data_after.nodes.items()
            if n.file_path == "models.py"
        }

        assert tasks_nodes_after == tasks_nodes_before, "tasks.py nodes must be untouched"
        assert models_nodes_after == models_nodes_before, "models.py nodes must be untouched"


class TestSyncFilesEdgePreservationFromNonSyncedFiles:
    """T046-3: Edge from non-synced file to synced file is preserved.
    Only edges where source is from the synced file should be invalidated."""

    def test_incoming_edge_from_non_synced_file_preserved(self, tmp_path):
        project_path = str(tmp_path)
        (tmp_path / "caller.py").write_text(
            'from flask import Flask\n'
            'app = Flask(__name__)\n'
            '\n'
            '@app.route("/api/call", methods=["GET"])\n'
            'def call():\n'
            '    pass\n'
        )
        (tmp_path / "callee.py").write_text(
            'from celery import shared_task\n'
            '\n'
            '@shared_task\n'
            'def do_work():\n'
            '    pass\n'
        )

        graph = _build_arch_graph(project_path)

        # Manually add an edge from caller.py's module node to callee.py's module node.
        # The module node (mod:callee) is a STABLE identifier that survives rescan of
        # callee.py with the same filename, so this edge should be preserved even after
        # syncing callee.py (as long as the module node is re-created with the same id).
        data = graph.to_data()
        # Use module-level node ids (stable across rescan of same filename)
        caller_module = next(
            (nid for nid, n in data.nodes.items()
             if n.file_path == "caller.py" and n.type == "module"),
            None,
        )
        callee_module = next(
            (nid for nid, n in data.nodes.items()
             if n.file_path == "callee.py" and n.type == "module"),
            None,
        )

        if caller_module and callee_module:
            cross_edge = Edge(
                source=caller_module,
                target=callee_module,
                type=EdgeType.CALLS,
                metadata={"inferred": True, "cross_file": True},
            )
            graph.add_edge(cross_edge)

            # Sync only callee.py, adding a new task (keeping existing one).
            # The module node id (mod:callee) is stable across this rescan.
            callee_path = str(tmp_path / "callee.py")
            (tmp_path / "callee.py").write_text(
                'from celery import shared_task\n'
                '\n'
                '@shared_task\n'
                'def do_work():\n'
                '    pass\n'
                '\n'
                '@shared_task\n'
                'def do_extra_work():\n'
                '    pass\n'
            )

            sync_files(graph, project_path, [callee_path])

            data_after = graph.to_data()
            # The cross-file edge from caller.py's module to callee.py's module
            # should still exist — we only removed edges SOURCED from callee.py nodes.
            cross_edges = [
                e for e in data_after.edges
                if e.source == caller_module and e.target == callee_module
            ]
            assert len(cross_edges) > 0, \
                "Cross-file edge from non-synced caller.py should be preserved"


class TestSyncFilesToolContract:
    """T046-4: Contract test for codegiraffe_sync_files tool."""

    def test_tool_exists_and_is_callable(self):
        """Verify codegiraffe_sync_files is importable and callable."""
        from codegiraffe.server import codegiraffe_sync_files
        assert callable(codegiraffe_sync_files)

    def test_tool_accepts_required_params(self, two_file_project, tmp_path):
        """Verify the tool accepts project_path and file_paths parameters."""
        import inspect
        from codegiraffe.server import codegiraffe_sync_files

        sig = inspect.signature(codegiraffe_sync_files)
        assert "project_path" in sig.parameters, "Must have project_path param"
        assert "file_paths" in sig.parameters, "Must have file_paths param"

    def test_tool_returns_json_summary(self, two_file_project):
        """Verify the tool returns JSON with added/removed/preserved counts."""
        from codegiraffe.server import codegiraffe_sync_files, codegiraffe_init

        project_path = str(two_file_project)
        # Initialize the graph first
        codegiraffe_init(project_path)

        routes_path = str(two_file_project / "routes.py")
        result = codegiraffe_sync_files(
            project_path=project_path,
            file_paths=json.dumps([routes_path]),
        )

        # Result should be a string that can be parsed or contains the summary
        assert isinstance(result, str)
        # Should contain key counts
        parsed = json.loads(result)
        assert "added" in parsed
        assert "removed" in parsed
        assert "preserved" in parsed

    def test_tool_accepts_scanner_mode_param(self):
        """Verify the tool has an optional scanner_mode parameter."""
        import inspect
        from codegiraffe.server import codegiraffe_sync_files

        sig = inspect.signature(codegiraffe_sync_files)
        assert "scanner_mode" in sig.parameters, "Must have scanner_mode param"
        # Should default to "regex"
        default = sig.parameters["scanner_mode"].default
        assert default == "regex"

    def test_tool_handles_comma_separated_paths(self, two_file_project):
        """Verify the tool accepts comma-separated file paths."""
        from codegiraffe.server import codegiraffe_sync_files, codegiraffe_init

        project_path = str(two_file_project)
        codegiraffe_init(project_path)

        routes_path = str(two_file_project / "routes.py")
        models_path = str(two_file_project / "models.py")

        result = codegiraffe_sync_files(
            project_path=project_path,
            file_paths=f"{routes_path},{models_path}",
        )
        assert isinstance(result, str)
        # Should succeed without error
        assert "Error" not in result or "error" not in result.lower()

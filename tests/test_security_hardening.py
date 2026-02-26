"""Tests for US1-US6 security hardening features.

US1 - Dashboard path allowlist / 403 guard
US2 - Scanner symlink boundary enforcement
US3 - Git subprocess timeouts + GitTimeoutError
US4 - XSS escaping in dashboard HTML template
US5 - Parameter bounds (MAX_QUERY_DEPTH, MAX_COUPLING_DEPTH, MAX_BLAST_DEPTH)
US6 - Shared test fixtures (reset_server_state, git helpers)
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# US1 — Dashboard path allowlist
# ---------------------------------------------------------------------------


class TestUS1DashboardPathAllowlist:
    """US1: The dashboard /api/init endpoint must reject paths not in the
    server's _initialized_project_paths allowlist with a 403."""

    def test_initialized_project_paths_exists_in_server_module(self):
        """server module exposes _initialized_project_paths as a set."""
        import codegiraffe.server as srv
        assert hasattr(srv, "_initialized_project_paths"), (
            "_initialized_project_paths must be a module-level set in server.py"
        )
        assert isinstance(srv._initialized_project_paths, set), (
            "_initialized_project_paths must be a set"
        )

    def test_codegiraffe_init_populates_allowlist(self, tmp_path):
        """codegiraffe_init() adds the project path to _initialized_project_paths on success."""
        import codegiraffe.server as srv
        from codegiraffe.server import codegiraffe_init
        from codegiraffe.storage import JSONStorage
        from codegiraffe.versioning import VersionStore
        from codegiraffe.federation import GraphFederation

        # Reset server state
        srv._graph = None
        srv._storage = JSONStorage()
        srv._version_store = VersionStore()
        srv._federation = GraphFederation()
        srv._initialized_project_paths = set()

        py_file = tmp_path / "app.py"
        py_file.write_text("class Foo:\n    pass\n")

        result = codegiraffe_init(str(tmp_path))
        assert "Error" not in result

        assert str(tmp_path) in srv._initialized_project_paths, (
            "codegiraffe_init must add the project_path to _initialized_project_paths"
        )

    def test_dashboard_init_rejects_unknown_path_with_403(self, tmp_path):
        """POST /api/init with a path not in the allowlist returns 403."""
        import codegiraffe.server as srv
        from codegiraffe.dashboard_server import DashboardServer
        from codegiraffe.storage import JSONStorage

        # Reset allowlist to empty
        srv._initialized_project_paths = set()

        # Build a minimal DashboardServer app inline (no real uvicorn needed)
        storage = JSONStorage()
        server = DashboardServer(
            ensure_graph_fn=srv._ensure_graph,
            storage=storage,
            port=0,
        )
        app = server._build_app()

        from starlette.testclient import TestClient
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post(
            "/api/init",
            json={"project_path": "/not/in/allowlist"},
        )
        assert resp.status_code == 403, (
            f"Expected 403 for unknown path, got {resp.status_code}. "
            "Ensure dashboard_server.py guards /api/init against unlisted paths."
        )

    def test_dashboard_init_allows_known_path(self, tmp_path):
        """POST /api/init with a path in the allowlist proceeds normally."""
        import codegiraffe.server as srv
        from codegiraffe.dashboard_server import DashboardServer
        from codegiraffe.storage import JSONStorage
        from codegiraffe.graph import ArchGraph, GraphData

        py_file = tmp_path / "app.py"
        py_file.write_text("class Foo:\n    pass\n")

        # Pre-populate allowlist with our tmp_path
        srv._initialized_project_paths = {str(tmp_path)}

        storage = JSONStorage()
        server = DashboardServer(
            ensure_graph_fn=srv._ensure_graph,
            storage=storage,
            port=0,
        )
        app = server._build_app()

        from starlette.testclient import TestClient
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post(
            "/api/init",
            json={"project_path": str(tmp_path)},
        )
        # Should be 200 (scanned successfully) — not 403
        assert resp.status_code != 403, (
            f"Expected non-403 for allowlisted path, got {resp.status_code}."
        )


# ---------------------------------------------------------------------------
# US2 — Scanner symlink boundary
# ---------------------------------------------------------------------------


class TestUS2SymlinkBoundary:
    """US2: The scanner must skip symlinks that escape the project root."""

    def test_symlink_within_project_is_scanned(self, tmp_path):
        """Symlinks that resolve within the project root are followed normally."""
        from codegiraffe.scanner import scan_project

        # Create a real file inside the project
        real_file = tmp_path / "real_mod.py"
        real_file.write_text("class RealService:\n    pass\n")

        # Create an internal symlink
        link = tmp_path / "alias_mod.py"
        link.symlink_to(real_file)

        result = scan_project(str(tmp_path))
        # Both the real file and the symlink should contribute nodes
        node_ids = [n.id for n in result.nodes]
        assert any("real_mod" in nid or "alias_mod" in nid for nid in node_ids), (
            "Internal symlinks should be followed during scanning"
        )

    def test_symlink_escaping_project_boundary_is_skipped(self, tmp_path):
        """Symlinks that escape the project root are skipped with a warning."""
        from codegiraffe.scanner import scan_project

        # Create a project directory
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Create a file OUTSIDE the project
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        outside_file = outside_dir / "secret.py"
        outside_file.write_text("SECRET_KEY = 'super_secret'\n")

        # Create a symlink inside the project that points outside
        escaping_link = project_dir / "escaped.py"
        escaping_link.symlink_to(outside_file)

        # Also add a normal file so the project isn't empty
        normal_file = project_dir / "normal.py"
        normal_file.write_text("class NormalService:\n    pass\n")

        import warnings
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = scan_project(str(project_dir))

        node_ids = [n.id for n in result.nodes]
        # The escaping symlink's content must NOT appear in results
        assert not any("escaped" in nid for nid in node_ids), (
            "Symlinks escaping the project root must be skipped"
        )
        # Normal file should still be scanned
        assert any("normal" in nid for nid in node_ids), (
            "Normal files must still be scanned after symlink skipping"
        )

    def test_symlink_directory_escaping_project_boundary_is_skipped(self, tmp_path):
        """Directory symlinks that point outside the project are skipped."""
        from codegiraffe.scanner import scan_project

        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Create an external directory with Python files
        external_dir = tmp_path / "external"
        external_dir.mkdir()
        (external_dir / "ext.py").write_text("class ExtService:\n    pass\n")

        # Symlink the external directory into the project
        link_dir = project_dir / "external_link"
        link_dir.symlink_to(external_dir)

        # Normal file
        (project_dir / "local.py").write_text("class LocalService:\n    pass\n")

        result = scan_project(str(project_dir))
        node_ids = [n.id for n in result.nodes]

        assert not any("ext" in nid and "ExtService" in nid for nid in node_ids), (
            "Symlinked external directories must not contribute nodes"
        )
        assert any("local" in nid or "LocalService" in nid for nid in node_ids), (
            "Local files must still be scanned"
        )


# ---------------------------------------------------------------------------
# US3 — Git subprocess timeouts
# ---------------------------------------------------------------------------


class TestUS3GitTimeouts:
    """US3: All git subprocess calls must use a timeout; GitTimeoutError must
    be raised when a command exceeds GIT_COMMAND_TIMEOUT."""

    def test_git_utils_exports_timeout_constant(self):
        """git_utils.py must expose GIT_COMMAND_TIMEOUT as a module-level int."""
        import codegiraffe.git_utils as git_utils

        assert hasattr(git_utils, "GIT_COMMAND_TIMEOUT"), (
            "git_utils must define GIT_COMMAND_TIMEOUT constant"
        )
        assert isinstance(git_utils.GIT_COMMAND_TIMEOUT, int), (
            "GIT_COMMAND_TIMEOUT must be an integer"
        )
        assert git_utils.GIT_COMMAND_TIMEOUT > 0, (
            "GIT_COMMAND_TIMEOUT must be positive"
        )

    def test_git_timeout_error_class_exists(self):
        """git_utils must define GitTimeoutError."""
        import codegiraffe.git_utils as git_utils

        assert hasattr(git_utils, "GitTimeoutError"), (
            "git_utils must define GitTimeoutError"
        )
        # Should be a subclass of GitError
        assert issubclass(git_utils.GitTimeoutError, git_utils.GitError), (
            "GitTimeoutError must subclass GitError"
        )

    def test_is_git_repo_raises_on_timeout(self):
        """is_git_repo raises GitTimeoutError when subprocess.TimeoutExpired fires."""
        import codegiraffe.git_utils as git_utils

        with patch("codegiraffe.git_utils.subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd=["git"], timeout=30)):
            with pytest.raises(git_utils.GitTimeoutError):
                git_utils.is_git_repo("/some/path")

    def test_get_uncommitted_diff_raises_on_timeout(self, tmp_path):
        """get_uncommitted_diff raises GitTimeoutError when subprocess.TimeoutExpired fires."""
        import codegiraffe.git_utils as git_utils

        # First call (is_git_repo check) succeeds; second call times out.
        side_effects = [
            subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            subprocess.TimeoutExpired(cmd=["git"], timeout=30),
        ]
        with patch("codegiraffe.git_utils.subprocess.run", side_effect=side_effects):
            with pytest.raises(git_utils.GitTimeoutError):
                git_utils.get_uncommitted_diff(str(tmp_path))

    def test_get_changed_files_raises_on_timeout(self, tmp_path):
        """get_changed_files raises GitTimeoutError when subprocess.TimeoutExpired fires."""
        import codegiraffe.git_utils as git_utils

        side_effects = [
            subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            subprocess.TimeoutExpired(cmd=["git"], timeout=30),
        ]
        with patch("codegiraffe.git_utils.subprocess.run", side_effect=side_effects):
            with pytest.raises(git_utils.GitTimeoutError):
                git_utils.get_changed_files(str(tmp_path))

    def test_get_commit_file_history_raises_on_timeout(self, tmp_path):
        """get_commit_file_history raises GitTimeoutError when subprocess.TimeoutExpired fires."""
        import codegiraffe.git_utils as git_utils

        side_effects = [
            subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            subprocess.TimeoutExpired(cmd=["git"], timeout=30),
        ]
        with patch("codegiraffe.git_utils.subprocess.run", side_effect=side_effects):
            with pytest.raises(git_utils.GitTimeoutError):
                git_utils.get_commit_file_history(str(tmp_path))

    def test_subprocess_run_called_with_timeout(self, tmp_path):
        """subprocess.run is called with timeout=GIT_COMMAND_TIMEOUT."""
        import codegiraffe.git_utils as git_utils

        calls: list = []

        def fake_run(*args, **kwargs):
            calls.append(kwargs.get("timeout"))
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        with patch("codegiraffe.git_utils.subprocess.run", side_effect=fake_run):
            git_utils.is_git_repo(str(tmp_path))

        assert calls, "subprocess.run was not called"
        assert calls[0] == git_utils.GIT_COMMAND_TIMEOUT, (
            f"Expected timeout={git_utils.GIT_COMMAND_TIMEOUT}, got {calls[0]}"
        )


# ---------------------------------------------------------------------------
# US4 — XSS escaping in dashboard
# ---------------------------------------------------------------------------


class TestUS4DashboardXssEscaping:
    """US4: Graph-derived values inserted into innerHTML in dashboard.py
    must be wrapped in escapeHtml() calls."""

    def test_type_distribution_panel_uses_escape(self):
        """Type distribution panel must call escapeHtml() on the type key."""
        from codegiraffe.dashboard import DASHBOARD_HTML

        # The type distribution HTML generation loop must use escapeHtml on 't'
        # Look for the pattern in the JS: escapeHtml(t) used in dist-row
        assert "escapeHtml(t)" in DASHBOARD_HTML, (
            "Type distribution panel must wrap node type 't' in escapeHtml(t). "
            "Found no escapeHtml(t) in dist-row generation."
        )

    def test_legend_node_type_uses_escape(self):
        """Legend item generation must call escapeHtml() on the type key."""
        from codegiraffe.dashboard import DASHBOARD_HTML

        # The legend item generation loop must use escapeHtml for node type labels
        # The pattern is: escapeHtml(t) used in legend-item generation
        assert "escapeHtml(t)" in DASHBOARD_HTML, (
            "Legend item generation must wrap the type key in escapeHtml(t)."
        )

    def test_xss_payload_not_raw_in_dist_row(self):
        """The dist-row and legend-item template strings must use escapeHtml(t)."""
        from codegiraffe.dashboard import DASHBOARD_HTML

        # Verify that `+ t +` is NOT present (only `+ escapeHtml(t) +` should be)
        # in the innerHTML-building sections for dist-row and legend-item.
        # We look for the specific pattern of the type variable `t` being
        # concatenated into an innerHTML string without escaping.
        # The safe pattern is `escapeHtml(t)` — already tested above.
        # Here we additionally check that none of the dist-row or legend-item
        # template strings use a bare `' + t +` or `' + t <` pattern.
        import re
        # Only search within the JS function bodies for dist-row/legend-item building
        # by looking for the specific unescaped variable concatenation pattern
        # e.g., `</span>' + t + '</div>` or `></span>' + t`
        unsafe_closing = re.compile(r"'>\s*\+\s*t\s*\+\s*'<")
        match = unsafe_closing.search(DASHBOARD_HTML)
        assert match is None, (
            "Found raw '>' + t + '<' concatenation in innerHTML-building code. "
            "Use escapeHtml(t) instead."
        )


# ---------------------------------------------------------------------------
# US5 — Parameter bounds
# ---------------------------------------------------------------------------


class TestUS5ParameterBounds:
    """US5: server.py must define MAX_QUERY_DEPTH, MAX_COUPLING_DEPTH, and
    MAX_BLAST_DEPTH constants, and clamp depth inputs at each tool entry point."""

    def test_max_query_depth_constant_exists(self):
        """server.py must define MAX_QUERY_DEPTH."""
        import codegiraffe.server as srv
        assert hasattr(srv, "MAX_QUERY_DEPTH"), (
            "server.py must define MAX_QUERY_DEPTH constant"
        )
        assert isinstance(srv.MAX_QUERY_DEPTH, int)
        assert srv.MAX_QUERY_DEPTH > 0

    def test_max_coupling_depth_constant_exists(self):
        """server.py must define MAX_COUPLING_DEPTH."""
        import codegiraffe.server as srv
        assert hasattr(srv, "MAX_COUPLING_DEPTH"), (
            "server.py must define MAX_COUPLING_DEPTH constant"
        )
        assert isinstance(srv.MAX_COUPLING_DEPTH, int)
        assert srv.MAX_COUPLING_DEPTH > 0

    def test_max_blast_depth_constant_exists(self):
        """server.py must define MAX_BLAST_DEPTH."""
        import codegiraffe.server as srv
        assert hasattr(srv, "MAX_BLAST_DEPTH"), (
            "server.py must define MAX_BLAST_DEPTH constant"
        )
        assert isinstance(srv.MAX_BLAST_DEPTH, int)
        assert srv.MAX_BLAST_DEPTH > 0

    def test_query_depth_clamped_to_max(self, tmp_path):
        """codegiraffe_query clamps depth to MAX_QUERY_DEPTH."""
        import codegiraffe.server as srv
        from codegiraffe.server import codegiraffe_init, codegiraffe_query
        from codegiraffe.storage import JSONStorage
        from codegiraffe.versioning import VersionStore
        from codegiraffe.federation import GraphFederation

        srv._graph = None
        srv._storage = JSONStorage()
        srv._version_store = VersionStore()
        srv._federation = GraphFederation()
        srv._initialized_project_paths = set()

        (tmp_path / "app.py").write_text("class Foo:\n    pass\n")
        codegiraffe_init(str(tmp_path))

        # Call with huge depth — should not crash and depth should be clamped
        captured_depth: list[int] = []
        original_query_by_node = __import__(
            "codegiraffe.query", fromlist=["query_by_node"]
        ).query_by_node

        def mock_query(graph, node_id, depth):
            captured_depth.append(depth)
            return original_query_by_node(graph, node_id, depth)

        with patch("codegiraffe.server.query_by_node", side_effect=mock_query):
            codegiraffe_query(str(tmp_path), node_id="mod:app", depth=9999)

        if captured_depth:
            assert captured_depth[0] <= srv.MAX_QUERY_DEPTH, (
                f"depth {captured_depth[0]} exceeds MAX_QUERY_DEPTH {srv.MAX_QUERY_DEPTH}"
            )

    def test_coupling_depth_clamped_to_max(self, tmp_path):
        """codegiraffe_file_coupling clamps depth to MAX_COUPLING_DEPTH."""
        import codegiraffe.server as srv
        from codegiraffe.server import codegiraffe_init, codegiraffe_file_coupling
        from codegiraffe.storage import JSONStorage
        from codegiraffe.versioning import VersionStore
        from codegiraffe.federation import GraphFederation

        srv._graph = None
        srv._storage = JSONStorage()
        srv._version_store = VersionStore()
        srv._federation = GraphFederation()
        srv._initialized_project_paths = set()

        (tmp_path / "app.py").write_text("class Foo:\n    pass\n")
        codegiraffe_init(str(tmp_path))

        # Initialize git repo for file_coupling
        _git_env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "t@t.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "t@t.com",
        }
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "checkout", "-b", "main"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path),
                       capture_output=True, env=_git_env)

        captured_depth: list[int] = []
        from codegiraffe import query as _query_mod
        original_file_coupling = _query_mod.file_coupling

        def mock_coupling(graph, project_path, file_path=None, depth=100, **kwargs):
            captured_depth.append(depth)
            return []

        with patch("codegiraffe.server.file_coupling", side_effect=mock_coupling):
            codegiraffe_file_coupling(str(tmp_path), depth=99999)

        if captured_depth:
            assert captured_depth[0] <= srv.MAX_COUPLING_DEPTH, (
                f"depth {captured_depth[0]} exceeds MAX_COUPLING_DEPTH {srv.MAX_COUPLING_DEPTH}"
            )

    def test_blast_depth_clamped_to_max(self, tmp_path):
        """codegiraffe_blast_radius clamps max_depth to MAX_BLAST_DEPTH."""
        import codegiraffe.server as srv
        from codegiraffe.server import codegiraffe_init, codegiraffe_blast_radius
        from codegiraffe.storage import JSONStorage
        from codegiraffe.versioning import VersionStore
        from codegiraffe.federation import GraphFederation

        srv._graph = None
        srv._storage = JSONStorage()
        srv._version_store = VersionStore()
        srv._federation = GraphFederation()
        srv._initialized_project_paths = set()

        (tmp_path / "app.py").write_text("class Foo:\n    pass\n")
        codegiraffe_init(str(tmp_path))

        captured_depth: list = []
        original_blast = __import__(
            "codegiraffe.query", fromlist=["compute_blast_radius"]
        ).compute_blast_radius

        def mock_blast(graph, node_id, include_upstream=False, max_depth=None):
            captured_depth.append(max_depth)
            return original_blast(graph, node_id,
                                  include_upstream=include_upstream,
                                  max_depth=max_depth)

        with patch("codegiraffe.server.compute_blast_radius", side_effect=mock_blast):
            codegiraffe_blast_radius(str(tmp_path), node_id="mod:app", max_depth=9999)

        if captured_depth:
            assert captured_depth[0] <= srv.MAX_BLAST_DEPTH, (
                f"max_depth {captured_depth[0]} exceeds MAX_BLAST_DEPTH {srv.MAX_BLAST_DEPTH}"
            )

    def test_blast_depth_none_is_clamped_to_max(self, tmp_path):
        """codegiraffe_blast_radius with max_depth=None uses MAX_BLAST_DEPTH (not unlimited)."""
        import codegiraffe.server as srv
        from codegiraffe.server import codegiraffe_init, codegiraffe_blast_radius
        from codegiraffe.storage import JSONStorage
        from codegiraffe.versioning import VersionStore
        from codegiraffe.federation import GraphFederation

        srv._graph = None
        srv._storage = JSONStorage()
        srv._version_store = VersionStore()
        srv._federation = GraphFederation()
        srv._initialized_project_paths = set()

        (tmp_path / "app.py").write_text("class Foo:\n    pass\n")
        codegiraffe_init(str(tmp_path))

        captured_depth: list = []
        original_blast = __import__(
            "codegiraffe.query", fromlist=["compute_blast_radius"]
        ).compute_blast_radius

        def mock_blast(graph, node_id, include_upstream=False, max_depth=None):
            captured_depth.append(max_depth)
            return original_blast(graph, node_id,
                                  include_upstream=include_upstream,
                                  max_depth=max_depth)

        # Call with max_depth=None (the default) — must be clamped to MAX_BLAST_DEPTH
        with patch("codegiraffe.server.compute_blast_radius", side_effect=mock_blast):
            codegiraffe_blast_radius(str(tmp_path), node_id="mod:app", max_depth=None)

        assert captured_depth, "compute_blast_radius was not called"
        assert captured_depth[0] is not None, (
            "max_depth=None must be replaced with MAX_BLAST_DEPTH before calling "
            "compute_blast_radius; got None (unbounded traversal allowed)"
        )
        assert captured_depth[0] <= srv.MAX_BLAST_DEPTH, (
            f"max_depth {captured_depth[0]} exceeds MAX_BLAST_DEPTH {srv.MAX_BLAST_DEPTH}"
        )


# ---------------------------------------------------------------------------
# US6 — Fixture consolidation (shared conftest)
# ---------------------------------------------------------------------------


class TestUS6FixtureConsolidation:
    """US6: Shared fixtures (reset_server_state, git helpers) should live in
    tests/conftest.py so individual test files don't duplicate them."""

    def test_reset_server_state_in_conftest(self):
        """conftest.py exports a reset_server_state fixture."""
        import tests.conftest as conftest
        assert hasattr(conftest, "reset_server_state"), (
            "tests/conftest.py must define reset_server_state fixture"
        )

    def test_git_env_in_conftest(self):
        """conftest.py or tests/helpers.py exports _GIT_ENV."""
        try:
            import tests.conftest as conftest
            has_in_conftest = hasattr(conftest, "_GIT_ENV")
        except Exception:
            has_in_conftest = False

        try:
            import tests.helpers as helpers
            has_in_helpers = hasattr(helpers, "_GIT_ENV")
        except Exception:
            has_in_helpers = False

        assert has_in_conftest or has_in_helpers, (
            "_GIT_ENV must be defined in tests/conftest.py or tests/helpers.py"
        )

    def test_git_helper_functions_in_conftest(self):
        """conftest.py or helpers.py exports _git, _init_repo, _commit_file."""
        try:
            import tests.conftest as conftest
            src = conftest
        except Exception:
            src = None

        try:
            import tests.helpers as helpers
            hsrc = helpers
        except Exception:
            hsrc = None

        def has_attr(name):
            return (src and hasattr(src, name)) or (hsrc and hasattr(hsrc, name))

        assert has_attr("_git"), "_git helper must be available in conftest or helpers"
        assert has_attr("_init_repo"), "_init_repo helper must be available"
        assert has_attr("_commit_file"), "_commit_file helper must be available"

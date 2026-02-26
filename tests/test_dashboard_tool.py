"""Tests for the codegiraffe_dashboard MCP tool and DashboardServer.

Verifies:
- project_path validation (graph must exist)
- DashboardServer starts, serves routes, and stops cleanly
- get_or_start_server singleton behavior
- webbrowser.open is called with the correct URL
- returned message contains the URL
- URL encoding of project paths with spaces/special chars
"""

from __future__ import annotations

import socket
import threading
import time
from unittest.mock import MagicMock, patch
from urllib.parse import quote as url_quote

import pytest

import codegiraffe.server as server_module
from codegiraffe.server import codegiraffe_dashboard
# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_dashboard_singleton():
    """Reset the dashboard_server module singleton between tests."""
    import codegiraffe.dashboard_server as ds_module

    original = ds_module._server
    ds_module._server = None
    yield
    # Stop any server started during the test.
    if ds_module._server is not None and ds_module._server.is_running:
        ds_module._server.stop()
    ds_module._server = original


@pytest.fixture()
def initialized_project(tmp_path):
    """Return a project path that has an initialized graph on disk."""
    from codegiraffe.server import codegiraffe_init

    py_file = tmp_path / "app.py"
    py_file.write_text(
        'from flask import Flask\napp = Flask(__name__)\n\n'
        '@app.route("/api/users")\ndef get_users():\n    return []\n'
    )
    result = codegiraffe_init(str(tmp_path))
    assert "Initialized" in result or "nodes" in result.lower()
    return str(tmp_path)


@pytest.fixture()
def uninitialized_project(tmp_path):
    """Return a project path with NO graph data."""
    return str(tmp_path)


# ---------------------------------------------------------------------------
# DashboardServer unit tests
# ---------------------------------------------------------------------------


class TestDashboardServer:
    """Tests for the DashboardServer class."""

    def _make_server(self) -> "DashboardServer":
        from codegiraffe.dashboard_server import DashboardServer, _find_free_port

        def fake_ensure(p):
            raise RuntimeError(f"No graph for {p}")

        class FakeStorage:
            def exists(self, p): return False
            def load(self, p): return None
            def save(self, p, d): pass

        port = _find_free_port(8260, attempts=5)
        return DashboardServer(fake_ensure, FakeStorage(), port=port)

    def test_is_running_false_before_start(self):
        server = self._make_server()
        assert server.is_running is False

    def test_is_running_true_after_start(self):
        server = self._make_server()
        server.start(timeout=5.0)
        try:
            assert server.is_running is True
        finally:
            server.stop()

    def test_is_running_false_after_stop(self):
        server = self._make_server()
        server.start(timeout=5.0)
        server.stop()
        assert server.is_running is False

    def test_port_property(self):
        server = self._make_server()
        assert isinstance(server.port, int)
        assert server.port > 0

    def test_url_encodes_project_path(self):
        server = self._make_server()
        url = server.url("/my project/path")
        assert "%2F" in url or "/my%20project" in url
        assert " " not in url
        assert "/dashboard" in url
        assert f"localhost:{server.port}" in url

    def test_dashboard_route_returns_html(self):
        server = self._make_server()
        server.start(timeout=5.0)
        try:
            import urllib.request
            resp = urllib.request.urlopen(
                f"http://localhost:{server.port}/dashboard", timeout=3
            )
            assert resp.status == 200
            content = resp.read(200).decode()
            assert "<!DOCTYPE html>" in content
        finally:
            server.stop()

    def test_api_graph_missing_param_returns_400(self):
        server = self._make_server()
        server.start(timeout=5.0)
        try:
            import urllib.request
            import urllib.error
            try:
                urllib.request.urlopen(
                    f"http://localhost:{server.port}/api/graph", timeout=3
                )
                assert False, "Expected HTTP error"
            except urllib.error.HTTPError as e:
                assert e.code == 400
        finally:
            server.stop()

    def test_api_graph_uninitialized_returns_404(self):
        server = self._make_server()
        server.start(timeout=5.0)
        try:
            import urllib.request
            import urllib.error
            try:
                urllib.request.urlopen(
                    f"http://localhost:{server.port}/api/graph?project_path=/nonexistent",
                    timeout=3,
                )
                assert False, "Expected HTTP error"
            except urllib.error.HTTPError as e:
                assert e.code == 404
        finally:
            server.stop()

    def test_start_twice_is_idempotent(self):
        """Calling start() on an already-running server is a no-op."""
        server = self._make_server()
        server.start(timeout=5.0)
        try:
            server.start(timeout=5.0)  # should not raise
            assert server.is_running is True
        finally:
            server.stop()

    def test_url_with_empty_project_path(self):
        """url('') still returns a parseable URL with an empty project_path param."""
        server = self._make_server()
        url = server.url("")
        assert url.startswith("http://localhost:")
        assert "/dashboard" in url
        assert "project_path=" in url
        # The value after the = should be empty (no crash, no exception).
        assert url.endswith("project_path=")

    def test_no_stdout_output_during_start_stop(self):
        """Server must never write to stdout — critical for MCP stdio transport."""
        import io
        import sys

        server = self._make_server()
        original_stdout = sys.stdout
        sys.stdout = captured = io.StringIO()
        try:
            server.start(timeout=5.0)
            server.stop()
        finally:
            sys.stdout = original_stdout

        output = captured.getvalue()
        assert output == "", (
            f"DashboardServer wrote to stdout (MCP stdio corruption risk): {output!r}"
        )


# ---------------------------------------------------------------------------
# Port conflict handling
# ---------------------------------------------------------------------------


class TestPortConflict:
    """Tests for _find_free_port and get_or_start_server port-advance logic."""

    def _make_fake_deps(self):
        def fake_ensure(p):
            raise RuntimeError(f"No graph for {p}")

        class FakeStorage:
            def exists(self, p): return False
            def load(self, p): return None
            def save(self, p, d): pass

        return fake_ensure, FakeStorage()

    def test_is_port_free_occupied(self):
        """_is_port_free returns False when a port is already bound."""
        import socket as _socket
        from codegiraffe.dashboard_server import _is_port_free

        sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        occupied = sock.getsockname()[1]
        try:
            assert _is_port_free(occupied) is False
        finally:
            sock.close()

    def test_is_port_free_after_close(self):
        """_is_port_free returns True once the port is released."""
        import socket as _socket
        from codegiraffe.dashboard_server import _is_port_free

        sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        freed_port = sock.getsockname()[1]
        sock.close()
        assert _is_port_free(freed_port) is True

    def test_find_free_port_skips_occupied(self):
        """_find_free_port returns the first port not in use."""
        import socket as _socket
        from codegiraffe.dashboard_server import _find_free_port

        # Bind the first port in range; _find_free_port should return the next one.
        sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 8320))
        sock.listen(1)
        try:
            found = _find_free_port(start=8320, attempts=5)
            assert found != 8320, "Should have skipped the occupied port"
            assert found in range(8321, 8325), f"Expected 8321-8324, got {found}"
        finally:
            sock.close()

    def test_find_free_port_raises_when_all_busy(self):
        """_find_free_port raises OSError when every port in the range is occupied."""
        import socket as _socket
        from codegiraffe.dashboard_server import _find_free_port

        socks = []
        start = 8330
        try:
            for p in range(start, start + 5):
                s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
                s.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
                s.bind(("127.0.0.1", p))
                s.listen(1)
                socks.append(s)
            with pytest.raises(OSError, match="No free port found"):
                _find_free_port(start=start, attempts=5)
        finally:
            for s in socks:
                s.close()

    def test_get_or_start_server_advances_past_blocked_port(self):
        """get_or_start_server automatically tries the next port when preferred is busy."""
        import socket as _socket
        import codegiraffe.dashboard_server as ds_module
        from codegiraffe.dashboard_server import get_or_start_server

        # Occupy the preferred starting port.
        sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 8340))
        sock.listen(1)

        original_server = ds_module._server
        ds_module._server = None
        fake_ensure, storage = self._make_fake_deps()
        try:
            server = get_or_start_server(fake_ensure, storage, port=8340)
            assert server.is_running, "Server must be running after get_or_start_server"
            assert server.port != 8340, (
                f"Expected port != 8340 (that port was occupied), got {server.port}"
            )
        finally:
            if ds_module._server is not None and ds_module._server.is_running:
                ds_module._server.stop()
            ds_module._server = original_server
            sock.close()


# ---------------------------------------------------------------------------
# get_or_start_server singleton behavior
# ---------------------------------------------------------------------------


class TestGetOrStartServer:
    def test_returns_running_server(self):
        from codegiraffe.dashboard_server import get_or_start_server

        def fake_ensure(p):
            raise RuntimeError("no graph")

        class FakeStorage:
            def exists(self, p): return False
            def load(self, p): return None
            def save(self, p, d): pass

        storage = FakeStorage()
        server = get_or_start_server(fake_ensure, storage, port=8261)
        try:
            assert server.is_running is True
        finally:
            server.stop()

    def test_returns_same_singleton_on_second_call(self):
        from codegiraffe.dashboard_server import get_or_start_server

        def fake_ensure(p):
            raise RuntimeError("no graph")

        class FakeStorage:
            def exists(self, p): return False
            def load(self, p): return None
            def save(self, p, d): pass

        storage = FakeStorage()
        s1 = get_or_start_server(fake_ensure, storage, port=8262)
        try:
            s2 = get_or_start_server(fake_ensure, storage, port=8262)
            assert s1 is s2
        finally:
            s1.stop()


# ---------------------------------------------------------------------------
# codegiraffe_dashboard tool — validation
# ---------------------------------------------------------------------------


class TestDashboardToolValidation:
    def test_returns_error_when_graph_not_initialized(self, uninitialized_project):
        """Tool must refuse to start when no graph data exists."""
        result = codegiraffe_dashboard(uninitialized_project, port=19999)
        assert "codegiraffe_init" in result.lower() or "init" in result
        assert uninitialized_project in result

    def test_error_message_is_helpful(self, uninitialized_project):
        """Error message should mention the project path and suggest init."""
        result = codegiraffe_dashboard(uninitialized_project, port=19998)
        assert "No architecture graph" in result or "Run codegiraffe_init" in result


# ---------------------------------------------------------------------------
# codegiraffe_dashboard — browser opening and URL shape
# ---------------------------------------------------------------------------


class TestDashboardToolBrowserOpen:
    def test_browser_open_is_called(self, initialized_project):
        """webbrowser.open must be called with the dashboard URL."""
        with patch("webbrowser.open") as mock_open:
            codegiraffe_dashboard(initialized_project, port=8270)

        mock_open.assert_called_once()
        opened_url: str = mock_open.call_args[0][0]
        assert "/dashboard" in opened_url
        assert "project_path=" in opened_url

    def test_browser_url_contains_project_path(self, initialized_project):
        """Browser URL must include the URL-encoded project_path."""
        with patch("webbrowser.open") as mock_open:
            codegiraffe_dashboard(initialized_project, port=8271)

        opened_url: str = mock_open.call_args[0][0]
        assert url_quote(initialized_project, safe="") in opened_url

    def test_return_message_contains_url(self, initialized_project):
        """Returned message must include the dashboard URL."""
        with patch("webbrowser.open"):
            result = codegiraffe_dashboard(initialized_project, port=8272)

        assert "/dashboard" in result
        assert "localhost:" in result

    def test_return_message_contains_running(self, initialized_project):
        """Returned message must indicate the dashboard is running."""
        with patch("webbrowser.open"):
            result = codegiraffe_dashboard(initialized_project, port=8273)

        assert "running" in result.lower() or "dashboard" in result.lower()


# ---------------------------------------------------------------------------
# codegiraffe_dashboard — URL encoding
# ---------------------------------------------------------------------------


class TestDashboardToolUrlEncoding:
    def test_spaces_in_project_path_are_percent_encoded(self, tmp_path):
        """project_path with spaces must be percent-encoded in the URL."""
        spaced_dir = tmp_path / "my project"
        spaced_dir.mkdir()
        (spaced_dir / "app.py").write_text("def main(): pass\n")

        from codegiraffe.server import codegiraffe_init
        codegiraffe_init(str(spaced_dir))

        with patch("webbrowser.open") as mock_open:
            result = codegiraffe_dashboard(str(spaced_dir), port=8274)

        opened_url: str = mock_open.call_args[0][0]
        assert " " not in opened_url, "Space must be percent-encoded in the URL"
        assert "%20" in opened_url, "Space must appear as %20 in the URL"

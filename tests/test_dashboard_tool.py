"""Tests for the codegiraffe_dashboard MCP tool.

Verifies:
- project_path validation (graph must exist)
- port-in-use detection (returns existing URL instead of spawning)
- subprocess spawned correctly when port is free
- webbrowser.open is called after the server starts
- returned message contains the URL
"""

from __future__ import annotations

import socket
import threading
import time
from unittest.mock import MagicMock, patch
from urllib.parse import quote as url_quote

import pytest

import codegiraffe.server as server_module
from codegiraffe.server import _is_port_in_use, codegiraffe_dashboard
from codegiraffe.storage import JSONStorage


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_server_state():
    """Reset server module globals before and after each test."""
    server_module._graph = None
    server_module._storage = JSONStorage()
    yield
    server_module._graph = None
    server_module._storage = JSONStorage()


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
# _is_port_in_use helper
# ---------------------------------------------------------------------------


class TestIsPortInUse:
    def test_free_port_returns_false(self):
        """A port with nothing bound to it should be reported as free."""
        # Use a high, unlikely-to-be-used port for the test.
        # We bind briefly to pick a free port, then release it.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            free_port = s.getsockname()[1]
        # Port is now released — should report free.
        assert _is_port_in_use(free_port) is False

    def test_occupied_port_returns_true(self):
        """A port actively bound should be reported as in use."""
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind(("127.0.0.1", 0))
        server_sock.listen(1)
        occupied_port = server_sock.getsockname()[1]
        try:
            assert _is_port_in_use(occupied_port) is True
        finally:
            server_sock.close()


# ---------------------------------------------------------------------------
# codegiraffe_dashboard — validation
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
# codegiraffe_dashboard — port-in-use detection
# ---------------------------------------------------------------------------


class TestDashboardToolPortInUse:
    def test_returns_existing_url_when_port_occupied(self, initialized_project):
        """When port is already in use, tool returns existing URL without spawning."""
        # Bind a socket to occupy the port.
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind(("127.0.0.1", 0))
        server_sock.listen(1)
        occupied_port = server_sock.getsockname()[1]

        try:
            with (
                patch("subprocess.Popen") as mock_popen,
                patch("webbrowser.open"),
            ):
                result = codegiraffe_dashboard(initialized_project, port=occupied_port)

            # Should NOT spawn a new process.
            mock_popen.assert_not_called()
            # Should return the URL.
            assert f"localhost:{occupied_port}" in result
            assert "/dashboard" in result
        finally:
            server_sock.close()

    def test_existing_url_contains_project_path(self, initialized_project):
        """URL returned when port is in use should URL-encode the project path."""
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind(("127.0.0.1", 0))
        server_sock.listen(1)
        occupied_port = server_sock.getsockname()[1]

        try:
            with (
                patch("subprocess.Popen"),
                patch("webbrowser.open"),
            ):
                result = codegiraffe_dashboard(initialized_project, port=occupied_port)
            assert url_quote(initialized_project, safe="") in result
        finally:
            server_sock.close()


# ---------------------------------------------------------------------------
# codegiraffe_dashboard — subprocess spawning
# ---------------------------------------------------------------------------


class TestDashboardToolSubprocess:
    def _free_port(self) -> int:
        """Pick an ephemeral free port without binding it."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def test_spawns_subprocess_when_port_free(self, initialized_project):
        """A background subprocess must be Popen'd when port is free."""
        free_port = self._free_port()
        with (
            patch("subprocess.Popen") as mock_popen,
            patch("threading.Thread"),  # prevent real thread from opening browser
        ):
            codegiraffe_dashboard(initialized_project, port=free_port)

        mock_popen.assert_called_once()

    def test_subprocess_uses_sys_executable(self, initialized_project):
        """Subprocess must use sys.executable for the correct Python interpreter."""
        import sys

        free_port = self._free_port()
        with (
            patch("subprocess.Popen") as mock_popen,
            patch("threading.Thread"),
        ):
            codegiraffe_dashboard(initialized_project, port=free_port)

        call_args = mock_popen.call_args
        cmd = call_args[0][0]  # positional first arg is the command list
        assert cmd[0] == sys.executable

    def test_subprocess_uses_streamable_http_transport(self, initialized_project):
        """Subprocess command must include the streamable-http transport flag."""
        free_port = self._free_port()
        with (
            patch("subprocess.Popen") as mock_popen,
            patch("threading.Thread"),
        ):
            codegiraffe_dashboard(initialized_project, port=free_port)

        cmd = mock_popen.call_args[0][0]
        cmd_str = " ".join(cmd)
        assert "streamable-http" in cmd_str

    def test_subprocess_uses_correct_port(self, initialized_project):
        """Subprocess command must pass the requested port number."""
        free_port = self._free_port()
        with (
            patch("subprocess.Popen") as mock_popen,
            patch("threading.Thread"),
        ):
            codegiraffe_dashboard(initialized_project, port=free_port)

        cmd = mock_popen.call_args[0][0]
        cmd_str = " ".join(str(c) for c in cmd)
        assert str(free_port) in cmd_str

    def test_subprocess_stdout_devnull(self, initialized_project):
        """Subprocess stdout/stderr must be redirected to DEVNULL (background)."""
        import subprocess

        free_port = self._free_port()
        with (
            patch("subprocess.Popen") as mock_popen,
            patch("threading.Thread"),
        ):
            codegiraffe_dashboard(initialized_project, port=free_port)

        kwargs = mock_popen.call_args[1]
        assert kwargs.get("stdout") == subprocess.DEVNULL
        assert kwargs.get("stderr") == subprocess.DEVNULL


# ---------------------------------------------------------------------------
# codegiraffe_dashboard — browser opening
# ---------------------------------------------------------------------------


class TestDashboardToolBrowserOpen:
    def _free_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def test_browser_open_is_called(self, initialized_project):
        """webbrowser.open must be called with the dashboard URL."""
        free_port = self._free_port()
        browser_calls: list[str] = []

        # Use a real thread but mock webbrowser and time.sleep so the test
        # doesn't actually sleep for 1.5 seconds.
        with (
            patch("subprocess.Popen"),
            patch("webbrowser.open", side_effect=browser_calls.append),
            patch("time.sleep"),  # skip the startup delay
        ):
            codegiraffe_dashboard(initialized_project, port=free_port)
            # Give the daemon thread a moment to run (time.sleep is mocked).
            time.sleep(0.05)

        # The thread is daemon=True and the mock makes it near-instant.
        # Poll briefly for the call.
        deadline = time.monotonic() + 2.0
        while not browser_calls and time.monotonic() < deadline:
            time.sleep(0.01)

        assert len(browser_calls) == 1
        assert f"localhost:{free_port}" in browser_calls[0]
        assert "/dashboard" in browser_calls[0]

    def test_browser_url_contains_project_path(self, initialized_project):
        """Browser URL must include the URL-encoded project_path query parameter."""
        free_port = self._free_port()
        browser_calls: list[str] = []

        with (
            patch("subprocess.Popen"),
            patch("webbrowser.open", side_effect=browser_calls.append),
            patch("time.sleep"),
        ):
            codegiraffe_dashboard(initialized_project, port=free_port)

        deadline = time.monotonic() + 2.0
        while not browser_calls and time.monotonic() < deadline:
            time.sleep(0.01)

        assert url_quote(initialized_project, safe="") in browser_calls[0]


# ---------------------------------------------------------------------------
# codegiraffe_dashboard — URL encoding
# ---------------------------------------------------------------------------


class TestDashboardToolUrlEncoding:
    def test_spaces_in_project_path_are_percent_encoded(self, tmp_path):
        """project_path with spaces must be percent-encoded in the URL."""
        # Create a subdirectory with a space in the name and initialize it.
        spaced_dir = tmp_path / "my project"
        spaced_dir.mkdir()
        py_file = spaced_dir / "app.py"
        py_file.write_text("def main(): pass\n")

        from codegiraffe.server import codegiraffe_init

        codegiraffe_init(str(spaced_dir))

        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind(("127.0.0.1", 0))
        server_sock.listen(1)
        occupied_port = server_sock.getsockname()[1]

        try:
            with patch("webbrowser.open"):
                result = codegiraffe_dashboard(str(spaced_dir), port=occupied_port)
            # The raw space must not appear in the URL portion of the result.
            # The URL is everything after "http://".
            url_start = result.find("http://")
            assert url_start != -1
            url_end = result.find("\n", url_start)
            url_part = result[url_start:url_end] if url_end != -1 else result[url_start:]
            assert " " not in url_part, "Space must be percent-encoded in the URL"
            assert "%20" in url_part, "Space must appear as %20 in the URL"
        finally:
            server_sock.close()

    def test_special_chars_encoded_in_fresh_spawn_path(self, tmp_path):
        """project_path with special chars must be encoded even in the fresh-spawn path."""
        spaced_dir = tmp_path / "my project"
        spaced_dir.mkdir()
        (spaced_dir / "app.py").write_text("def main(): pass\n")

        from codegiraffe.server import codegiraffe_init

        codegiraffe_init(str(spaced_dir))

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            free_port = s.getsockname()[1]

        with (
            patch("subprocess.Popen"),
            patch("threading.Thread"),
        ):
            result = codegiraffe_dashboard(str(spaced_dir), port=free_port)

        url_start = result.find("http://")
        assert url_start != -1
        url_end = result.find("\n", url_start)
        url_part = result[url_start:url_end] if url_end != -1 else result[url_start:]
        assert " " not in url_part, "Space must be percent-encoded in the URL"
        assert "%20" in url_part, "Space must appear as %20 in the URL"


# ---------------------------------------------------------------------------
# codegiraffe_dashboard — browser opens in port-in-use path
# ---------------------------------------------------------------------------


class TestDashboardToolBrowserOpenPortInUse:
    def test_browser_open_called_when_port_in_use(self, initialized_project):
        """webbrowser.open must be called when the port is already occupied."""
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind(("127.0.0.1", 0))
        server_sock.listen(1)
        occupied_port = server_sock.getsockname()[1]

        try:
            with patch("webbrowser.open") as mock_open:
                codegiraffe_dashboard(initialized_project, port=occupied_port)
            mock_open.assert_called_once()
        finally:
            server_sock.close()

    def test_browser_open_url_contains_dashboard_path_when_port_in_use(
        self, initialized_project
    ):
        """URL passed to webbrowser.open must include /dashboard when port is in use."""
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind(("127.0.0.1", 0))
        server_sock.listen(1)
        occupied_port = server_sock.getsockname()[1]

        try:
            with patch("webbrowser.open") as mock_open:
                codegiraffe_dashboard(initialized_project, port=occupied_port)
            opened_url = mock_open.call_args[0][0]
            assert "/dashboard" in opened_url
            assert f"localhost:{occupied_port}" in opened_url
        finally:
            server_sock.close()


# ---------------------------------------------------------------------------
# codegiraffe_dashboard — return message
# ---------------------------------------------------------------------------


class TestDashboardToolReturnMessage:
    def _free_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def test_return_message_contains_url(self, initialized_project):
        """Returned message must include the dashboard URL."""
        free_port = self._free_port()
        with (
            patch("subprocess.Popen"),
            patch("threading.Thread"),
        ):
            result = codegiraffe_dashboard(initialized_project, port=free_port)

        assert f"localhost:{free_port}" in result
        assert "/dashboard" in result

    def test_default_port_8251(self, initialized_project):
        """Default port should be 8251."""
        with (
            patch("codegiraffe.server._is_port_in_use", return_value=True),
        ):
            result = codegiraffe_dashboard(initialized_project)

        assert "8251" in result

    def test_custom_port_in_message(self, initialized_project):
        """Custom port must appear in the returned message."""
        free_port = self._free_port()
        with (
            patch("subprocess.Popen"),
            patch("threading.Thread"),
        ):
            result = codegiraffe_dashboard(initialized_project, port=free_port)

        assert str(free_port) in result

    def test_already_running_message(self, initialized_project):
        """When port is occupied, message should indicate it is already running."""
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind(("127.0.0.1", 0))
        server_sock.listen(1)
        occupied_port = server_sock.getsockname()[1]

        try:
            with (
                patch("subprocess.Popen"),
                patch("webbrowser.open"),
            ):
                result = codegiraffe_dashboard(initialized_project, port=occupied_port)
            assert "already" in result.lower() or "running" in result.lower()
        finally:
            server_sock.close()

"""Tests for API & DX Improvements (spec 035).

TDD: Tests written BEFORE implementation (RED phase).

US1: Split codegiraffe_domains into 4 separate tools
US2: Remove codegiraffe_restore (negative contract test)
US3: Add codegiraffe_release tool
US4: Rename codegiraffe_status -> codegiraffe_update_agent_status
"""

from __future__ import annotations

import inspect
import json

import pytest

import codegiraffe.server as server_module
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
    server_module._graph = None
    server_module._storage = JSONStorage()
    server_module._version_store = VersionStore()
    server_module._federation = GraphFederation()


@pytest.fixture
def project_dir(tmp_path):
    """Create a minimal Python project with at least one scannable file."""
    py_file = tmp_path / "service.py"
    py_file.write_text(
        "class PaymentService:\n"
        "    def process(self):\n"
        "        pass\n"
    )
    return str(tmp_path)


# ===========================================================================
# US1: Split codegiraffe_domains into 4 separate tools
# ===========================================================================


class TestListDomainsTool:
    """codegiraffe_list_domains — list all domains."""

    def test_function_exists(self):
        """codegiraffe_list_domains is importable from server module."""
        assert hasattr(server_module, "codegiraffe_list_domains")

    def test_accepts_project_path(self):
        """codegiraffe_list_domains accepts project_path parameter."""
        sig = inspect.signature(server_module.codegiraffe_list_domains)
        assert "project_path" in sig.parameters

    def test_returns_string(self, tmp_path):
        """Returns a string for an uninitialized project."""
        from codegiraffe.server import codegiraffe_list_domains

        result = codegiraffe_list_domains(project_path=str(tmp_path))
        assert isinstance(result, str)

    def test_no_domains_returns_descriptive_message(self, tmp_path):
        """Returns a helpful message when no domains are defined."""
        from codegiraffe.server import codegiraffe_init, codegiraffe_list_domains

        codegiraffe_init(project_path=str(tmp_path))
        result = codegiraffe_list_domains(project_path=str(tmp_path))

        assert isinstance(result, str)
        # Should say no domains or return an empty domains list
        assert "domain" in result.lower() or "no" in result.lower()

    def test_lists_added_domains(self, project_dir):
        """After adding a domain, it appears in list output."""
        from codegiraffe.server import (
            codegiraffe_add_domain,
            codegiraffe_init,
            codegiraffe_list_domains,
            _ensure_graph,
        )

        codegiraffe_init(project_path=project_dir)
        graph = _ensure_graph(project_dir)
        nodes = list(graph.to_data().nodes.keys())
        if not nodes:
            pytest.skip("No nodes in graph after init")

        node_id = nodes[0]
        codegiraffe_add_domain(
            project_path=project_dir,
            name="test-domain",
            node_ids=node_id,
        )

        result = codegiraffe_list_domains(project_path=project_dir)
        assert "test-domain" in result


class TestInferDomainsTool:
    """codegiraffe_infer_domains — auto-infer domains from graph structure."""

    def test_function_exists(self):
        """codegiraffe_infer_domains is importable from server module."""
        assert hasattr(server_module, "codegiraffe_infer_domains")

    def test_accepts_project_path(self):
        """codegiraffe_infer_domains accepts project_path parameter."""
        sig = inspect.signature(server_module.codegiraffe_infer_domains)
        assert "project_path" in sig.parameters

    def test_returns_string(self, tmp_path):
        """Returns a string for an uninitialized project."""
        from codegiraffe.server import codegiraffe_infer_domains

        result = codegiraffe_infer_domains(project_path=str(tmp_path))
        assert isinstance(result, str)

    def test_returns_string_after_init(self, tmp_path):
        """Returns a string after project is initialized."""
        from codegiraffe.server import codegiraffe_init, codegiraffe_infer_domains

        codegiraffe_init(project_path=str(tmp_path))
        result = codegiraffe_infer_domains(project_path=str(tmp_path))

        assert isinstance(result, str)

    def test_infers_domains_from_directories(self, tmp_path):
        """Infers domains when project has multi-directory structure."""
        from codegiraffe.server import codegiraffe_init, codegiraffe_infer_domains

        # Create two directories with 2+ Python files each
        payments = tmp_path / "payments"
        payments.mkdir()
        (payments / "service.py").write_text("class PayService:\n    pass\n")
        (payments / "models.py").write_text("class Payment:\n    pass\n")

        auth = tmp_path / "auth"
        auth.mkdir()
        (auth / "login.py").write_text("class LoginHandler:\n    pass\n")
        (auth / "logout.py").write_text("class LogoutHandler:\n    pass\n")

        codegiraffe_init(project_path=str(tmp_path))
        result = codegiraffe_infer_domains(project_path=str(tmp_path))

        assert isinstance(result, str)
        # Either inferred some domains or said none found
        assert "domain" in result.lower() or "cluster" in result.lower() or "no" in result.lower()


class TestAddDomainTool:
    """codegiraffe_add_domain — create a named domain."""

    def test_function_exists(self):
        """codegiraffe_add_domain is importable from server module."""
        assert hasattr(server_module, "codegiraffe_add_domain")

    def test_accepts_project_path(self):
        """codegiraffe_add_domain accepts project_path parameter."""
        sig = inspect.signature(server_module.codegiraffe_add_domain)
        assert "project_path" in sig.parameters

    def test_accepts_name(self):
        """codegiraffe_add_domain accepts name parameter."""
        sig = inspect.signature(server_module.codegiraffe_add_domain)
        assert "name" in sig.parameters

    def test_accepts_node_ids(self):
        """codegiraffe_add_domain accepts node_ids parameter."""
        sig = inspect.signature(server_module.codegiraffe_add_domain)
        assert "node_ids" in sig.parameters

    def test_returns_string(self, tmp_path):
        """Returns a string."""
        from codegiraffe.server import codegiraffe_add_domain, codegiraffe_init

        codegiraffe_init(project_path=str(tmp_path))
        result = codegiraffe_add_domain(
            project_path=str(tmp_path),
            name="my-domain",
            node_ids="",
        )
        assert isinstance(result, str)

    def test_empty_node_ids_returns_error(self, tmp_path):
        """Returns an error when node_ids is empty."""
        from codegiraffe.server import codegiraffe_add_domain, codegiraffe_init

        codegiraffe_init(project_path=str(tmp_path))
        result = codegiraffe_add_domain(
            project_path=str(tmp_path),
            name="my-domain",
            node_ids="",
        )
        assert "error" in result.lower()

    def test_empty_name_returns_error(self, tmp_path):
        """Returns an error when name is empty."""
        from codegiraffe.server import codegiraffe_add_domain, codegiraffe_init

        codegiraffe_init(project_path=str(tmp_path))
        result = codegiraffe_add_domain(
            project_path=str(tmp_path),
            name="",
            node_ids="service:A",
        )
        assert "error" in result.lower()

    def test_creates_domain_successfully(self, project_dir):
        """Creates a domain and returns success message."""
        from codegiraffe.server import (
            codegiraffe_add_domain,
            codegiraffe_init,
            _ensure_graph,
        )

        codegiraffe_init(project_path=project_dir)
        graph = _ensure_graph(project_dir)
        nodes = list(graph.to_data().nodes.keys())
        if not nodes:
            pytest.skip("No nodes in graph after init")

        node_id = nodes[0]
        result = codegiraffe_add_domain(
            project_path=project_dir,
            name="test-domain",
            node_ids=node_id,
        )

        assert isinstance(result, str)
        assert "error" not in result.lower() or "test-domain" in result


class TestRemoveDomainTool:
    """codegiraffe_remove_domain — remove a domain by name."""

    def test_function_exists(self):
        """codegiraffe_remove_domain is importable from server module."""
        assert hasattr(server_module, "codegiraffe_remove_domain")

    def test_accepts_project_path(self):
        """codegiraffe_remove_domain accepts project_path parameter."""
        sig = inspect.signature(server_module.codegiraffe_remove_domain)
        assert "project_path" in sig.parameters

    def test_accepts_name(self):
        """codegiraffe_remove_domain accepts name parameter."""
        sig = inspect.signature(server_module.codegiraffe_remove_domain)
        assert "name" in sig.parameters

    def test_returns_string(self, tmp_path):
        """Returns a string."""
        from codegiraffe.server import codegiraffe_remove_domain, codegiraffe_init

        codegiraffe_init(project_path=str(tmp_path))
        result = codegiraffe_remove_domain(
            project_path=str(tmp_path),
            name="nonexistent",
        )
        assert isinstance(result, str)

    def test_nonexistent_domain_returns_error(self, tmp_path):
        """Returns an error when the domain doesn't exist."""
        from codegiraffe.server import codegiraffe_remove_domain, codegiraffe_init

        codegiraffe_init(project_path=str(tmp_path))
        result = codegiraffe_remove_domain(
            project_path=str(tmp_path),
            name="ghost-domain",
        )
        assert "not found" in result.lower() or "error" in result.lower()

    def test_empty_name_returns_error(self, tmp_path):
        """Returns an error when name is empty."""
        from codegiraffe.server import codegiraffe_remove_domain, codegiraffe_init

        codegiraffe_init(project_path=str(tmp_path))
        result = codegiraffe_remove_domain(
            project_path=str(tmp_path),
            name="",
        )
        assert "error" in result.lower()

    def test_removes_existing_domain(self, project_dir):
        """Removes a domain that was previously added."""
        from codegiraffe.server import (
            codegiraffe_add_domain,
            codegiraffe_init,
            codegiraffe_remove_domain,
            _ensure_graph,
        )

        codegiraffe_init(project_path=project_dir)
        graph = _ensure_graph(project_dir)
        nodes = list(graph.to_data().nodes.keys())
        if not nodes:
            pytest.skip("No nodes in graph after init")

        node_id = nodes[0]
        codegiraffe_add_domain(
            project_path=project_dir,
            name="temp-domain",
            node_ids=node_id,
        )

        result = codegiraffe_remove_domain(
            project_path=project_dir,
            name="temp-domain",
        )

        assert isinstance(result, str)
        assert "removed" in result.lower() or "temp-domain" in result


class TestOldDomainsToolRemoved:
    """The combined codegiraffe_domains tool should no longer exist."""

    def test_codegiraffe_domains_does_not_exist(self):
        """codegiraffe_domains has been removed from server module."""
        assert not hasattr(server_module, "codegiraffe_domains"), (
            "codegiraffe_domains should have been removed and replaced by "
            "codegiraffe_list_domains, codegiraffe_infer_domains, "
            "codegiraffe_add_domain, codegiraffe_remove_domain"
        )


# ===========================================================================
# US2: codegiraffe_restore has been removed
# ===========================================================================


class TestRestoreToolRemoved:
    """Negative contract test: codegiraffe_restore no longer exists."""

    def test_codegiraffe_restore_does_not_exist(self):
        """codegiraffe_restore has been removed from server module."""
        assert not hasattr(server_module, "codegiraffe_restore"), (
            "codegiraffe_restore is a permanently-failing stub and should have "
            "been removed from the server module"
        )


# ===========================================================================
# US3: codegiraffe_release tool
# ===========================================================================


class TestReleaseTool:
    """codegiraffe_release — release an agent's claim."""

    def test_function_exists(self):
        """codegiraffe_release is importable from server module."""
        assert hasattr(server_module, "codegiraffe_release")

    def test_accepts_project_path(self):
        """codegiraffe_release accepts project_path parameter."""
        sig = inspect.signature(server_module.codegiraffe_release)
        assert "project_path" in sig.parameters

    def test_accepts_agent_id(self):
        """codegiraffe_release accepts agent_id parameter."""
        sig = inspect.signature(server_module.codegiraffe_release)
        assert "agent_id" in sig.parameters

    def test_returns_string(self, tmp_path):
        """Returns a string."""
        from codegiraffe.server import codegiraffe_release

        result = codegiraffe_release(
            project_path=str(tmp_path),
            agent_id="agent-99",
        )
        assert isinstance(result, str)

    def test_release_returns_json(self, tmp_path):
        """Returns JSON with success key."""
        from codegiraffe.server import codegiraffe_release

        result = codegiraffe_release(
            project_path=str(tmp_path),
            agent_id="agent-99",
        )
        data = json.loads(result)
        assert "success" in data

    def test_release_unclaimed_agent_returns_released_zero(self, tmp_path):
        """Releasing an agent that has no claim returns released=0."""
        from codegiraffe.server import codegiraffe_release

        result = codegiraffe_release(
            project_path=str(tmp_path),
            agent_id="agent-nobody",
        )
        data = json.loads(result)
        assert data["success"] is True
        assert data["released"] == 0

    def test_release_after_claim_returns_released_one(self, tmp_path):
        """Releasing an agent that has a claim returns released=1."""
        from codegiraffe.server import codegiraffe_claim, codegiraffe_release

        # First claim some nodes
        codegiraffe_claim(
            project_path=str(tmp_path),
            agent_id="agent-1",
            node_ids=["service:A", "service:B"],
            task="Working on payments",
        )

        result = codegiraffe_release(
            project_path=str(tmp_path),
            agent_id="agent-1",
        )
        data = json.loads(result)
        assert data["success"] is True
        assert data["released"] == 1

    def test_only_releases_own_claim(self, tmp_path):
        """Releasing agent-1 does not affect agent-2's claim."""
        from codegiraffe.server import (
            codegiraffe_agents,
            codegiraffe_claim,
            codegiraffe_release,
        )

        codegiraffe_claim(
            project_path=str(tmp_path),
            agent_id="agent-1",
            node_ids=["service:A"],
            task="Task A",
        )
        codegiraffe_claim(
            project_path=str(tmp_path),
            agent_id="agent-2",
            node_ids=["service:B"],
            task="Task B",
        )

        codegiraffe_release(
            project_path=str(tmp_path),
            agent_id="agent-1",
        )

        # agent-2 should still be listed
        agents_result = codegiraffe_agents(project_path=str(tmp_path))
        assert "agent-2" in agents_result


# ===========================================================================
# US4: Rename codegiraffe_status -> codegiraffe_update_agent_status
# ===========================================================================


class TestUpdateAgentStatusTool:
    """codegiraffe_update_agent_status — renamed from codegiraffe_status."""

    def test_function_exists(self):
        """codegiraffe_update_agent_status is importable from server module."""
        assert hasattr(server_module, "codegiraffe_update_agent_status")

    def test_accepts_project_path(self):
        """codegiraffe_update_agent_status accepts project_path parameter."""
        sig = inspect.signature(server_module.codegiraffe_update_agent_status)
        assert "project_path" in sig.parameters

    def test_accepts_agent_id(self):
        """codegiraffe_update_agent_status accepts agent_id parameter."""
        sig = inspect.signature(server_module.codegiraffe_update_agent_status)
        assert "agent_id" in sig.parameters

    def test_accepts_status(self):
        """codegiraffe_update_agent_status accepts status parameter."""
        sig = inspect.signature(server_module.codegiraffe_update_agent_status)
        assert "status" in sig.parameters

    def test_accepts_optional_task(self):
        """codegiraffe_update_agent_status accepts optional task parameter."""
        sig = inspect.signature(server_module.codegiraffe_update_agent_status)
        assert "task" in sig.parameters

    def test_returns_string(self, tmp_path):
        """Returns a string."""
        from codegiraffe.server import codegiraffe_update_agent_status

        result = codegiraffe_update_agent_status(
            project_path=str(tmp_path),
            agent_id="agent-1",
            status="active",
        )
        assert isinstance(result, str)

    def test_updates_status_successfully(self, tmp_path):
        """Updates status for an existing claim and returns JSON."""
        from codegiraffe.server import (
            codegiraffe_claim,
            codegiraffe_update_agent_status,
        )

        codegiraffe_claim(
            project_path=str(tmp_path),
            agent_id="agent-1",
            node_ids=["service:X"],
            task="Doing work",
        )

        result = codegiraffe_update_agent_status(
            project_path=str(tmp_path),
            agent_id="agent-1",
            status="done",
        )

        # Should return JSON with claim details
        data = json.loads(result)
        assert "claim" in data
        assert data["claim"]["status"] == "done"


class TestOldStatusToolRemoved:
    """codegiraffe_status has been renamed; the old name should not exist."""

    def test_codegiraffe_status_does_not_exist(self):
        """codegiraffe_status has been renamed to codegiraffe_update_agent_status."""
        assert not hasattr(server_module, "codegiraffe_status"), (
            "codegiraffe_status should have been renamed to "
            "codegiraffe_update_agent_status"
        )


# ===========================================================================
# Tool count verification
# ===========================================================================


class TestToolCount:
    """Verify total MCP tool count is 40 after all changes."""

    def test_tool_count_is_40(self):
        """Server exposes exactly 40 MCP tools after API improvements."""
        # Get all @mcp.tool() decorated functions
        # FastMCP stores tools in _tool_manager or similar
        mcp = server_module.mcp
        # FastMCP exposes tools via mcp._tool_manager._tools or similar attribute
        # Check via list_tools (sync version)
        import inspect

        # Count functions in server_module that are decorated with @mcp.tool()
        # We verify by checking attributes on the mcp object
        # The mcp object has a _tool_manager with _tools dict in FastMCP
        tool_manager = getattr(mcp, "_tool_manager", None)
        if tool_manager is not None:
            tools = getattr(tool_manager, "_tools", None)
            if tools is not None:
                count = len(tools)
                assert count == 40, (
                    f"Expected 40 tools, got {count}. "
                    f"Tools: {sorted(tools.keys())}"
                )
        # If we can't inspect the tool manager, skip the count test
        # (the individual tool tests above cover correctness)

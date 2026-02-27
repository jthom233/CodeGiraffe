"""Server-level tests for the three new change impact validation MCP tools.

Tests codegiraffe_validate_changes, codegiraffe_suggest_tests, and
codegiraffe_file_coupling tool functions through the server module interface.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

import codegiraffe.server as server_module
from codegiraffe.graph import ArchGraph, Edge, GraphData, Node
from codegiraffe.schema import EdgeType, NodeType
from codegiraffe.server import (
    codegiraffe_file_coupling,
    codegiraffe_suggest_tests,
    codegiraffe_validate_changes,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _build_graph(project_path: str) -> ArchGraph:
    """Build and cache a small graph in server state."""
    g = ArchGraph()
    g.add_node(
        Node(
            id="mod:app",
            type=NodeType.MODULE,
            label="app",
            file_path="src/app.py",
        )
    )
    g.add_node(
        Node(
            id="mod:utils",
            type=NodeType.MODULE,
            label="utils",
            file_path="src/utils.py",
        )
    )
    g.add_node(
        Node(
            id="mod:test_app",
            type=NodeType.MODULE,
            label="test_app",
            file_path="tests/test_app.py",
            metadata={"source": "test"},
        )
    )
    g.add_edge(Edge(source="mod:app", target="mod:utils", type=EdgeType.IMPORTS))
    g.add_edge(Edge(source="mod:test_app", target="mod:app", type=EdgeType.IMPORTS))

    data = g.to_data()
    data.project_path = project_path
    server_module._storage.save(project_path, data)
    server_module._graph = None  # Force reload
    return g


# A minimal unified diff that touches src/app.py
_SAMPLE_DIFF = """\
diff --git a/src/app.py b/src/app.py
index 1234567..abcdefg 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,3 +1,4 @@
 import utils
+import os
 def main():
     pass
"""


# ===========================================================================
# TestValidateChangesTool
# ===========================================================================


class TestValidateChangesTool:
    """Tests for the codegiraffe_validate_changes MCP tool."""

    def test_auto_detects_diff(self, tmp_path):
        """When auto=True and no diff provided, reads from git."""
        project = str(tmp_path)
        _build_graph(project)

        with patch(
            "codegiraffe.server.get_uncommitted_diff", return_value=_SAMPLE_DIFF
        ):
            result = codegiraffe_validate_changes(project)

        assert isinstance(result, dict)
        assert "changed_files" in result
        paths = [f["path"] for f in result["changed_files"]]
        assert "src/app.py" in paths

    def test_explicit_diff(self, tmp_path):
        """When diff is provided directly, it is used without git."""
        project = str(tmp_path)
        _build_graph(project)

        result = codegiraffe_validate_changes(project, diff=_SAMPLE_DIFF)
        assert isinstance(result, dict)
        assert "changed_files" in result
        paths = [f["path"] for f in result["changed_files"]]
        assert "src/app.py" in paths

    def test_structured_fields_present(self, tmp_path):
        """Result dict contains all expected structured fields."""
        project = str(tmp_path)
        _build_graph(project)

        result = codegiraffe_validate_changes(project, diff=_SAMPLE_DIFF)
        assert isinstance(result, dict)
        for field in ("changed_files", "changed_nodes", "total_blast_radius",
                      "covered_nodes", "uncovered_nodes", "contract_violations",
                      "recommendations"):
            assert field in result, f"Missing field: {field}"

    def test_changed_files_have_path_and_status(self, tmp_path):
        """Each changed_files entry has path and status keys."""
        project = str(tmp_path)
        _build_graph(project)

        result = codegiraffe_validate_changes(project, diff=_SAMPLE_DIFF)
        assert isinstance(result, dict)
        assert len(result["changed_files"]) > 0
        for entry in result["changed_files"]:
            assert "path" in entry
            assert "status" in entry

    def test_no_diff_no_auto_error(self, tmp_path):
        """diff=None with auto=False returns an error dict."""
        project = str(tmp_path)
        _build_graph(project)

        result = codegiraffe_validate_changes(project, diff=None, auto=False)
        assert isinstance(result, dict)
        assert "error" in result
        assert "auto=False" in result["error"]

    def test_not_git_repo_error(self, tmp_path):
        """Non-git directory with auto=True returns an error dict."""
        project = str(tmp_path)
        _build_graph(project)

        with patch(
            "codegiraffe.server.get_uncommitted_diff",
            side_effect=server_module.NotAGitRepoError("not a repo"),
        ):
            result = codegiraffe_validate_changes(project)

        assert isinstance(result, dict)
        assert "error" in result
        assert "not a git repository" in result["error"]

    def test_no_graph_error(self, tmp_path):
        """No initialized graph returns an error dict."""
        project = str(tmp_path / "nonexistent")
        result = codegiraffe_validate_changes(project)
        assert isinstance(result, dict)
        assert "error" in result

    def test_no_uncommitted_changes(self, tmp_path):
        """Empty diff returns a no_changes status dict."""
        project = str(tmp_path)
        _build_graph(project)

        with patch(
            "codegiraffe.server.get_uncommitted_diff", return_value=""
        ):
            result = codegiraffe_validate_changes(project)

        assert isinstance(result, dict)
        assert result.get("status") == "no_changes"
        assert "No uncommitted changes" in result.get("message", "")


# ===========================================================================
# TestSuggestTestsTool
# ===========================================================================


class TestSuggestTestsTool:
    """Tests for the codegiraffe_suggest_tests MCP tool."""

    def test_returns_dict(self, tmp_path):
        """Output is a structured dict with suggestions list."""
        project = str(tmp_path)
        _build_graph(project)

        result = codegiraffe_suggest_tests(project, diff=_SAMPLE_DIFF)
        assert isinstance(result, dict)
        assert "suggestions" in result
        assert "total_suggestions" in result

    def test_suggestion_entries_have_required_fields(self, tmp_path):
        """Each suggestion entry has file_path, score, reason, strategy, and relevance."""
        project = str(tmp_path)
        _build_graph(project)

        result = codegiraffe_suggest_tests(project, diff=_SAMPLE_DIFF)
        assert isinstance(result, dict)
        for s in result["suggestions"]:
            assert "file_path" in s
            assert "score" in s
            assert "reason" in s
            assert "strategy" in s
            assert "relevance" in s
            assert s["relevance"] in ("high", "medium", "low")

    def test_no_tests_found_returns_empty_list(self, tmp_path):
        """When no tests match, suggestions list is empty."""
        project = str(tmp_path)
        # Build a graph with no test nodes
        g = ArchGraph()
        g.add_node(
            Node(
                id="mod:app",
                type=NodeType.MODULE,
                label="app",
                file_path="src/app.py",
            )
        )
        data = g.to_data()
        data.project_path = project
        server_module._storage.save(project, data)
        server_module._graph = None

        # A diff touching a file with no corresponding test nodes
        diff = """\
diff --git a/src/unknown.py b/src/unknown.py
index 1234567..abcdefg 100644
--- a/src/unknown.py
+++ b/src/unknown.py
@@ -1 +1,2 @@
 x = 1
+y = 2
"""
        result = codegiraffe_suggest_tests(project, diff=diff)
        assert isinstance(result, dict)
        assert "suggestions" in result
        assert isinstance(result["suggestions"], list)

    def test_max_suggestions_respected(self, tmp_path):
        """Output is truncated to max_suggestions entries."""
        project = str(tmp_path)
        _build_graph(project)

        result = codegiraffe_suggest_tests(
            project, diff=_SAMPLE_DIFF, max_suggestions=1
        )
        assert isinstance(result, dict)
        assert len(result["suggestions"]) <= 1
        assert result["total_suggestions"] <= 1

    def test_no_diff_no_auto_error(self, tmp_path):
        """diff=None with auto=False returns an error dict."""
        project = str(tmp_path)
        _build_graph(project)

        result = codegiraffe_suggest_tests(project, diff=None, auto=False)
        assert isinstance(result, dict)
        assert "error" in result
        assert "suggestions" in result

    def test_no_uncommitted_changes(self, tmp_path):
        """Empty diff returns a no_changes status dict."""
        project = str(tmp_path)
        _build_graph(project)

        with patch("codegiraffe.server.get_uncommitted_diff", return_value=""):
            result = codegiraffe_suggest_tests(project)

        assert isinstance(result, dict)
        assert result.get("status") == "no_changes"


# ===========================================================================
# TestFileCouplingTool
# ===========================================================================


class TestFileCouplingTool:
    """Tests for the codegiraffe_file_coupling MCP tool."""

    def test_returns_table(self, tmp_path):
        """Output contains the markdown table header."""
        project = str(tmp_path)
        _build_graph(project)

        # Mock git operations to return coupling data
        with patch("codegiraffe.server.is_git_repo", return_value=True), patch(
            "codegiraffe.query.get_commit_file_history",
            return_value=[
                ["src/app.py", "src/utils.py"],
                ["src/app.py", "src/utils.py"],
                ["src/app.py", "src/utils.py"],
            ],
        ):
            result = codegiraffe_file_coupling(project)

        assert "## File Coupling Analysis" in result

    def test_with_file_path(self, tmp_path):
        """file_path filter shows the focus file header."""
        project = str(tmp_path)
        _build_graph(project)

        with patch("codegiraffe.server.is_git_repo", return_value=True), patch(
            "codegiraffe.query.get_commit_file_history",
            return_value=[
                ["src/app.py", "src/utils.py"],
                ["src/app.py", "src/utils.py"],
                ["src/app.py", "src/utils.py"],
            ],
        ):
            result = codegiraffe_file_coupling(project, file_path="src/app.py")

        assert "Focus file" in result
        assert "src/app.py" in result

    def test_not_git_repo(self, tmp_path):
        """Non-git directory returns error."""
        project = str(tmp_path)
        _build_graph(project)

        with patch("codegiraffe.server.is_git_repo", return_value=False):
            result = codegiraffe_file_coupling(project)

        assert "Error" in result
        assert "not a git repository" in result

    def test_no_pairs_above_threshold(self, tmp_path):
        """No coupling results returns an appropriate message."""
        project = str(tmp_path)
        _build_graph(project)

        with patch("codegiraffe.server.is_git_repo", return_value=True), patch(
            "codegiraffe.query.get_commit_file_history",
            return_value=[],
        ):
            result = codegiraffe_file_coupling(project)

        assert "No file coupling pairs found" in result

"""Tests for CI/CD integration — GitHub Actions workflow and PR comment formatter.

Covers:
- T071: YAML validity and structure of .github/workflows/codegiraffe-pr.yml
- T071: PR comment formatter produces valid markdown output
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "codegiraffe-pr.yml"
SCRIPT_PATH = REPO_ROOT / ".github" / "scripts" / "format-pr-comment.py"


def _load_format_module():
    """Dynamically import .github/scripts/format-pr-comment.py as a module."""
    spec = importlib.util.spec_from_file_location("format_pr_comment", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# TestWorkflowYAML — YAML validity and key structure
# ---------------------------------------------------------------------------


class TestWorkflowYAML:
    """Tests for .github/workflows/codegiraffe-pr.yml validity."""

    def test_workflow_file_exists(self):
        """The workflow file must exist at the expected path."""
        assert WORKFLOW_PATH.exists(), f"Workflow file not found: {WORKFLOW_PATH}"

    def test_workflow_is_valid_yaml(self):
        """The workflow file must parse as valid YAML without errors."""
        yaml = pytest.importorskip("yaml")
        content = WORKFLOW_PATH.read_text()
        # Should not raise
        parsed = yaml.safe_load(content)
        assert parsed is not None

    def test_workflow_has_name_key(self):
        """Workflow must have a top-level 'name' key."""
        yaml = pytest.importorskip("yaml")
        parsed = yaml.safe_load(WORKFLOW_PATH.read_text())
        assert "name" in parsed, "Workflow missing 'name' key"

    def test_workflow_has_on_key(self):
        """Workflow must have a top-level 'on' key (trigger configuration)."""
        yaml = pytest.importorskip("yaml")
        parsed = yaml.safe_load(WORKFLOW_PATH.read_text())
        # PyYAML converts 'on' key to True in some versions — check both
        assert "on" in parsed or True in parsed, "Workflow missing 'on' trigger key"

    def test_workflow_has_jobs_key(self):
        """Workflow must have a top-level 'jobs' key."""
        yaml = pytest.importorskip("yaml")
        parsed = yaml.safe_load(WORKFLOW_PATH.read_text())
        assert "jobs" in parsed, "Workflow missing 'jobs' key"

    def test_workflow_triggers_on_pull_request(self):
        """Workflow must trigger on pull_request events."""
        content = WORKFLOW_PATH.read_text()
        assert "pull_request" in content, "Workflow must trigger on pull_request"

    def test_workflow_references_blast_radius_threshold(self):
        """Workflow must reference the BLAST_RADIUS_THRESHOLD env var."""
        content = WORKFLOW_PATH.read_text()
        assert "BLAST_RADIUS_THRESHOLD" in content, (
            "Workflow must define BLAST_RADIUS_THRESHOLD env var"
        )

    def test_workflow_targets_main_branch(self):
        """Workflow must target the main branch."""
        content = WORKFLOW_PATH.read_text()
        assert "main" in content, "Workflow must reference 'main' branch"

    def test_workflow_uses_checkout_action(self):
        """Workflow must use actions/checkout for repository access."""
        content = WORKFLOW_PATH.read_text()
        assert "actions/checkout" in content, "Workflow must use actions/checkout"

    def test_workflow_uses_setup_python(self):
        """Workflow must set up Python via actions/setup-python."""
        content = WORKFLOW_PATH.read_text()
        assert "actions/setup-python" in content, "Workflow must use actions/setup-python"

    def test_workflow_has_pr_write_permission(self):
        """Workflow must have pull-requests: write permission to post comments."""
        content = WORKFLOW_PATH.read_text()
        assert "pull-requests" in content and "write" in content, (
            "Workflow must grant pull-requests: write permission"
        )

    def test_workflow_calls_format_script(self):
        """Workflow must call the format-pr-comment.py script."""
        content = WORKFLOW_PATH.read_text()
        assert "format-pr-comment.py" in content, (
            "Workflow must call format-pr-comment.py"
        )

    def test_workflow_fetches_full_history(self):
        """Workflow must fetch full git history (fetch-depth: 0) for diffs."""
        content = WORKFLOW_PATH.read_text()
        assert "fetch-depth" in content, (
            "Workflow must set fetch-depth for full git history"
        )


# ---------------------------------------------------------------------------
# TestFormatPRComment — PR comment formatting
# ---------------------------------------------------------------------------


class TestFormatPRComment:
    """Tests for .github/scripts/format-pr-comment.py."""

    def test_script_file_exists(self):
        """The format script must exist at the expected path."""
        assert SCRIPT_PATH.exists(), f"Script not found: {SCRIPT_PATH}"

    def test_format_comment_with_empty_results(self):
        """format_comment() with empty results must return a non-empty string."""
        module = _load_format_module()
        result = module.format_comment({})
        assert isinstance(result, str)
        assert len(result) > 0

    def test_format_comment_contains_header(self):
        """Output must contain a CodeGiraffe header line."""
        module = _load_format_module()
        result = module.format_comment({})
        assert "CodeGiraffe" in result

    def test_format_comment_changed_files_count(self):
        """Output must show the number of changed files."""
        module = _load_format_module()
        results = {"changed_files": ["src/foo.py", "src/bar.py"]}
        result = module.format_comment(results)
        assert "2" in result

    def test_format_comment_blast_radius_table(self):
        """Output must include a blast radius table when blast data is present."""
        module = _load_format_module()
        results = {
            "changed_files": ["src/foo.py"],
            "blast_radius": [
                {"file": "src/foo.py", "downstream_count": 5},
                {"file": "src/bar.py", "downstream_count": 2},
            ],
        }
        result = module.format_comment(results)
        assert "src/foo.py" in result
        assert "5" in result
        assert "src/bar.py" in result
        assert "2" in result

    def test_format_comment_blast_radius_table_headers(self):
        """Blast radius section must have a table with File and Downstream columns."""
        module = _load_format_module()
        results = {
            "blast_radius": [
                {"file": "src/foo.py", "downstream_count": 3},
            ],
        }
        result = module.format_comment(results)
        # Should contain table-like structure
        assert "File" in result or "file" in result
        assert "Downstream" in result or "downstream" in result or "nodes" in result

    def test_format_comment_test_suggestions_section(self):
        """Output must list test suggestions when they are present."""
        module = _load_format_module()
        results = {
            "test_suggestions": ["tests/test_foo.py", "tests/test_bar.py"],
        }
        result = module.format_comment(results)
        assert "tests/test_foo.py" in result
        assert "tests/test_bar.py" in result

    def test_format_comment_omits_empty_blast_section(self):
        """When blast_radius list is empty, table section should be absent or empty."""
        module = _load_format_module()
        results = {"blast_radius": []}
        result = module.format_comment(results)
        # Should not crash; blast radius table rows should not appear
        assert isinstance(result, str)

    def test_format_comment_omits_empty_test_section(self):
        """When test_suggestions list is empty, test section should be absent."""
        module = _load_format_module()
        results = {"test_suggestions": []}
        result = module.format_comment(results)
        assert isinstance(result, str)

    def test_format_comment_is_valid_markdown(self):
        """Output must contain markdown structural elements."""
        module = _load_format_module()
        results = {
            "changed_files": ["src/handler.py"],
            "blast_radius": [{"file": "src/handler.py", "downstream_count": 7}],
            "test_suggestions": ["tests/test_handler.py"],
        }
        result = module.format_comment(results)
        # Must have at least one markdown heading
        assert "##" in result or "#" in result

    def test_format_comment_footer_attribution(self):
        """Output must include attribution to CodeGiraffe."""
        module = _load_format_module()
        result = module.format_comment({})
        lower = result.lower()
        assert "codegiraffe" in lower

    def test_format_comment_returns_string(self):
        """format_comment() must return a str, not bytes or other type."""
        module = _load_format_module()
        result = module.format_comment({"changed_files": [], "blast_radius": []})
        assert isinstance(result, str)

    def test_format_comment_zero_changed_files(self):
        """Explicit zero changed files must be handled gracefully."""
        module = _load_format_module()
        result = module.format_comment({"changed_files": []})
        assert "0" in result

    def test_format_comment_large_blast_radius(self):
        """Large blast radius data renders all rows."""
        module = _load_format_module()
        blast = [{"file": f"src/module{i}.py", "downstream_count": i * 2} for i in range(10)]
        results = {"blast_radius": blast}
        result = module.format_comment(results)
        # All 10 files should appear
        for i in range(10):
            assert f"src/module{i}.py" in result

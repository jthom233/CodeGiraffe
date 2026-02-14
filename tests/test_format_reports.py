"""Tests for markdown format helpers in server.py (v0.10.0).

Covers _format_validation_report, _format_test_suggestions,
and _format_coupling_report.
"""

from codegiraffe.diff_parser import (
    ChangeReport,
    CouplingPair,
    DiffFile,
    DiffHunk,
    TestSuggestion,
)
from codegiraffe.server import (
    _format_coupling_report,
    _format_test_suggestions,
    _format_validation_report,
)


# ---------------------------------------------------------------------------
# TestFormatValidationReport
# ---------------------------------------------------------------------------


class TestFormatValidationReport:
    """Tests for _format_validation_report."""

    def test_empty_report(self):
        """An empty ChangeReport produces a report with the header."""
        report = ChangeReport()
        result = _format_validation_report(report)
        assert "## Change Impact Validation" in result
        assert "### Changes Detected" in result
        assert "No files changed" in result

    def test_uncovered_nodes(self):
        """Uncovered nodes appear under Potentially Missing Changes."""
        report = ChangeReport(
            uncovered_nodes=[
                "module:src/bar/consumer.py",
                "endpoint:/api/users",
            ],
        )
        result = _format_validation_report(report)
        assert "### Potentially Missing Changes" in result
        assert "`module:src/bar/consumer.py`" in result
        assert "`endpoint:/api/users`" in result

    def test_contract_violations(self):
        """Contract violations section is present when violations exist."""
        report = ChangeReport(
            contract_violations=[
                "contract:api/users -- producer changed but consumer not updated",
            ],
        )
        result = _format_validation_report(report)
        assert "### Contract Violations" in result
        assert "contract:api/users" in result
        assert "producer changed" in result

    def test_recommendations_listed(self):
        """Recommendations are listed as bullet items."""
        report = ChangeReport(
            recommendations=[
                "Review src/bar/consumer.py",
                "Verify endpoint:/api/users route",
                "Run tests in tests/test_handler.py",
            ],
        )
        result = _format_validation_report(report)
        assert "### Recommendations" in result
        assert "- Review src/bar/consumer.py" in result
        assert "- Verify endpoint:/api/users route" in result
        assert "- Run tests in tests/test_handler.py" in result

    def test_changed_files_list(self):
        """Changed files are listed with their status indicators."""
        report = ChangeReport(
            changed_files=[
                DiffFile(path="src/foo/handler.py", status="modified"),
                DiffFile(path="src/new_file.py", status="added"),
                DiffFile(path="src/old_file.py", status="deleted"),
            ],
        )
        result = _format_validation_report(report)
        assert "`src/foo/handler.py` (modified)" in result
        assert "`src/new_file.py` (added)" in result
        assert "`src/old_file.py` (deleted)" in result


# ---------------------------------------------------------------------------
# TestFormatTestSuggestions
# ---------------------------------------------------------------------------


class TestFormatTestSuggestions:
    """Tests for _format_test_suggestions."""

    def test_high_relevance_section(self):
        """A suggestion with score >= 0.7 appears in High Relevance."""
        suggestions = [
            TestSuggestion(
                file_path="tests/test_handler.py",
                score=0.9,
                reason="directly tests handler",
                strategy="graph",
            ),
        ]
        result = _format_test_suggestions(suggestions)
        assert "### High Relevance" in result
        assert "tests/test_handler.py" in result
        assert "0.9" in result

    def test_medium_relevance_section(self):
        """A suggestion with 0.3 <= score < 0.7 appears in Medium Relevance."""
        suggestions = [
            TestSuggestion(
                file_path="tests/test_api.py",
                score=0.5,
                reason="tests sibling module",
                strategy="naming",
            ),
        ]
        result = _format_test_suggestions(suggestions)
        assert "### Medium Relevance" in result
        assert "tests/test_api.py" in result
        assert "0.5" in result

    def test_low_relevance_section(self):
        """A suggestion with score < 0.3 appears in Low Relevance."""
        suggestions = [
            TestSuggestion(
                file_path="tests/test_reporting.py",
                score=0.2,
                reason="transitive dependency",
                strategy="blast_radius",
            ),
        ]
        result = _format_test_suggestions(suggestions)
        assert "### Low Relevance" in result
        assert "tests/test_reporting.py" in result
        assert "0.2" in result

    def test_empty_suggestions(self):
        """Empty suggestions list produces appropriate message."""
        result = _format_test_suggestions([])
        assert "No test" in result.lower() or "no test" in result.lower()
        # Should not contain any relevance sections
        assert "### High Relevance" not in result
        assert "### Medium Relevance" not in result
        assert "### Low Relevance" not in result

    def test_file_paths_in_output(self):
        """All suggestion file paths appear in the output."""
        suggestions = [
            TestSuggestion(
                file_path="tests/test_handler.py",
                score=0.9,
                reason="direct",
                strategy="graph",
            ),
            TestSuggestion(
                file_path="tests/test_models.py",
                score=0.5,
                reason="sibling",
                strategy="naming",
            ),
            TestSuggestion(
                file_path="tests/test_utils.py",
                score=0.2,
                reason="transitive",
                strategy="blast_radius",
            ),
        ]
        result = _format_test_suggestions(suggestions)
        assert "tests/test_handler.py" in result
        assert "tests/test_models.py" in result
        assert "tests/test_utils.py" in result


# ---------------------------------------------------------------------------
# TestFormatCouplingReport
# ---------------------------------------------------------------------------


class TestFormatCouplingReport:
    """Tests for _format_coupling_report."""

    def test_table_structure(self):
        """Output contains a markdown table with correct column headers."""
        pairs = [
            CouplingPair(
                file_a="src/foo.py",
                file_b="src/bar.py",
                co_change_count=10,
                change_count_a=20,
                change_count_b=15,
                coupling=0.50,
                in_graph=True,
                edge_type="imports",
            ),
        ]
        result = _format_coupling_report(pairs, file_path=None)
        assert "| Coupled File |" in result
        assert "| Co-Changes |" in result
        assert "| Coupling |" in result
        assert "| In Graph? |" in result

    def test_implicit_coupling_section(self):
        """Pairs with in_graph=False and high coupling show implicit coupling section."""
        pairs = [
            CouplingPair(
                file_a="src/foo.py",
                file_b="config/settings.yaml",
                co_change_count=8,
                change_count_a=20,
                change_count_b=10,
                coupling=0.80,
                in_graph=False,
                edge_type="",
            ),
        ]
        result = _format_coupling_report(pairs, file_path="src/foo.py")
        assert "Implicit Coupling" in result
        assert "config/settings.yaml" in result

    def test_no_pairs_message(self):
        """Empty pairs list produces an appropriate message."""
        result = _format_coupling_report([], file_path=None)
        assert "No file coupling" in result or "no file coupling" in result

    def test_file_path_header(self):
        """When file_path is provided, the header mentions the focus file."""
        pairs = [
            CouplingPair(
                file_a="src/handler.py",
                file_b="src/models.py",
                co_change_count=15,
                change_count_a=30,
                change_count_b=20,
                coupling=0.50,
                in_graph=True,
                edge_type="imports",
            ),
        ]
        result = _format_coupling_report(pairs, file_path="src/handler.py")
        assert "`src/handler.py`" in result

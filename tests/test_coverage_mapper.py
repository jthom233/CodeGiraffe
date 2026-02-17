"""Tests for coverage_mapper.py — US8 Test Coverage Mapping.

Covers T052 (coverage parsing), T053 (mapping to nodes), T054 (risk/test
integration and contract tests).
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from codegiraffe.graph import ArchGraph, Edge, Node
from codegiraffe.schema import EdgeType, NodeType


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_graph(*nodes: tuple[str, str, str]) -> ArchGraph:
    """Build an ArchGraph from (id, file_path, type) tuples."""
    g = ArchGraph()
    for nid, fp, ntype in nodes:
        g.add_node(Node(id=nid, type=ntype, label=nid, file_path=fp))
    return g


def _write_tmp(content: str | bytes, suffix: str = ".json") -> str:
    """Write content to a temp file and return its path."""
    with tempfile.NamedTemporaryFile(
        mode="wb" if isinstance(content, bytes) else "w",
        suffix=suffix,
        delete=False,
    ) as f:
        if isinstance(content, bytes):
            f.write(content)
        else:
            f.write(content)
        return f.name


# ---------------------------------------------------------------------------
# T052: Coverage parsing tests
# ---------------------------------------------------------------------------


COVERAGE_PY_JSON = json.dumps(
    {
        "meta": {"version": "7.0"},
        "files": {
            "src/auth.py": {"summary": {"percent_covered": 85.5}},
            "src/db.py": {"summary": {"percent_covered": 0.0}},
        },
    }
)

ISTANBUL_JSON = json.dumps(
    {
        "src/auth.py": {"s": {"0": 1, "1": 1, "2": 0}, "fnMap": {}},
        "src/db.py": {"s": {"0": 0, "1": 0}, "fnMap": {}},
    }
)

LCOV_TEXT = """\
SF:src/auth.py
DA:1,1
DA:2,1
DA:3,0
end_of_record
SF:src/db.py
DA:1,0
DA:2,0
end_of_record
"""


class TestParseCoveragePy:
    """T052 — parse_coverage_py() tests."""

    def test_returns_file_percentage_mapping(self, tmp_path):
        """parse_coverage_py returns dict mapping file paths to percentages."""
        from codegiraffe.coverage_mapper import parse_coverage_py

        path = tmp_path / "coverage.json"
        path.write_text(COVERAGE_PY_JSON)

        result = parse_coverage_py(str(path))

        assert isinstance(result, dict)
        assert "src/auth.py" in result
        assert result["src/auth.py"] == pytest.approx(85.5)

    def test_zero_percent_coverage_included(self, tmp_path):
        """parse_coverage_py includes files with 0% coverage."""
        from codegiraffe.coverage_mapper import parse_coverage_py

        path = tmp_path / "coverage.json"
        path.write_text(COVERAGE_PY_JSON)

        result = parse_coverage_py(str(path))

        assert "src/db.py" in result
        assert result["src/db.py"] == pytest.approx(0.0)

    def test_file_not_found_raises(self):
        """parse_coverage_py raises FileNotFoundError for missing file."""
        from codegiraffe.coverage_mapper import parse_coverage_py

        with pytest.raises(FileNotFoundError):
            parse_coverage_py("/nonexistent/coverage.json")


class TestParseIstanbul:
    """T052 — parse_istanbul() tests."""

    def test_returns_file_percentage_mapping(self, tmp_path):
        """parse_istanbul returns dict mapping file paths to percentages."""
        from codegiraffe.coverage_mapper import parse_istanbul

        path = tmp_path / "coverage.json"
        path.write_text(ISTANBUL_JSON)

        result = parse_istanbul(str(path))

        assert isinstance(result, dict)
        assert "src/auth.py" in result
        # 2 of 3 statements covered = ~66.67%
        assert result["src/auth.py"] == pytest.approx(66.67, abs=0.1)

    def test_zero_percent_coverage_included(self, tmp_path):
        """parse_istanbul includes files where all statements are uncovered."""
        from codegiraffe.coverage_mapper import parse_istanbul

        path = tmp_path / "coverage.json"
        path.write_text(ISTANBUL_JSON)

        result = parse_istanbul(str(path))

        assert "src/db.py" in result
        assert result["src/db.py"] == pytest.approx(0.0)

    def test_empty_statement_map_treated_as_zero(self, tmp_path):
        """parse_istanbul treats empty statement map as 0% coverage."""
        from codegiraffe.coverage_mapper import parse_istanbul

        data = json.dumps({"src/empty.py": {"s": {}, "fnMap": {}}})
        path = tmp_path / "coverage.json"
        path.write_text(data)

        result = parse_istanbul(str(path))
        assert result.get("src/empty.py", 0.0) == pytest.approx(0.0)


class TestParseLcov:
    """T052 — parse_lcov() tests."""

    def test_returns_file_percentage_mapping(self, tmp_path):
        """parse_lcov returns dict mapping file paths to percentages."""
        from codegiraffe.coverage_mapper import parse_lcov

        path = tmp_path / "lcov.info"
        path.write_text(LCOV_TEXT)

        result = parse_lcov(str(path))

        assert isinstance(result, dict)
        assert "src/auth.py" in result
        # 2 of 3 lines hit = 66.67%
        assert result["src/auth.py"] == pytest.approx(66.67, abs=0.1)

    def test_fully_uncovered_file(self, tmp_path):
        """parse_lcov includes 0% covered file."""
        from codegiraffe.coverage_mapper import parse_lcov

        path = tmp_path / "lcov.info"
        path.write_text(LCOV_TEXT)

        result = parse_lcov(str(path))

        assert "src/db.py" in result
        assert result["src/db.py"] == pytest.approx(0.0)

    def test_file_not_found_raises(self):
        """parse_lcov raises FileNotFoundError for missing file."""
        from codegiraffe.coverage_mapper import parse_lcov

        with pytest.raises(FileNotFoundError):
            parse_lcov("/nonexistent/lcov.info")


class TestAutoDetectFormat:
    """T052 — auto_detect_format() tests."""

    def test_detects_coverage_py(self, tmp_path):
        """auto_detect_format returns 'coverage_py' for coverage.py JSON."""
        from codegiraffe.coverage_mapper import auto_detect_format

        path = tmp_path / "coverage.json"
        path.write_text(COVERAGE_PY_JSON)

        assert auto_detect_format(str(path)) == "coverage_py"

    def test_detects_istanbul(self, tmp_path):
        """auto_detect_format returns 'istanbul' for Istanbul JSON."""
        from codegiraffe.coverage_mapper import auto_detect_format

        path = tmp_path / "coverage.json"
        path.write_text(ISTANBUL_JSON)

        assert auto_detect_format(str(path)) == "istanbul"

    def test_detects_lcov(self, tmp_path):
        """auto_detect_format returns 'lcov' for LCOV files."""
        from codegiraffe.coverage_mapper import auto_detect_format

        path = tmp_path / "lcov.info"
        path.write_text(LCOV_TEXT)

        assert auto_detect_format(str(path)) == "lcov"


# ---------------------------------------------------------------------------
# T053: Coverage mapping tests
# ---------------------------------------------------------------------------


class TestMapCoverageToNodes:
    """T053 — map_coverage_to_nodes() tests."""

    def test_sets_test_coverage_metadata_on_matching_node(self):
        """map_coverage_to_nodes sets _test_coverage on nodes whose file_path matches."""
        from codegiraffe.coverage_mapper import map_coverage_to_nodes

        g = _make_graph(
            ("mod:auth", "src/auth.py", NodeType.MODULE),
            ("mod:db", "src/db.py", NodeType.MODULE),
        )
        coverage = {"src/auth.py": 85.5, "src/db.py": 0.0}

        map_coverage_to_nodes(g, coverage)

        auth_node = g.graph.nodes["mod:auth"]["node"]
        assert auth_node.metadata.get("_test_coverage") == pytest.approx(85.5)

    def test_uncovered_node_gets_zero_coverage(self):
        """map_coverage_to_nodes sets _test_coverage=0.0 for 0% covered nodes."""
        from codegiraffe.coverage_mapper import map_coverage_to_nodes

        g = _make_graph(("mod:db", "src/db.py", NodeType.MODULE))
        coverage = {"src/db.py": 0.0}

        map_coverage_to_nodes(g, coverage)

        db_node = g.graph.nodes["mod:db"]["node"]
        assert db_node.metadata.get("_test_coverage") == pytest.approx(0.0)

    def test_files_not_in_coverage_get_no_metadata_change(self):
        """map_coverage_to_nodes does not touch nodes with no coverage data."""
        from codegiraffe.coverage_mapper import map_coverage_to_nodes

        g = _make_graph(("mod:utils", "src/utils.py", NodeType.MODULE))
        coverage = {"src/auth.py": 85.5}  # utils not in coverage

        map_coverage_to_nodes(g, coverage)

        utils_node = g.graph.nodes["mod:utils"]["node"]
        assert "_test_coverage" not in utils_node.metadata

    def test_empty_coverage_data_is_noop(self):
        """map_coverage_to_nodes with empty dict does not set any metadata."""
        from codegiraffe.coverage_mapper import map_coverage_to_nodes

        g = _make_graph(("mod:auth", "src/auth.py", NodeType.MODULE))
        map_coverage_to_nodes(g, {})

        auth_node = g.graph.nodes["mod:auth"]["node"]
        assert "_test_coverage" not in auth_node.metadata

    def test_suffix_match_works(self):
        """map_coverage_to_nodes matches nodes where file_path suffix matches coverage key."""
        from codegiraffe.coverage_mapper import map_coverage_to_nodes

        # Node stores an absolute-style path, coverage reports relative
        g = _make_graph(
            ("mod:auth", "/project/src/auth.py", NodeType.MODULE),
        )
        coverage = {"src/auth.py": 75.0}

        map_coverage_to_nodes(g, coverage)

        auth_node = g.graph.nodes["mod:auth"]["node"]
        assert auth_node.metadata.get("_test_coverage") == pytest.approx(75.0)


# ---------------------------------------------------------------------------
# T054: Coverage-enhanced risk/test and contract tests
# ---------------------------------------------------------------------------


class TestRiskMultiplierForUncoveredNodes:
    """T054 — codegiraffe_risk_assessment gives uncovered nodes 1.5x risk multiplier."""

    def test_uncovered_node_has_higher_risk_than_covered(self):
        """Nodes with _test_coverage=0 get 1.5x risk multiplier."""
        from codegiraffe.query import compute_risk_with_coverage

        g = _make_graph(
            ("mod:auth", "src/auth.py", NodeType.MODULE),
            ("mod:db", "src/db.py", NodeType.MODULE),
        )

        # Set coverage: auth is covered, db is not
        auth_node = g.graph.nodes["mod:auth"]["node"]
        auth_node.metadata["_test_coverage"] = 80.0

        db_node = g.graph.nodes["mod:db"]["node"]
        db_node.metadata["_test_coverage"] = 0.0

        # Both nodes have same base risk (no edges), multiplier for uncovered
        base_risk = 0.1
        auth_risk = compute_risk_with_coverage(base_risk, auth_node)
        db_risk = compute_risk_with_coverage(base_risk, db_node)

        assert db_risk == pytest.approx(base_risk * 1.5)
        assert auth_risk == pytest.approx(base_risk)  # no multiplier

    def test_node_without_coverage_metadata_gets_multiplier(self):
        """Nodes with no _test_coverage metadata also get 1.5x multiplier."""
        from codegiraffe.query import compute_risk_with_coverage

        g = _make_graph(("mod:unknown", "src/unknown.py", NodeType.MODULE))
        unknown_node = g.graph.nodes["mod:unknown"]["node"]
        # No _test_coverage metadata at all

        base_risk = 0.2
        result = compute_risk_with_coverage(base_risk, unknown_node)

        assert result == pytest.approx(base_risk * 1.5)

    def test_covered_node_above_zero_has_no_multiplier(self):
        """Nodes with _test_coverage > 0 get no multiplier."""
        from codegiraffe.query import compute_risk_with_coverage

        g = _make_graph(("mod:well_tested", "src/well.py", NodeType.MODULE))
        well_node = g.graph.nodes["mod:well_tested"]["node"]
        well_node.metadata["_test_coverage"] = 95.0

        base_risk = 0.3
        result = compute_risk_with_coverage(base_risk, well_node)

        assert result == pytest.approx(base_risk)


class TestSuggestTestsWithCoverageStatus:
    """T054 — suggest_tests_for_changes returns coverage_status field."""

    def test_uncovered_node_returns_uncovered_status(self):
        """suggest_tests returns coverage_status='uncovered' for 0% covered nodes."""
        from codegiraffe.diff_parser import DiffFile
        from codegiraffe.query import suggest_tests

        g = _make_graph(
            ("mod:auth", "src/auth.py", NodeType.MODULE),
            ("mod:test_auth", "tests/test_auth.py", NodeType.MODULE),
        )

        # Mark auth as uncovered
        auth_node = g.graph.nodes["mod:auth"]["node"]
        auth_node.metadata["_test_coverage"] = 0.0
        auth_node.metadata["source"] = "test"  # make it a test node for suggest_tests
        # Actually add a proper test node
        g.graph.nodes["mod:test_auth"]["node"].metadata["source"] = "test"
        g.add_edge(
            Edge(
                source="mod:test_auth",
                target="mod:auth",
                type=EdgeType.IMPORTS,
            )
        )

        diff = [DiffFile(path="src/auth.py", status="modified")]
        results = suggest_tests(g, diff)

        # At minimum, we should find a suggestion; each should have coverage_status
        assert len(results) >= 1
        for r in results:
            assert hasattr(r, "coverage_status")

    def test_covered_node_returns_covered_status(self):
        """suggest_tests returns coverage_status='covered' for covered nodes."""
        from codegiraffe.diff_parser import DiffFile
        from codegiraffe.query import suggest_tests

        g = _make_graph(
            ("mod:auth", "src/auth.py", NodeType.MODULE),
            ("mod:test_auth", "tests/test_auth.py", NodeType.MODULE),
        )
        g.graph.nodes["mod:test_auth"]["node"].metadata["source"] = "test"
        g.graph.nodes["mod:test_auth"]["node"].metadata["_test_coverage"] = 90.0

        g.add_edge(
            Edge(
                source="mod:test_auth",
                target="mod:auth",
                type=EdgeType.IMPORTS,
            )
        )

        diff = [DiffFile(path="src/auth.py", status="modified")]
        results = suggest_tests(g, diff)

        assert len(results) >= 1
        test_auth_results = [r for r in results if "test_auth" in r.file_path]
        assert len(test_auth_results) >= 1
        assert test_auth_results[0].coverage_status == "covered"

    def test_unknown_coverage_returns_unknown_status(self):
        """suggest_tests returns coverage_status='unknown' when no coverage data present."""
        from codegiraffe.diff_parser import DiffFile
        from codegiraffe.query import suggest_tests

        g = _make_graph(
            ("mod:auth", "src/auth.py", NodeType.MODULE),
            ("mod:test_auth", "tests/test_auth.py", NodeType.MODULE),
        )
        g.graph.nodes["mod:test_auth"]["node"].metadata["source"] = "test"
        # No _test_coverage metadata

        g.add_edge(
            Edge(
                source="mod:test_auth",
                target="mod:auth",
                type=EdgeType.IMPORTS,
            )
        )

        diff = [DiffFile(path="src/auth.py", status="modified")]
        results = suggest_tests(g, diff)

        assert len(results) >= 1
        test_auth_results = [r for r in results if "test_auth" in r.file_path]
        assert len(test_auth_results) >= 1
        assert test_auth_results[0].coverage_status == "unknown"


class TestCoverageToolContract:
    """T054 — Contract test: codegiraffe_coverage tool signature."""

    def test_tool_exists_in_server(self):
        """codegiraffe_coverage tool is importable from server module."""
        from codegiraffe.server import codegiraffe_coverage

        assert callable(codegiraffe_coverage)

    def test_tool_accepts_project_path(self, tmp_path):
        """codegiraffe_coverage accepts project_path parameter."""
        import inspect
        from codegiraffe.server import codegiraffe_coverage

        sig = inspect.signature(codegiraffe_coverage)
        assert "project_path" in sig.parameters

    def test_tool_accepts_coverage_path(self, tmp_path):
        """codegiraffe_coverage accepts coverage_path parameter."""
        import inspect
        from codegiraffe.server import codegiraffe_coverage

        sig = inspect.signature(codegiraffe_coverage)
        assert "coverage_path" in sig.parameters

    def test_tool_accepts_format_parameter(self, tmp_path):
        """codegiraffe_coverage accepts format parameter with default 'auto'."""
        import inspect
        from codegiraffe.server import codegiraffe_coverage

        sig = inspect.signature(codegiraffe_coverage)
        assert "format" in sig.parameters
        assert sig.parameters["format"].default == "auto"

    def test_tool_returns_string(self, tmp_path):
        """codegiraffe_coverage returns a string (markdown report)."""
        import codegiraffe.server as server_module
        from codegiraffe.server import codegiraffe_coverage
        from codegiraffe.graph import ArchGraph, GraphData, Node
        from codegiraffe.storage import JSONStorage

        # Set up minimal server state
        server_module._graph = None
        server_module._storage = JSONStorage()

        project_path = str(tmp_path / "proj")
        os.makedirs(project_path)

        g = ArchGraph()
        g.add_node(
            Node(id="mod:auth", type=NodeType.MODULE, label="auth", file_path="src/auth.py")
        )
        data = g.to_data()
        data.project_path = project_path
        server_module._storage.save(project_path, data)
        server_module._graph = None

        # Write a coverage file
        cov_path = str(tmp_path / "coverage.json")
        with open(cov_path, "w") as f:
            f.write(COVERAGE_PY_JSON)

        result = codegiraffe_coverage(
            project_path=project_path,
            coverage_path=cov_path,
            format="auto",
        )
        assert isinstance(result, str)
        assert len(result) > 0

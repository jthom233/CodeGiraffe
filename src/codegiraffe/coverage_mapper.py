"""Coverage data parsing and mapping to graph nodes.

Supports three coverage formats:
- coverage.py JSON (``coverage.py --json``)
- Istanbul/NYC JSON (JavaScript coverage)
- LCOV (generic line coverage format)

Usage::

    from codegiraffe.coverage_mapper import auto_detect_format, parse_coverage_py, map_coverage_to_nodes

    fmt = auto_detect_format("coverage.json")
    if fmt == "coverage_py":
        data = parse_coverage_py("coverage.json")
    map_coverage_to_nodes(graph, data)
"""

from __future__ import annotations

import json
import os

from codegiraffe.graph import ArchGraph, Edge, Node
from codegiraffe.schema import EdgeType, NodeType


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def parse_coverage_py(path: str) -> dict[str, float]:
    """Parse coverage.py JSON, return file -> percentage mapping.

    Expected format::

        {
          "meta": {"version": "7.0"},
          "files": {
            "src/auth.py": {"summary": {"percent_covered": 85.5}},
            ...
          }
        }

    Parameters
    ----------
    path:
        Absolute or relative path to the coverage.py JSON report.

    Returns
    -------
    dict[str, float]
        Mapping of file path to coverage percentage (0–100).

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Coverage file not found: {path}")

    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

    result: dict[str, float] = {}
    for file_path, file_data in data.get("files", {}).items():
        pct = file_data.get("summary", {}).get("percent_covered", 0.0)
        result[file_path] = float(pct)

    return result


def parse_istanbul(path: str) -> dict[str, float]:
    """Parse Istanbul/NYC JSON, return file -> percentage mapping.

    Computes statement coverage percentage from the ``s`` (statements) map
    where each key is a statement index and each value is the hit count.

    Expected format::

        {
          "src/auth.py": {
            "s": {"0": 1, "1": 1, "2": 0},
            "fnMap": {}
          },
          ...
        }

    Parameters
    ----------
    path:
        Absolute or relative path to the Istanbul JSON report.

    Returns
    -------
    dict[str, float]
        Mapping of file path to statement coverage percentage (0–100).

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Coverage file not found: {path}")

    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

    result: dict[str, float] = {}
    for file_path, file_data in data.items():
        statements = file_data.get("s", {})
        if not statements:
            result[file_path] = 0.0
            continue
        total = len(statements)
        covered = sum(1 for count in statements.values() if count > 0)
        pct = (covered / total * 100.0) if total > 0 else 0.0
        result[file_path] = round(pct, 2)

    return result


def parse_lcov(path: str) -> dict[str, float]:
    """Parse LCOV format, return file -> percentage mapping.

    Reads DA (data) records (``DA:<line>,<hits>``) per source file record.

    Expected format::

        SF:src/auth.py
        DA:1,1
        DA:2,1
        DA:3,0
        end_of_record

    Parameters
    ----------
    path:
        Absolute or relative path to the LCOV file.

    Returns
    -------
    dict[str, float]
        Mapping of file path to line coverage percentage (0–100).

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Coverage file not found: {path}")

    result: dict[str, float] = {}
    current_file: str | None = None
    total_lines = 0
    covered_lines = 0

    with open(path, encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if line.startswith("SF:"):
                current_file = line[3:]
                total_lines = 0
                covered_lines = 0
            elif line.startswith("DA:") and current_file is not None:
                parts = line[3:].split(",")
                if len(parts) >= 2:
                    try:
                        hits = int(parts[1])
                        total_lines += 1
                        if hits > 0:
                            covered_lines += 1
                    except ValueError:
                        pass
            elif line == "end_of_record" and current_file is not None:
                pct = (covered_lines / total_lines * 100.0) if total_lines > 0 else 0.0
                result[current_file] = round(pct, 2)
                current_file = None
                total_lines = 0
                covered_lines = 0

    return result


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------


def auto_detect_format(path: str) -> str:
    """Detect coverage format from file content.

    Inspection logic:
    - If the file ends with ``.info`` or ``.lcov`` -> ``"lcov"``
    - If the JSON has a top-level ``"meta"`` key with ``"version"`` -> ``"coverage_py"``
    - Otherwise, if the JSON values contain a ``"s"`` key -> ``"istanbul"``
    - Falls back to ``"coverage_py"``

    Parameters
    ----------
    path:
        Path to the coverage file.

    Returns
    -------
    str
        One of ``"coverage_py"``, ``"istanbul"``, or ``"lcov"``.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Coverage file not found: {path}")

    lower = path.lower()
    if lower.endswith(".info") or lower.endswith(".lcov"):
        return "lcov"

    # Try parsing as JSON
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, UnicodeDecodeError):
        # Not JSON — try LCOV heuristic
        with open(path, encoding="utf-8", errors="replace") as fh:
            content = fh.read(512)
        if "SF:" in content and "end_of_record" in content:
            return "lcov"
        return "coverage_py"

    # coverage.py: top-level "meta" key with "version"
    if isinstance(data, dict) and "meta" in data and "version" in data.get("meta", {}):
        return "coverage_py"

    # Istanbul: dict of file paths -> objects with "s" key
    if isinstance(data, dict) and data:
        first_value = next(iter(data.values()), None)
        if isinstance(first_value, dict) and "s" in first_value:
            return "istanbul"

    return "coverage_py"


# ---------------------------------------------------------------------------
# Graph mapping
# ---------------------------------------------------------------------------


def map_coverage_to_nodes(graph: ArchGraph, coverage: dict[str, float]) -> None:
    """Set ``_test_coverage`` metadata on nodes whose file_path matches coverage keys.

    Matching is done in two passes:
    1. Exact match: ``node.file_path == coverage_key``
    2. Suffix match: ``node.file_path`` ends with ``/<coverage_key>`` or
       ``coverage_key`` ends with ``/<node.file_path>``

    If a match is found, the node's metadata is updated with
    ``_test_coverage: <percentage>``.

    Additionally, if a test module node exists in the graph and is connected
    to a covered node via an ``imports`` edge, a ``TESTED_BY`` edge is created
    from the covered node to the test module node.

    Parameters
    ----------
    graph:
        The architecture graph to update in-place.
    coverage:
        Mapping of file path to coverage percentage (0–100).
    """
    if not coverage:
        return

    for nid, attrs in graph.graph.nodes(data=True):
        node: Node | None = attrs.get("node")
        if node is None or not node.file_path:
            continue

        node_fp = node.file_path
        for cov_key, pct in coverage.items():
            matched = False
            # Pass 1: exact match
            if node_fp == cov_key:
                matched = True
            # Pass 2: suffix match (handles absolute vs. relative paths)
            elif node_fp.endswith("/" + cov_key) or cov_key.endswith("/" + node_fp):
                matched = True

            if matched:
                node.metadata["_test_coverage"] = pct
                break

#!/usr/bin/env python3
"""Run CodeGiraffe change-impact analysis for a pull request.

Scans the checked-out repository, diffs it against the PR base ref, and
writes ``review-results.json`` for ``format-pr-comment.py``.

Usage:
    python architectural-review.py [BASE_REF] [OUTPUT_PATH]

    BASE_REF     git ref to diff against (default: origin/main)
    OUTPUT_PATH  where to write the JSON results (default: review-results.json)

Environment:
    BLAST_RADIUS_THRESHOLD  total blast radius above which the PR is flagged
                            (default: 10)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

from codegiraffe.diff_parser import parse_diff
from codegiraffe.graph import ArchGraph, GraphData
from codegiraffe.query import map_files_to_nodes, suggest_tests, validate_changes
from codegiraffe.scanner import scan_project

DEFAULT_THRESHOLD = 10


def build_graph(project_path: str) -> ArchGraph:
    """Scan *project_path* and return an in-memory architecture graph."""
    result = scan_project(project_path)
    data = GraphData(
        nodes={node.id: node for node in result.nodes},
        edges=result.edges,
        project_path=project_path,
        last_scan=datetime.now(timezone.utc).isoformat(),
    )
    return ArchGraph(data)


def build_results(graph: ArchGraph, raw_diff: str, threshold: int = DEFAULT_THRESHOLD) -> dict:
    """Compute per-file blast radius, coverage gaps and test suggestions.

    Pure function so it can be unit-tested without git or a real checkout.
    """
    diff_files = parse_diff(raw_diff)
    report = validate_changes(graph, diff_files)
    file_paths = [df.path for df in diff_files]
    file_node_map = map_files_to_nodes(graph, file_paths)

    blast_radius = []
    for fp in file_paths:
        node_ids = file_node_map.get(fp, [])
        downstream: set[str] = set()
        for nid in node_ids:
            downstream |= graph.get_all_descendants(nid)
        downstream -= set(node_ids)
        blast_radius.append({"file": fp, "downstream_count": len(downstream)})

    suggestions = suggest_tests(graph, diff_files)

    return {
        "changed_files": file_paths,
        "blast_radius": blast_radius,
        "test_suggestions": [s.file_path for s in suggestions],
        "total_blast_radius": report.total_blast_radius,
        "uncovered_nodes": report.uncovered_nodes,
        "contract_violations": report.contract_violations,
        "recommendations": report.recommendations,
        "threshold": threshold,
        "exceeds_threshold": report.total_blast_radius > threshold,
    }


def main(argv: list[str]) -> int:
    base_ref = argv[1] if len(argv) > 1 else "origin/main"
    output_path = argv[2] if len(argv) > 2 else "review-results.json"
    threshold = int(os.environ.get("BLAST_RADIUS_THRESHOLD", str(DEFAULT_THRESHOLD)))

    diff = subprocess.run(
        ["git", "diff", f"{base_ref}...HEAD"],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )

    graph = build_graph(".")
    results = build_results(graph, diff.stdout, threshold)

    with open(output_path, "w", encoding="utf-8") as fp:
        json.dump(results, fp, indent=2)

    print(
        f"{len(results['changed_files'])} changed files, "
        f"total blast radius {results['total_blast_radius']} "
        f"(threshold {threshold}), "
        f"{len(results['uncovered_nodes'])} uncovered nodes"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

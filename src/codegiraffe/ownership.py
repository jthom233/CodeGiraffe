"""Ownership inference — CODEOWNERS parsing and node annotation.

Parses GitHub-style CODEOWNERS files and maps file ownership to graph nodes.
Supports gitignore-style glob patterns with last-match-wins semantics.
"""

from __future__ import annotations

import fnmatch
import os


def parse_codeowners(project_path: str) -> dict[str, str]:
    """Parse CODEOWNERS file and return a file pattern to owner mapping.

    Searches for CODEOWNERS in root, .github/, and docs/ directories.
    Supports gitignore-style glob patterns. Last match wins (most specific rule).
    Comments (lines starting with #) and blank lines are skipped.

    Parameters
    ----------
    project_path:
        Root directory of the project to search.

    Returns
    -------
    dict[str, str]
        Mapping of file pattern strings to owner strings (e.g. "@auth-team").
        Returns empty dict if no CODEOWNERS file is found.
    """
    candidates = [
        os.path.join(project_path, "CODEOWNERS"),
        os.path.join(project_path, ".github", "CODEOWNERS"),
        os.path.join(project_path, "docs", "CODEOWNERS"),
    ]

    codeowners_path: str | None = None
    for candidate in candidates:
        if os.path.isfile(candidate):
            codeowners_path = candidate
            break

    if codeowners_path is None:
        return {}

    patterns: dict[str, str] = {}

    with open(codeowners_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            # Skip blank lines and comments
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            pattern = parts[0]
            # Use first owner when multiple are listed
            owner = parts[1]
            patterns[pattern] = owner

    return patterns


def match_file_to_owner(file_path: str, codeowners: dict[str, str]) -> str | None:
    """Match a file path against CODEOWNERS patterns using fnmatch.

    Iterates through all patterns in order (preserving insertion order, which
    is the file order) and returns the owner from the LAST matching pattern.
    This implements the CODEOWNERS last-match-wins semantics.

    Parameters
    ----------
    file_path:
        The file path to match (relative path, e.g. "src/auth/login.py").
    codeowners:
        Mapping returned by :func:`parse_codeowners`.

    Returns
    -------
    str | None
        The matching owner string, or ``None`` if no pattern matches.
    """
    matched_owner: str | None = None

    for pattern, owner in codeowners.items():
        if fnmatch.fnmatch(file_path, pattern):
            matched_owner = owner

    return matched_owner


def map_ownership_to_nodes(graph, ownership: dict[str, str]) -> None:
    """Set 'owner' metadata on graph nodes based on their file_path matching CODEOWNERS patterns.

    Updates the ``owner`` key in each matching node's metadata in-place.
    Nodes without a ``file_path`` or whose path matches no pattern are skipped.

    Parameters
    ----------
    graph:
        An :class:`~codegiraffe.graph.ArchGraph` to annotate.
    ownership:
        Pattern-to-owner mapping from :func:`parse_codeowners`.
    """
    for nid, attrs in graph.graph.nodes(data=True):
        node = attrs.get("node")
        if node is None or not node.file_path:
            continue

        owner = match_file_to_owner(node.file_path, ownership)
        if owner is not None:
            node.metadata["owner"] = owner

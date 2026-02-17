"""Convention mining — extract naming patterns and detect anti-patterns from node clusters.

Analyzes clusters of same-type nodes to surface shared naming conventions,
common metadata attributes, and outliers that deviate from the established pattern.
"""

from __future__ import annotations

import os
from collections import Counter
from typing import Any

from codegiraffe.graph import ArchGraph, Node


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _longest_common_suffix(strings: list[str]) -> str:
    """Return the longest common suffix across all strings."""
    if not strings:
        return ""
    reversed_strings = [s[::-1] for s in strings]
    common = os.path.commonprefix(reversed_strings)
    return common[::-1]


def _extract_naming_pattern(node_ids: list[str]) -> str:
    """Detect common prefix and/or suffix in node IDs.

    Returns a human-readable pattern string, e.g.:
    - ``"service:*"`` when all IDs start with "service:"
    - ``"*Service"`` when all IDs end with "Service"
    - ``"service:*Service"`` when both prefix and suffix are detected
    - ``"<no common pattern>"`` when no meaningful pattern is found
    """
    if not node_ids:
        return ""

    if len(node_ids) == 1:
        return node_ids[0]

    prefix = os.path.commonprefix(node_ids)
    suffix = _longest_common_suffix(node_ids)

    # Avoid double-counting characters when prefix + suffix overlap
    # (can happen with very short strings)
    if prefix and suffix and len(prefix) + len(suffix) >= len(node_ids[0]):
        # Trim suffix so it doesn't overlap with prefix
        overlap = len(prefix) + len(suffix) - len(node_ids[0])
        suffix = suffix[overlap:] if overlap < len(suffix) else ""

    # Only include prefix/suffix if they're non-trivial (> 2 chars)
    has_prefix = len(prefix) > 2
    has_suffix = len(suffix) > 2

    if has_prefix and has_suffix:
        return f"{prefix}*{suffix}"
    elif has_prefix:
        return f"{prefix}*"
    elif has_suffix:
        return f"*{suffix}"
    else:
        return "<no common pattern>"


def _compute_common_attributes(nodes: list[Node], threshold: float = 0.66) -> dict[str, Any]:
    """Return metadata keys present in more than *threshold* fraction of nodes.

    For each qualifying key, the most common value across all nodes is stored.
    """
    if not nodes:
        return {}

    total = len(nodes)
    key_counts: Counter[str] = Counter()
    key_values: dict[str, list[Any]] = {}

    for node in nodes:
        for key, value in node.metadata.items():
            key_counts[key] += 1
            key_values.setdefault(key, []).append(value)

    common: dict[str, Any] = {}
    for key, count in key_counts.items():
        if count / total > threshold:
            # Most common value
            value_counter: Counter = Counter(
                str(v) for v in key_values[key]  # stringify for hashability
            )
            most_common_str = value_counter.most_common(1)[0][0]
            # Try to recover the original type
            original_values = key_values[key]
            # Find the first value that matches the most common stringified value
            best_value: Any = most_common_str
            for v in original_values:
                if str(v) == most_common_str:
                    best_value = v
                    break
            common[key] = best_value

    return common



# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_patterns(
    graph: ArchGraph,
    node_type: str,
    min_cluster: int = 3,
) -> dict:
    """Analyze nodes of a given type to extract naming conventions and detect anti-patterns.

    Parameters
    ----------
    graph:
        The architecture graph to analyze.
    node_type:
        The node type string to filter on (e.g. ``"service"``, ``"endpoint"``).
    min_cluster:
        Minimum number of nodes required to extract a pattern.
        If fewer nodes exist, returns an insufficient-data message.

    Returns
    -------
    On success::

        {
            "node_type": str,
            "sample_size": int,
            "naming_pattern": str,
            "common_attributes": dict,   # keys present in >66% of nodes
            "outliers": list[str],        # node IDs violating >50% of conventions
            "exemplar": str              # node ID most representative of the pattern
        }

    On insufficient data::

        {"node_type": str, "sample_size": int, "message": "Insufficient nodes..."}
    """
    nodes = graph.get_nodes_by_type(node_type)
    sample_size = len(nodes)

    if sample_size < min_cluster:
        return {
            "node_type": node_type,
            "sample_size": sample_size,
            "message": (
                f"Insufficient nodes of type '{node_type}' to extract a pattern. "
                f"Found {sample_size}, need at least {min_cluster}."
            ),
        }

    node_ids = [n.id for n in nodes]
    naming_pattern = _extract_naming_pattern(node_ids)
    common_attributes = _compute_common_attributes(nodes)

    # Score each node: count violations of naming + attribute conventions
    violation_counts: list[tuple[str, int]] = []
    total_conventions = len(common_attributes) + (
        1 if naming_pattern and naming_pattern != "<no common pattern>" else 0
    )

    for node in nodes:
        violations = 0

        # Naming pattern check
        if naming_pattern and naming_pattern != "<no common pattern>":
            nid = node.id
            if "*" in naming_pattern:
                parts = naming_pattern.split("*", 1)
                prefix_part = parts[0]
                suffix_part = parts[1] if len(parts) > 1 else ""
                matches = nid.startswith(prefix_part) and nid.endswith(suffix_part)
            else:
                matches = nid == naming_pattern
            if not matches:
                violations += 1

        # Attribute checks
        for key in common_attributes:
            if key not in node.metadata:
                violations += 1

        violation_counts.append((node.id, violations))

    # Outliers: nodes violating more than 50% of total conventions
    outliers: list[str] = []
    if total_conventions > 0:
        for nid, violations in violation_counts:
            if violations / total_conventions > 0.5:
                outliers.append(nid)

    # Exemplar: node with fewest violations (most representative)
    violation_counts.sort(key=lambda x: x[1])
    exemplar = violation_counts[0][0] if violation_counts else node_ids[0]

    return {
        "node_type": node_type,
        "sample_size": sample_size,
        "naming_pattern": naming_pattern,
        "common_attributes": common_attributes,
        "outliers": outliers,
        "exemplar": exemplar,
    }

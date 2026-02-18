"""Layout computation for the Code Giraffe dashboard.

Computes 2-D positions for graph nodes using ForceAtlas2 (if available)
or a deterministic grid fallback.
"""

from __future__ import annotations

import math

import networkx as nx

from codegiraffe.graph import GraphData

try:
    from fa2 import ForceAtlas2
    _FA2_AVAILABLE = True
except ImportError:
    _FA2_AVAILABLE = False


def compute_layout(graph_data: GraphData) -> dict[str, list[float]]:
    """Compute 2-D positions for all nodes in *graph_data*.

    Returns a dict mapping each node ID to a ``[x, y]`` list of floats.
    If *graph_data* has no nodes, returns ``{}``.

    Uses ForceAtlas2 when the ``fa2`` package is installed; otherwise falls
    back to a fast deterministic grid layout.
    """
    if not graph_data.nodes:
        return {}

    nx_graph: nx.DiGraph = nx.DiGraph()
    nx_graph.add_nodes_from(graph_data.nodes.keys())
    for edge in graph_data.edges:
        nx_graph.add_edge(edge.source, edge.target)

    if _FA2_AVAILABLE:
        return _forceatlas2_layout(nx_graph)
    return _grid_fallback_layout(list(graph_data.nodes.keys()))


def _forceatlas2_layout(nx_graph: nx.DiGraph) -> dict[str, list[float]]:
    """Run ForceAtlas2 on *nx_graph* and return normalized ``{node_id: [x, y]}``."""
    fa2 = ForceAtlas2(
        barnesHutOptimize=True,
        barnesHutTheta=1.2,
        iterationWeights=None,
        outboundAttractionDistribution=False,
        edgeWeightInfluence=1.0,
        jitterTolerance=1.0,
        scalingRatio=2.0,
        strongGravityMode=False,
        gravity=1.0,
        verbose=False,
    )
    positions: dict[str, tuple[float, float]] = fa2.forceatlas2_networkx_layout(
        nx_graph, pos=None, iterations=50
    )

    # Convert tuples to lists.
    raw: dict[str, list[float]] = {nid: list(xy) for nid, xy in positions.items()}

    # Normalize to [-1, 1].
    all_x = [coords[0] for coords in raw.values()]
    all_y = [coords[1] for coords in raw.values()]
    min_x, max_x = min(all_x), max(all_x)
    min_y, max_y = min(all_y), max(all_y)
    range_x = max_x - min_x
    range_y = max_y - min_y

    result: dict[str, list[float]] = {}
    for nid, coords in raw.items():
        nx_val = (coords[0] - min_x) / range_x * 2 - 1 if range_x else 0.0
        ny_val = (coords[1] - min_y) / range_y * 2 - 1 if range_y else 0.0
        result[nid] = [nx_val, ny_val]

    return result


def _grid_fallback_layout(node_ids: list[str]) -> dict[str, list[float]]:
    """Assign *node_ids* to a square grid in [-1, 1] x [-1, 1].

    The layout is deterministic and requires no external dependencies.
    """
    if not node_ids:
        return {}

    cols = math.ceil(math.sqrt(len(node_ids)))
    return {
        node_id: [
            (i % cols) / max(cols - 1, 1) * 2 - 1,
            (i // cols) / max(cols - 1, 1) * 2 - 1,
        ]
        for i, node_id in enumerate(node_ids)
    }

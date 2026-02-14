"""Graph export to visualization formats (Mermaid, D3.js JSON)."""

from __future__ import annotations

import json

from codegiraffe.graph import GraphData, Node
from codegiraffe.schema import NodeType

# Mermaid shape mapping by node type
_MERMAID_SHAPES: dict[str, tuple[str, str]] = {
    # type -> (open_bracket, close_bracket)
    NodeType.ENDPOINT: ("[/", "/]"),  # parallelogram
    NodeType.DATABASE_TABLE: ("[(", ")]"),  # cylinder
    NodeType.QUEUE: ("[[", "]]"),  # subroutine
    NodeType.WORKER: ("{{", "}}"),  # hexagon
    NodeType.SERVICE: ("[", "]"),  # rectangle
    NodeType.ENV_VAR: ("(", ")"),  # rounded
    NodeType.CONFIG: ("(", ")"),  # rounded
    NodeType.FRONTEND_COMPONENT: (">", "]"),  # asymmetric
    NodeType.EVENT: ("([", "])"),  # stadium
    NodeType.EXTERNAL_API: ("((", "))"),  # circle
    NodeType.CONTRACT: ("{{", "}}"),  # hexagon
}

_DEFAULT_SHAPE = ("[", "]")


def _sanitize_mermaid_id(node_id: str) -> str:
    """Make a node ID safe for Mermaid syntax."""
    return (
        node_id.replace(":", "_")
        .replace("/", "_")
        .replace("<", "")
        .replace(">", "")
        .replace(" ", "_")
        .replace(".", "_")
        .replace("-", "_")
    )


def _sanitize_mermaid_label(label: str) -> str:
    """Make a label safe for Mermaid syntax."""
    return label.replace('"', "'").replace("\n", " ")


def to_mermaid(
    data: GraphData,
    direction: str = "TD",
    subgraph_by_type: bool = True,
) -> str:
    """Export GraphData as a Mermaid flowchart diagram.

    Parameters
    ----------
    data : GraphData
        The graph data to export.
    direction : str
        Mermaid direction: TD (top-down), LR (left-right), BT (bottom-top),
        RL (right-left).
    subgraph_by_type : bool
        If True, group nodes into subgraphs by their type.

    Returns
    -------
    str
        Mermaid diagram source text.
    """
    lines = [f"flowchart {direction}"]

    if subgraph_by_type:
        # Group nodes by type
        by_type: dict[str, list[Node]] = {}
        for node in data.nodes.values():
            by_type.setdefault(node.type, []).append(node)

        for node_type in sorted(by_type.keys()):
            nodes = by_type[node_type]
            type_label = node_type.replace("_", " ").title()
            lines.append(f"    subgraph {type_label}")
            for node in sorted(nodes, key=lambda n: n.id):
                safe_id = _sanitize_mermaid_id(node.id)
                safe_label = _sanitize_mermaid_label(node.label or node.id)
                open_b, close_b = _MERMAID_SHAPES.get(node.type, _DEFAULT_SHAPE)
                lines.append(
                    f'        {safe_id}{open_b}"{safe_label}"{close_b}'
                )
            lines.append("    end")
    else:
        for node in sorted(data.nodes.values(), key=lambda n: n.id):
            safe_id = _sanitize_mermaid_id(node.id)
            safe_label = _sanitize_mermaid_label(node.label or node.id)
            open_b, close_b = _MERMAID_SHAPES.get(node.type, _DEFAULT_SHAPE)
            lines.append(f'    {safe_id}{open_b}"{safe_label}"{close_b}')

    # Add edges
    for edge in data.edges:
        src = _sanitize_mermaid_id(edge.source)
        tgt = _sanitize_mermaid_id(edge.target)
        edge_label = edge.type.replace("_", " ")
        lines.append(f'    {src} -->|"{edge_label}"| {tgt}')

    return "\n".join(lines) + "\n"


def to_d3_json(data: GraphData) -> str:
    """Export GraphData as D3.js-compatible force-directed graph JSON.

    Returns a JSON string with the structure::

        {
            "nodes": [{"id": ..., "type": ..., "label": ..., "group": ..., ...}],
            "links": [{"source": ..., "target": ..., "type": ..., ...}],
            "metadata": {"project_path": ..., "last_scan": ..., ...}
        }
    """
    nodes = []
    for node in sorted(data.nodes.values(), key=lambda n: n.id):
        nodes.append(
            {
                "id": node.id,
                "type": node.type,
                "label": node.label or node.id,
                "group": node.type,  # D3 uses "group" for coloring
                "file_path": node.file_path,
                "manual": node.manual,
                "metadata": node.metadata,
            }
        )

    links = []
    for edge in data.edges:
        links.append(
            {
                "source": edge.source,
                "target": edge.target,
                "type": edge.type,
                "manual": edge.manual,
                "metadata": edge.metadata,
            }
        )

    result = {
        "nodes": nodes,
        "links": links,
        "metadata": {
            "project_path": data.project_path,
            "last_scan": data.last_scan,
            "schema_version": data.schema_version,
            "node_count": len(nodes),
            "edge_count": len(links),
        },
    }

    return json.dumps(result, indent=2, ensure_ascii=False)

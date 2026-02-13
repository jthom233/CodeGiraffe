"""Tests for graph export (codegiraffe.export)."""

import json

import pytest

from codegiraffe.export import to_d3_json, to_mermaid
from codegiraffe.graph import GraphData, Node
from codegiraffe.schema import EdgeType, NodeType


@pytest.fixture
def export_graph_data(sample_nodes, sample_edges):
    """Graph data for export tests."""
    nodes = {n.id: n for n in sample_nodes}
    return GraphData(
        nodes=nodes,
        edges=sample_edges,
        project_path="/test",
        last_scan="2026-01-01T00:00:00Z",
    )


class TestMermaidExport:
    def test_basic_mermaid_output(self, export_graph_data):
        result = to_mermaid(export_graph_data)
        assert result.startswith("flowchart TD\n")
        assert "subgraph" in result

    def test_mermaid_contains_all_nodes(self, export_graph_data):
        result = to_mermaid(export_graph_data)
        for node in export_graph_data.nodes.values():
            # Sanitized IDs should appear
            safe_id = (
                node.id.replace(":", "_")
                .replace("/", "_")
                .replace("<", "")
                .replace(">", "")
                .replace(" ", "_")
                .replace(".", "_")
                .replace("-", "_")
            )
            assert safe_id in result

    def test_mermaid_contains_all_edges(self, export_graph_data):
        result = to_mermaid(export_graph_data)
        for edge in export_graph_data.edges:
            assert edge.type.replace("_", " ") in result

    def test_mermaid_direction(self, export_graph_data):
        result = to_mermaid(export_graph_data, direction="LR")
        assert result.startswith("flowchart LR\n")

    def test_mermaid_no_subgraphs(self, export_graph_data):
        result = to_mermaid(export_graph_data, subgraph_by_type=False)
        assert "subgraph" not in result

    def test_mermaid_empty_graph(self):
        data = GraphData(nodes={}, edges=[], project_path="/test", last_scan="")
        result = to_mermaid(data)
        assert result.strip() == "flowchart TD"

    def test_mermaid_special_characters_in_labels(self):
        nodes = {
            "test:1": Node(
                id="test:1",
                type=NodeType.SERVICE,
                label='Has "quotes" and <angle>',
            ),
        }
        data = GraphData(nodes=nodes, edges=[], project_path="/test", last_scan="")
        result = to_mermaid(data)
        # Double quotes should be replaced with single quotes in labels
        assert "Has 'quotes' and <angle>" in result

    def test_mermaid_node_shapes_by_type(self):
        """Each node type should produce the correct Mermaid shape brackets."""
        type_to_expected = {
            NodeType.ENDPOINT: ("[/", "/]"),
            NodeType.DATABASE_TABLE: ("[(", ")]"),
            NodeType.QUEUE: ("[[", "]]"),
            NodeType.WORKER: ("{{", "}}"),
            NodeType.SERVICE: ("[", "]"),
            NodeType.ENV_VAR: ("(", ")"),
            NodeType.EVENT: ("([", "])"),
            NodeType.EXTERNAL_API: ("((", "))"),
        }
        for ntype, (open_b, close_b) in type_to_expected.items():
            nodes = {
                f"n:{ntype}": Node(
                    id=f"n:{ntype}", type=ntype, label=f"test {ntype}"
                ),
            }
            data = GraphData(
                nodes=nodes, edges=[], project_path="/test", last_scan=""
            )
            result = to_mermaid(data, subgraph_by_type=False)
            assert open_b in result, f"Missing open bracket for {ntype}"
            assert close_b in result, f"Missing close bracket for {ntype}"

    def test_mermaid_subgraph_grouping(self, export_graph_data):
        """Nodes should be grouped into subgraphs labelled by type."""
        result = to_mermaid(export_graph_data, subgraph_by_type=True)
        # The fixture has endpoints, database tables, workers, env vars,
        # services, and queues
        assert "subgraph Endpoint" in result
        assert "subgraph Database Table" in result
        assert "subgraph Worker" in result
        assert "end" in result


class TestD3Export:
    def test_basic_d3_output(self, export_graph_data):
        result = to_d3_json(export_graph_data)
        parsed = json.loads(result)
        assert "nodes" in parsed
        assert "links" in parsed
        assert "metadata" in parsed

    def test_d3_node_count(self, export_graph_data):
        result = json.loads(to_d3_json(export_graph_data))
        assert len(result["nodes"]) == len(export_graph_data.nodes)
        assert result["metadata"]["node_count"] == len(export_graph_data.nodes)

    def test_d3_edge_count(self, export_graph_data):
        result = json.loads(to_d3_json(export_graph_data))
        assert len(result["links"]) == len(export_graph_data.edges)
        assert result["metadata"]["edge_count"] == len(export_graph_data.edges)

    def test_d3_node_has_required_fields(self, export_graph_data):
        result = json.loads(to_d3_json(export_graph_data))
        for node in result["nodes"]:
            assert "id" in node
            assert "type" in node
            assert "label" in node
            assert "group" in node

    def test_d3_link_has_required_fields(self, export_graph_data):
        result = json.loads(to_d3_json(export_graph_data))
        for link in result["links"]:
            assert "source" in link
            assert "target" in link
            assert "type" in link

    def test_d3_empty_graph(self):
        data = GraphData(nodes={}, edges=[], project_path="/test", last_scan="")
        result = json.loads(to_d3_json(data))
        assert result["nodes"] == []
        assert result["links"] == []
        assert result["metadata"]["node_count"] == 0

    def test_d3_metadata(self, export_graph_data):
        result = json.loads(to_d3_json(export_graph_data))
        assert result["metadata"]["project_path"] == "/test"
        assert result["metadata"]["last_scan"] == "2026-01-01T00:00:00Z"

    def test_d3_valid_json(self, export_graph_data):
        result = to_d3_json(export_graph_data)
        # Should not raise
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_d3_nodes_sorted_by_id(self, export_graph_data):
        result = json.loads(to_d3_json(export_graph_data))
        ids = [n["id"] for n in result["nodes"]]
        assert ids == sorted(ids)

    def test_d3_schema_version(self, export_graph_data):
        result = json.loads(to_d3_json(export_graph_data))
        assert result["metadata"]["schema_version"] == "1.0"

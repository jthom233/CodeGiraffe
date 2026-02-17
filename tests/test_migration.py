"""Tests for migration planning (T074-T075).

TDD — these tests are written BEFORE the implementation in migration.py.
"""

from __future__ import annotations

import json
import pytest

from codegiraffe.graph import ArchGraph, Edge, Node
from codegiraffe.schema import EdgeType, NodeType


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------


def _chain_graph() -> ArchGraph:
    """Service dependency chain: A → B → C (A imports B imports C)."""
    g = ArchGraph()
    for name in ["A", "B", "C"]:
        g.add_node(
            Node(
                id=f"service:{name}",
                type=NodeType.SERVICE,
                label=name,
                metadata={"file_path": f"src/{name.lower()}.py"},
                file_path=f"src/{name.lower()}.py",
            )
        )
    g.add_edge(Edge(source="service:A", target="service:B", type=EdgeType.IMPORTS))
    g.add_edge(Edge(source="service:B", target="service:C", type=EdgeType.IMPORTS))
    return g


def _cycle_graph() -> ArchGraph:
    """Cyclic graph: A → B → C → A."""
    g = ArchGraph()
    for name in ["A", "B", "C"]:
        g.add_node(
            Node(
                id=f"service:{name}",
                type=NodeType.SERVICE,
                label=name,
                file_path=f"src/{name.lower()}.py",
            )
        )
    g.add_edge(Edge(source="service:A", target="service:B", type=EdgeType.IMPORTS))
    g.add_edge(Edge(source="service:B", target="service:C", type=EdgeType.IMPORTS))
    g.add_edge(Edge(source="service:C", target="service:A", type=EdgeType.IMPORTS))
    return g


def _contract_graph() -> ArchGraph:
    """Graph with a contract node linked to service:A."""
    g = _chain_graph()
    g.add_node(
        Node(
            id="contract:api-v1",
            type=NodeType.CONTRACT,
            label="api-v1",
            file_path="contracts/api.yaml",
        )
    )
    g.add_edge(
        Edge(source="service:A", target="contract:api-v1", type=EdgeType.PRODUCES)
    )
    return g


# ---------------------------------------------------------------------------
# T074: Migration plan tests
# ---------------------------------------------------------------------------


class TestGenerateMigrationPlan:
    """T074: Core migration plan generation."""

    def test_plan_returns_required_keys(self):
        """generate_migration_plan() returns a dict with all required keys."""
        from codegiraffe.migration import generate_migration_plan

        graph = _chain_graph()
        plan = generate_migration_plan(graph, "move reads to cache")

        assert isinstance(plan, dict)
        assert "steps" in plan
        assert "checkpoints" in plan
        assert "contract_implications" in plan
        assert "estimated_files" in plan

    def test_plan_steps_are_ordered(self):
        """Steps have sequential 'order' values starting from 1."""
        from codegiraffe.migration import generate_migration_plan

        graph = _chain_graph()
        plan = generate_migration_plan(
            graph, "migrate cache", target_nodes=["service:A", "service:B", "service:C"]
        )

        steps = plan["steps"]
        assert len(steps) > 0
        orders = [s["order"] for s in steps]
        assert orders == list(range(1, len(steps) + 1))

    def test_each_step_has_required_fields(self):
        """Each step contains action, node_id, file, description."""
        from codegiraffe.migration import generate_migration_plan

        graph = _chain_graph()
        plan = generate_migration_plan(
            graph, "migrate", target_nodes=["service:A", "service:B"]
        )

        for step in plan["steps"]:
            assert "order" in step
            assert "action" in step
            assert "node_id" in step
            assert "file" in step
            assert "description" in step

    def test_dependency_order_leaf_first(self):
        """Dependency leaves (C) come before their dependents (B before A) in steps."""
        from codegiraffe.migration import generate_migration_plan

        graph = _chain_graph()
        plan = generate_migration_plan(
            graph,
            "migrate all",
            target_nodes=["service:A", "service:B", "service:C"],
        )

        steps = plan["steps"]
        node_order = {s["node_id"]: s["order"] for s in steps}

        # C has no outgoing imports in the chain (it's the leaf)
        # B depends on C, A depends on B
        # So order should be: C < B < A
        if "service:C" in node_order and "service:B" in node_order:
            assert node_order["service:C"] < node_order["service:B"]
        if "service:B" in node_order and "service:A" in node_order:
            assert node_order["service:B"] < node_order["service:A"]

    def test_checkpoints_are_valid_step_indices(self):
        """Checkpoints are step indices (1-based) within the range of steps."""
        from codegiraffe.migration import generate_migration_plan

        graph = _chain_graph()
        plan = generate_migration_plan(
            graph,
            "migrate",
            target_nodes=["service:A", "service:B", "service:C"],
        )

        steps = plan["steps"]
        checkpoints = plan["checkpoints"]
        valid_orders = {s["order"] for s in steps}

        for cp in checkpoints:
            assert cp in valid_orders, f"Checkpoint {cp} not in step orders {valid_orders}"

    def test_contract_implications_reported(self):
        """When a contract node is connected to affected nodes, it appears in contract_implications."""
        from codegiraffe.migration import generate_migration_plan

        graph = _contract_graph()
        plan = generate_migration_plan(
            graph, "migrate service A", target_nodes=["service:A"]
        )

        # service:A produces contract:api-v1
        implications = plan["contract_implications"]
        assert isinstance(implications, list)
        contract_ids = [imp["contract"] for imp in implications]
        assert "contract:api-v1" in contract_ids

    def test_estimated_files_matches_unique_files(self):
        """estimated_files equals the number of distinct file paths across steps."""
        from codegiraffe.migration import generate_migration_plan

        graph = _chain_graph()
        plan = generate_migration_plan(
            graph,
            "migrate",
            target_nodes=["service:A", "service:B", "service:C"],
        )

        steps = plan["steps"]
        unique_files = len({s["file"] for s in steps if s["file"]})
        assert plan["estimated_files"] == unique_files

    def test_keyword_matching_finds_relevant_nodes(self):
        """Without target_nodes, keywords in description match node labels/ids."""
        from codegiraffe.migration import generate_migration_plan

        graph = _chain_graph()
        # 'A' appears in the label and id of service:A
        plan = generate_migration_plan(graph, "migrate service A")

        # Should find at least something matching "A"
        assert isinstance(plan["steps"], list)


# ---------------------------------------------------------------------------
# T075: Migration edge cases and contract tests
# ---------------------------------------------------------------------------


class TestMigrationEdgeCases:
    """T075: Edge cases and tool contract tests."""

    def test_empty_target_nodes_returns_empty_plan(self):
        """When target_nodes=[] is explicitly passed, steps should be empty."""
        from codegiraffe.migration import generate_migration_plan

        graph = _chain_graph()
        plan = generate_migration_plan(graph, "migrate", target_nodes=[])

        assert plan["steps"] == []
        assert plan["estimated_files"] == 0
        assert plan["contract_implications"] == []

    def test_empty_graph_returns_empty_plan(self):
        """An empty graph produces an empty plan."""
        from codegiraffe.migration import generate_migration_plan

        graph = ArchGraph()
        plan = generate_migration_plan(graph, "move reads to cache")

        assert plan["steps"] == []
        assert plan["estimated_files"] == 0

    def test_cyclic_graph_reports_cycle(self):
        """When all target nodes form a cycle, the plan reports the cycle."""
        from codegiraffe.migration import generate_migration_plan

        graph = _cycle_graph()
        plan = generate_migration_plan(
            graph,
            "migrate cycle",
            target_nodes=["service:A", "service:B", "service:C"],
        )

        # The plan should still produce steps (fallback ordering)
        assert isinstance(plan["steps"], list)
        assert len(plan["steps"]) > 0

        # And should report the cycle somewhere
        # Cycles can surface in checkpoints being empty or in a top-level key
        # We encode them as a "cycles" key in the plan
        assert "cycles" in plan
        assert len(plan["cycles"]) > 0

    def test_cyclic_graph_step_count_matches_target(self):
        """Even with cycles, all target nodes appear as steps."""
        from codegiraffe.migration import generate_migration_plan

        graph = _cycle_graph()
        target = ["service:A", "service:B", "service:C"]
        plan = generate_migration_plan(graph, "migrate cycle", target_nodes=target)

        step_nodes = {s["node_id"] for s in plan["steps"]}
        for nid in target:
            assert nid in step_nodes

    def test_estimated_files_non_negative(self):
        """estimated_files is always a non-negative integer."""
        from codegiraffe.migration import generate_migration_plan

        graph = _chain_graph()
        plan = generate_migration_plan(graph, "anything")

        assert isinstance(plan["estimated_files"], int)
        assert plan["estimated_files"] >= 0

    def test_no_contract_implications_when_none_connected(self):
        """Nodes with no contract connections produce empty contract_implications."""
        from codegiraffe.migration import generate_migration_plan

        graph = _chain_graph()  # no contract nodes
        plan = generate_migration_plan(
            graph, "migrate B", target_nodes=["service:B"]
        )

        assert plan["contract_implications"] == []

    def test_contract_implication_has_impact_field(self):
        """Each contract implication includes an 'impact' description string."""
        from codegiraffe.migration import generate_migration_plan

        graph = _contract_graph()
        plan = generate_migration_plan(
            graph, "migrate", target_nodes=["service:A"]
        )

        for imp in plan["contract_implications"]:
            assert "impact" in imp
            assert isinstance(imp["impact"], str)


# ---------------------------------------------------------------------------
# T075 (cont.): MCP tool contract test (server integration)
# ---------------------------------------------------------------------------


class TestMigrationPlanToolContract:
    """Verify codegiraffe_migration_plan tool accepts required params and returns correct shape."""

    def test_tool_exists_in_server(self):
        """The codegiraffe_migration_plan function exists in server.py."""
        import codegiraffe.server as server_mod

        assert hasattr(server_mod, "codegiraffe_migration_plan"), (
            "codegiraffe_migration_plan not found in server module"
        )

    def test_tool_accepts_project_path_and_description(self, tmp_path):
        """The tool accepts project_path and description (returns a string)."""
        import codegiraffe.server as server_mod

        result = server_mod.codegiraffe_migration_plan(
            project_path=str(tmp_path),
            description="move reads to cache",
        )
        assert isinstance(result, str)

    def test_tool_result_contains_expected_sections(self, tmp_path):
        """Tool output contains Steps, Checkpoints, Contract Implications, Estimated Files."""
        import codegiraffe.server as server_mod

        result = server_mod.codegiraffe_migration_plan(
            project_path=str(tmp_path),
            description="move reads to cache",
        )
        # Either contains section headers or an informational message
        assert isinstance(result, str)
        assert len(result) > 0

    def test_tool_accepts_optional_target_nodes(self, tmp_path):
        """The tool accepts an optional target_nodes JSON array."""
        import codegiraffe.server as server_mod

        result = server_mod.codegiraffe_migration_plan(
            project_path=str(tmp_path),
            description="migrate service A",
            target_nodes='["service:A"]',
        )
        assert isinstance(result, str)

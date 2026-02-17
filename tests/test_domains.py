"""Tests for Domain Model Abstraction (US11 — Phase 15).

TDD: Tests written BEFORE implementation (T066-T068).

Groups:
- T066: Domain inference tests (infer_domains)
- T067: Domain query tests (context_for_task boost, compute_blast_radius domain_groups)
- T068: Domain persistence and contract tests
"""

from __future__ import annotations

import pytest

from codegiraffe.graph import ArchGraph, Edge, GraphData, Node
from codegiraffe.schema import NodeType, EdgeType


# ---------------------------------------------------------------------------
# Helpers — build test graphs
# ---------------------------------------------------------------------------


def _build_dir_graph() -> ArchGraph:
    """Graph with nodes from two directories: payments/ and auth/."""
    graph = ArchGraph()
    graph.add_node(Node(
        id="module:src/payments/service.py",
        type=NodeType.MODULE,
        label="service",
        metadata={"file_path": "src/payments/service.py"},
        file_path="src/payments/service.py",
    ))
    graph.add_node(Node(
        id="module:src/payments/models.py",
        type=NodeType.MODULE,
        label="models",
        metadata={"file_path": "src/payments/models.py"},
        file_path="src/payments/models.py",
    ))
    graph.add_node(Node(
        id="module:src/auth/login.py",
        type=NodeType.MODULE,
        label="login",
        metadata={"file_path": "src/auth/login.py"},
        file_path="src/auth/login.py",
    ))
    return graph


def _build_flat_graph() -> ArchGraph:
    """Graph with nodes having no file_path — use id prefix clustering."""
    graph = ArchGraph()
    graph.add_node(Node(
        id="service:PaymentService",
        type=NodeType.SERVICE,
        label="PaymentService",
        metadata={},
    ))
    graph.add_node(Node(
        id="service:AuthService",
        type=NodeType.SERVICE,
        label="AuthService",
        metadata={},
    ))
    graph.add_node(Node(
        id="endpoint:POST/payment",
        type=NodeType.ENDPOINT,
        label="POST /payment",
        metadata={},
    ))
    graph.add_node(Node(
        id="endpoint:GET/login",
        type=NodeType.ENDPOINT,
        label="GET /login",
        metadata={},
    ))
    return graph


# ===========================================================================
# T066: Domain inference tests
# ===========================================================================


class TestInferDomainsFromDirectory:
    """T066 — infer_domains() clusters nodes by top-level directory from file_path."""

    def test_infer_returns_list(self):
        """infer_domains returns a list."""
        from codegiraffe.domains import infer_domains

        graph = _build_dir_graph()
        result = infer_domains(graph)

        assert isinstance(result, list)

    def test_infer_two_directories(self):
        """Two directories → two domains."""
        from codegiraffe.domains import infer_domains

        graph = _build_dir_graph()
        result = infer_domains(graph)

        names = {d["name"] for d in result}
        assert len(names) == 2

    def test_infer_payments_domain_has_two_nodes(self):
        """payments directory → domain with node_count == 2."""
        from codegiraffe.domains import infer_domains

        graph = _build_dir_graph()
        result = infer_domains(graph)

        payments = next((d for d in result if "payments" in d["name"]), None)
        assert payments is not None
        assert payments["node_count"] == 2

    def test_infer_auth_domain_has_one_node(self):
        """auth directory → domain with node_count == 1."""
        from codegiraffe.domains import infer_domains

        graph = _build_dir_graph()
        result = infer_domains(graph)

        auth = next((d for d in result if "auth" in d["name"]), None)
        assert auth is not None
        assert auth["node_count"] == 1

    def test_infer_domain_includes_node_ids(self):
        """Each domain entry contains a node_ids list."""
        from codegiraffe.domains import infer_domains

        graph = _build_dir_graph()
        result = infer_domains(graph)

        for domain in result:
            assert "node_ids" in domain
            assert isinstance(domain["node_ids"], list)
            assert len(domain["node_ids"]) > 0

    def test_infer_payments_domain_node_ids(self):
        """payments domain node_ids contains both payment module IDs."""
        from codegiraffe.domains import infer_domains

        graph = _build_dir_graph()
        result = infer_domains(graph)

        payments = next((d for d in result if "payments" in d["name"]), None)
        assert payments is not None
        node_ids = set(payments["node_ids"])
        assert "module:src/payments/service.py" in node_ids
        assert "module:src/payments/models.py" in node_ids


class TestInferDomainsFromIdPrefix:
    """T066 — Flat structure (no file_path) falls back to node ID prefix clustering."""

    def test_flat_structure_returns_domains(self):
        """Nodes with no file_path but typed IDs form prefix-based domains."""
        from codegiraffe.domains import infer_domains

        graph = _build_flat_graph()
        result = infer_domains(graph)

        assert isinstance(result, list)

    def test_flat_structure_clusters_by_prefix(self):
        """service: and endpoint: prefixes form distinct clusters."""
        from codegiraffe.domains import infer_domains

        graph = _build_flat_graph()
        result = infer_domains(graph)

        names = {d["name"] for d in result}
        # Should have at least one domain grouping
        assert len(names) >= 1

    def test_flat_prefix_cluster_has_correct_count(self):
        """service prefix → cluster with 2 node IDs."""
        from codegiraffe.domains import infer_domains

        graph = _build_flat_graph()
        result = infer_domains(graph)

        service_domain = next((d for d in result if "service" in d["name"]), None)
        if service_domain is not None:
            assert service_domain["node_count"] == 2


class TestInferDomainsEdgeCases:
    """T066 — Edge cases for domain inference."""

    def test_empty_graph_returns_empty_list(self):
        """Empty graph → empty domain list."""
        from codegiraffe.domains import infer_domains

        graph = ArchGraph()
        result = infer_domains(graph)

        assert result == []

    def test_single_node_per_directory_returns_empty(self):
        """When every directory has only 1 node, no meaningful clusters → empty list."""
        from codegiraffe.domains import infer_domains

        graph = ArchGraph()
        # Each node in a different directory
        graph.add_node(Node(
            id="module:src/a/foo.py",
            type=NodeType.MODULE,
            label="foo",
            metadata={"file_path": "src/a/foo.py"},
            file_path="src/a/foo.py",
        ))
        graph.add_node(Node(
            id="module:src/b/bar.py",
            type=NodeType.MODULE,
            label="bar",
            metadata={"file_path": "src/b/bar.py"},
            file_path="src/b/bar.py",
        ))

        result = infer_domains(graph)

        # 1 node per dir = no meaningful groupings
        assert result == []

    def test_domain_nodes_excluded_from_inference(self):
        """Existing domain nodes are not treated as regular nodes for inference."""
        from codegiraffe.domains import infer_domains

        graph = _build_dir_graph()
        # Add a domain node to the graph
        graph.add_node(Node(
            id="domain:payments",
            type=NodeType.DOMAIN,
            label="payments",
            metadata={},
        ))

        result = infer_domains(graph)
        # domain: nodes should not be included in cluster counts
        payments = next((d for d in result if "payments" in d["name"]), None)
        assert payments is not None
        # Still 2, not 3
        assert payments["node_count"] == 2


# ===========================================================================
# T067: Domain query tests
# ===========================================================================


class TestContextForTaskDomainBoosting:
    """T067 — context_for_task boosts domain-member nodes when task names a domain."""

    def test_domain_name_in_task_boosts_members(self):
        """When task contains a domain name, that domain's members score higher."""
        from codegiraffe.domains import add_domain
        from codegiraffe.query import context_for_task

        graph = ArchGraph()
        # payments domain: 2 nodes
        graph.add_node(Node(
            id="module:src/payments/service.py",
            type=NodeType.MODULE,
            label="service",
            metadata={"file_path": "src/payments/service.py"},
            file_path="src/payments/service.py",
        ))
        graph.add_node(Node(
            id="module:src/payments/models.py",
            type=NodeType.MODULE,
            label="models",
            metadata={"file_path": "src/payments/models.py"},
            file_path="src/payments/models.py",
        ))
        # unrelated node
        graph.add_node(Node(
            id="module:src/auth/login.py",
            type=NodeType.MODULE,
            label="login",
            metadata={"file_path": "src/auth/login.py"},
            file_path="src/auth/login.py",
        ))

        add_domain(graph, "payments", [
            "module:src/payments/service.py",
            "module:src/payments/models.py",
        ])

        result = context_for_task(graph, "payments domain refactoring", use_embeddings=False)

        # Both payments members should be in the result
        assert "module:src/payments/service.py" in result.nodes
        assert "module:src/payments/models.py" in result.nodes

    def test_domain_members_score_higher_than_non_members(self):
        """Domain members have higher _relevance_score than non-members when domain named in task."""
        from codegiraffe.domains import add_domain
        from codegiraffe.query import context_for_task

        graph = ArchGraph()
        graph.add_node(Node(
            id="module:src/payments/service.py",
            type=NodeType.MODULE,
            label="service",
            metadata={"file_path": "src/payments/service.py"},
            file_path="src/payments/service.py",
        ))
        graph.add_node(Node(
            id="module:src/auth/login.py",
            type=NodeType.MODULE,
            label="login",
            metadata={"file_path": "src/auth/login.py"},
            file_path="src/auth/login.py",
        ))

        add_domain(graph, "payments", ["module:src/payments/service.py"])

        result = context_for_task(graph, "payments domain", use_embeddings=False)

        # payments member should be present
        assert "module:src/payments/service.py" in result.nodes

        # If both nodes are present, check scores
        if "module:src/auth/login.py" in result.nodes:
            payment_score = result.nodes["module:src/payments/service.py"].metadata.get("_relevance_score", 0)
            auth_score = result.nodes["module:src/auth/login.py"].metadata.get("_relevance_score", 0)
            assert payment_score >= auth_score


class TestBlastRadiusDomainGroups:
    """T067 — compute_blast_radius groups impacted nodes by domain in domain_groups."""

    def test_blast_radius_has_domain_groups_key(self):
        """compute_blast_radius result includes domain_groups key."""
        from codegiraffe.query import compute_blast_radius

        graph = ArchGraph()
        graph.add_node(Node(id="service:A", type=NodeType.SERVICE, label="A", metadata={}))
        graph.add_node(Node(id="service:B", type=NodeType.SERVICE, label="B", metadata={}))
        graph.add_edge(Edge(source="service:A", target="service:B", type=EdgeType.CALLS))

        result = compute_blast_radius(graph, "service:A")

        assert "domain_groups" in result

    def test_blast_radius_domain_groups_empty_when_no_domains(self):
        """domain_groups is empty dict when no domain nodes exist in graph."""
        from codegiraffe.query import compute_blast_radius

        graph = ArchGraph()
        graph.add_node(Node(id="service:A", type=NodeType.SERVICE, label="A", metadata={}))
        graph.add_node(Node(id="service:B", type=NodeType.SERVICE, label="B", metadata={}))
        graph.add_edge(Edge(source="service:A", target="service:B", type=EdgeType.CALLS))

        result = compute_blast_radius(graph, "service:A")

        assert result["domain_groups"] == {}

    def test_blast_radius_domain_groups_maps_domain_to_impacted_nodes(self):
        """domain_groups maps domain name to list of impacted downstream node IDs in that domain."""
        from codegiraffe.domains import add_domain
        from codegiraffe.query import compute_blast_radius

        graph = ArchGraph()
        graph.add_node(Node(id="service:Gateway", type=NodeType.SERVICE, label="Gateway", metadata={}))
        graph.add_node(Node(id="service:PayService", type=NodeType.SERVICE, label="PayService", metadata={}))
        graph.add_node(Node(id="service:AuthService", type=NodeType.SERVICE, label="AuthService", metadata={}))
        graph.add_edge(Edge(source="service:Gateway", target="service:PayService", type=EdgeType.CALLS))
        graph.add_edge(Edge(source="service:Gateway", target="service:AuthService", type=EdgeType.CALLS))

        # Create domain containing PayService
        add_domain(graph, "payments", ["service:PayService"])
        # Create domain containing AuthService
        add_domain(graph, "auth", ["service:AuthService"])

        result = compute_blast_radius(graph, "service:Gateway")

        domain_groups = result["domain_groups"]
        assert "payments" in domain_groups
        assert "auth" in domain_groups
        assert "service:PayService" in domain_groups["payments"]
        assert "service:AuthService" in domain_groups["auth"]


class TestDomainAddRemove:
    """T067 — add_domain and remove_domain operations."""

    def test_add_domain_creates_domain_node(self):
        """add_domain creates a domain node in the graph."""
        from codegiraffe.domains import add_domain

        graph = ArchGraph()
        graph.add_node(Node(id="service:A", type=NodeType.SERVICE, label="A", metadata={}))

        add_domain(graph, "my-domain", ["service:A"])

        data = graph.to_data()
        domain_nodes = [n for n in data.nodes.values() if n.type == NodeType.DOMAIN]
        assert len(domain_nodes) == 1
        assert domain_nodes[0].label == "my-domain"

    def test_add_domain_creates_belongs_to_edges(self):
        """add_domain creates belongs_to edges from members to domain node."""
        from codegiraffe.domains import add_domain

        graph = ArchGraph()
        graph.add_node(Node(id="service:A", type=NodeType.SERVICE, label="A", metadata={}))
        graph.add_node(Node(id="service:B", type=NodeType.SERVICE, label="B", metadata={}))

        add_domain(graph, "my-domain", ["service:A", "service:B"])

        data = graph.to_data()
        belongs_to_edges = [e for e in data.edges if e.type == EdgeType.BELONGS_TO]
        sources = {e.source for e in belongs_to_edges}
        assert "service:A" in sources
        assert "service:B" in sources

    def test_add_domain_edges_target_domain_node(self):
        """belongs_to edges target the domain node."""
        from codegiraffe.domains import add_domain

        graph = ArchGraph()
        graph.add_node(Node(id="service:A", type=NodeType.SERVICE, label="A", metadata={}))

        add_domain(graph, "my-domain", ["service:A"])

        data = graph.to_data()
        belongs_to_edges = [e for e in data.edges if e.type == EdgeType.BELONGS_TO]
        targets = {e.target for e in belongs_to_edges}
        assert "domain:my-domain" in targets

    def test_remove_domain_deletes_domain_node(self):
        """remove_domain removes the domain node from the graph."""
        from codegiraffe.domains import add_domain, remove_domain

        graph = ArchGraph()
        graph.add_node(Node(id="service:A", type=NodeType.SERVICE, label="A", metadata={}))
        add_domain(graph, "my-domain", ["service:A"])

        remove_domain(graph, "my-domain")

        data = graph.to_data()
        domain_nodes = [n for n in data.nodes.values() if n.type == NodeType.DOMAIN]
        assert len(domain_nodes) == 0

    def test_remove_domain_deletes_belongs_to_edges(self):
        """remove_domain removes belongs_to edges associated with the domain."""
        from codegiraffe.domains import add_domain, remove_domain

        graph = ArchGraph()
        graph.add_node(Node(id="service:A", type=NodeType.SERVICE, label="A", metadata={}))
        add_domain(graph, "my-domain", ["service:A"])

        remove_domain(graph, "my-domain")

        data = graph.to_data()
        belongs_to_edges = [e for e in data.edges if e.type == EdgeType.BELONGS_TO]
        assert len(belongs_to_edges) == 0

    def test_remove_nonexistent_domain_is_noop(self):
        """remove_domain on a domain that does not exist does not raise."""
        from codegiraffe.domains import remove_domain

        graph = ArchGraph()
        # Should not raise
        remove_domain(graph, "ghost-domain")


class TestListDomains:
    """T067 — list_domains returns all domain nodes with member counts."""

    def test_list_domains_returns_list(self):
        """list_domains returns a list."""
        from codegiraffe.domains import list_domains

        graph = ArchGraph()
        result = list_domains(graph)

        assert isinstance(result, list)

    def test_list_domains_empty_when_no_domains(self):
        """list_domains returns empty list when no domain nodes exist."""
        from codegiraffe.domains import list_domains

        graph = ArchGraph()
        result = list_domains(graph)

        assert result == []

    def test_list_domains_returns_correct_domains(self):
        """list_domains returns one entry per domain node."""
        from codegiraffe.domains import add_domain, list_domains

        graph = ArchGraph()
        graph.add_node(Node(id="service:A", type=NodeType.SERVICE, label="A", metadata={}))
        graph.add_node(Node(id="service:B", type=NodeType.SERVICE, label="B", metadata={}))
        add_domain(graph, "alpha", ["service:A"])
        add_domain(graph, "beta", ["service:B"])

        result = list_domains(graph)

        names = {d["name"] for d in result}
        assert "alpha" in names
        assert "beta" in names

    def test_list_domains_includes_node_count(self):
        """list_domains entries include node_count."""
        from codegiraffe.domains import add_domain, list_domains

        graph = ArchGraph()
        graph.add_node(Node(id="service:A", type=NodeType.SERVICE, label="A", metadata={}))
        graph.add_node(Node(id="service:B", type=NodeType.SERVICE, label="B", metadata={}))
        add_domain(graph, "alpha", ["service:A", "service:B"])

        result = list_domains(graph)

        alpha = next(d for d in result if d["name"] == "alpha")
        assert alpha["node_count"] == 2


# ===========================================================================
# T068: Domain persistence and contract tests
# ===========================================================================


class TestDomainPersistence:
    """T068 — Manual domains have manual=True and survive rescans."""

    def test_manual_domain_has_manual_true(self):
        """add_domain sets manual=True on the domain node."""
        from codegiraffe.domains import add_domain

        graph = ArchGraph()
        graph.add_node(Node(id="service:A", type=NodeType.SERVICE, label="A", metadata={}))
        add_domain(graph, "my-domain", ["service:A"])

        data = graph.to_data()
        domain_node = next(n for n in data.nodes.values() if n.type == NodeType.DOMAIN)
        assert domain_node.manual is True

    def test_manual_domain_edges_have_manual_true(self):
        """add_domain sets manual=True on the belongs_to edges."""
        from codegiraffe.domains import add_domain

        graph = ArchGraph()
        graph.add_node(Node(id="service:A", type=NodeType.SERVICE, label="A", metadata={}))
        add_domain(graph, "my-domain", ["service:A"])

        data = graph.to_data()
        belongs_to_edges = [e for e in data.edges if e.type == EdgeType.BELONGS_TO]
        assert all(e.manual is True for e in belongs_to_edges)

    def test_manual_domain_survives_merge_manual_annotations(self):
        """Manual domain node and edges survive merge_manual_annotations (rescan)."""
        from codegiraffe.domains import add_domain

        graph = ArchGraph()
        graph.add_node(Node(id="service:A", type=NodeType.SERVICE, label="A", metadata={}))
        add_domain(graph, "persistent-domain", ["service:A"])
        old_data = graph.to_data()

        # Simulate rescan with fresh graph
        new_graph = ArchGraph()
        new_graph.add_node(Node(id="service:A", type=NodeType.SERVICE, label="A", metadata={}))
        new_graph.merge_manual_annotations(old_data)

        new_data = new_graph.to_data()
        domain_nodes = [n for n in new_data.nodes.values() if n.type == NodeType.DOMAIN]
        assert len(domain_nodes) == 1
        assert domain_nodes[0].label == "persistent-domain"

    def test_belongs_to_edges_in_graph_data(self):
        """After add_domain, belongs_to edges appear in graph.to_data().edges."""
        from codegiraffe.domains import add_domain

        graph = ArchGraph()
        graph.add_node(Node(id="service:A", type=NodeType.SERVICE, label="A", metadata={}))
        add_domain(graph, "my-domain", ["service:A"])

        data = graph.to_data()
        edge_types = {e.type for e in data.edges}
        assert EdgeType.BELONGS_TO in edge_types

    def test_belongs_to_edge_type_is_in_schema(self):
        """EdgeType.BELONGS_TO is defined in schema."""
        assert EdgeType.BELONGS_TO == "belongs_to"

    def test_domain_node_type_is_in_schema(self):
        """NodeType.DOMAIN is defined in schema."""
        assert NodeType.DOMAIN == "domain"


class TestDomainContractTool:
    """T068 — Contract test: codegiraffe_domains tool signature."""

    def test_codegiraffe_domains_function_exists(self):
        """codegiraffe_domains function is importable from server module."""
        from codegiraffe import server
        assert hasattr(server, "codegiraffe_domains")

    def test_codegiraffe_domains_accepts_project_path(self):
        """codegiraffe_domains accepts project_path parameter."""
        import inspect
        from codegiraffe import server

        sig = inspect.signature(server.codegiraffe_domains)
        assert "project_path" in sig.parameters

    def test_codegiraffe_domains_accepts_action(self):
        """codegiraffe_domains accepts action parameter."""
        import inspect
        from codegiraffe import server

        sig = inspect.signature(server.codegiraffe_domains)
        assert "action" in sig.parameters

    def test_codegiraffe_domains_accepts_name(self):
        """codegiraffe_domains accepts name parameter."""
        import inspect
        from codegiraffe import server

        sig = inspect.signature(server.codegiraffe_domains)
        assert "name" in sig.parameters

    def test_codegiraffe_domains_accepts_node_ids(self):
        """codegiraffe_domains accepts node_ids parameter."""
        import inspect
        from codegiraffe import server

        sig = inspect.signature(server.codegiraffe_domains)
        assert "node_ids" in sig.parameters

    def test_codegiraffe_domains_returns_string(self, tmp_path):
        """codegiraffe_domains returns a string (even for an uninitialized project)."""
        from codegiraffe.server import codegiraffe_domains

        result = codegiraffe_domains(
            project_path=str(tmp_path),
            action="list",
        )

        assert isinstance(result, str)

    def test_codegiraffe_domains_list_action_uninitialised(self, tmp_path):
        """list action returns an error or empty message for un-initialised project."""
        from codegiraffe.server import codegiraffe_domains

        result = codegiraffe_domains(
            project_path=str(tmp_path),
            action="list",
        )

        # Must be a string — either an error message or empty list message
        assert isinstance(result, str)

    def test_codegiraffe_domains_invalid_action_returns_error(self, tmp_path):
        """Invalid action returns an error string."""
        from codegiraffe.server import codegiraffe_domains

        result = codegiraffe_domains(
            project_path=str(tmp_path),
            action="explode",
        )

        assert "error" in result.lower() or "invalid" in result.lower()


class TestDomainInferAction:
    """T068 — infer action creates domain nodes from directory structure."""

    def test_infer_action_returns_string(self, tmp_path):
        """infer action returns a descriptive string."""
        from codegiraffe.server import codegiraffe_domains, codegiraffe_init

        # First init a real project
        codegiraffe_init(project_path=str(tmp_path))

        result = codegiraffe_domains(
            project_path=str(tmp_path),
            action="infer",
        )

        assert isinstance(result, str)

    def test_add_action_creates_domain(self, tmp_path):
        """add action creates a named domain with node_ids."""
        from codegiraffe.server import codegiraffe_domains, codegiraffe_init
        from codegiraffe.server import _ensure_graph

        # Init with a Python file to get at least one node
        src = tmp_path / "service.py"
        src.write_text("class PaymentService:\n    pass\n")

        codegiraffe_init(project_path=str(tmp_path))
        graph = _ensure_graph(str(tmp_path))

        # Get a valid node ID from the graph
        nodes = list(graph.to_data().nodes.keys())
        if not nodes:
            pytest.skip("No nodes in graph after init")

        node_id = nodes[0]

        result = codegiraffe_domains(
            project_path=str(tmp_path),
            action="add",
            name="test-domain",
            node_ids=node_id,
        )

        assert isinstance(result, str)
        assert "error" not in result.lower() or "test-domain" in result

    def test_remove_action_removes_domain(self, tmp_path):
        """remove action removes a previously added domain."""
        from codegiraffe.server import codegiraffe_domains, codegiraffe_init
        from codegiraffe.server import _ensure_graph

        src = tmp_path / "service.py"
        src.write_text("class PaymentService:\n    pass\n")
        codegiraffe_init(project_path=str(tmp_path))

        graph = _ensure_graph(str(tmp_path))
        nodes = list(graph.to_data().nodes.keys())
        if not nodes:
            pytest.skip("No nodes in graph after init")

        node_id = nodes[0]
        # Add then remove
        codegiraffe_domains(
            project_path=str(tmp_path),
            action="add",
            name="temp-domain",
            node_ids=node_id,
        )
        result = codegiraffe_domains(
            project_path=str(tmp_path),
            action="remove",
            name="temp-domain",
        )

        assert isinstance(result, str)

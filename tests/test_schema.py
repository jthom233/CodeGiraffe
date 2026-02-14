"""Tests for the schema module (codegiraffe.schema)."""

import pytest

from codegiraffe.schema import EdgeType, NodeType


class TestNodeTypeEnum:
    """Verify NodeType enum values including new v0.4.0 additions."""

    def test_module_exists(self):
        assert NodeType.MODULE == "module"

    def test_module_string_value(self):
        assert NodeType("module") is NodeType.MODULE

    # Backward compatibility: all pre-existing values still resolve
    @pytest.mark.parametrize(
        "member, expected",
        [
            (NodeType.SERVICE, "service"),
            (NodeType.ENDPOINT, "endpoint"),
            (NodeType.DATABASE_TABLE, "database_table"),
            (NodeType.QUEUE, "queue"),
            (NodeType.ENV_VAR, "env_var"),
            (NodeType.CONFIG, "config"),
            (NodeType.WORKER, "worker"),
            (NodeType.FRONTEND_COMPONENT, "frontend_component"),
            (NodeType.EVENT, "event"),
            (NodeType.EXTERNAL_API, "external_api"),
            (NodeType.MODULE, "module"),
            (NodeType.CONTRACT, "contract"),
        ],
    )
    def test_node_type_values(self, member, expected):
        assert member == expected
        assert member.value == expected


class TestEdgeTypeEnum:
    """Verify EdgeType enum values including new v0.4.0 additions."""

    def test_imports_exists(self):
        assert EdgeType.IMPORTS == "imports"

    def test_implements_exists(self):
        assert EdgeType.IMPLEMENTS == "implements"

    def test_contains_exists(self):
        assert EdgeType.CONTAINS == "contains"

    def test_imports_string_value(self):
        assert EdgeType("imports") is EdgeType.IMPORTS

    def test_implements_string_value(self):
        assert EdgeType("implements") is EdgeType.IMPLEMENTS

    def test_contains_string_value(self):
        assert EdgeType("contains") is EdgeType.CONTAINS

    # Backward compatibility: all pre-existing values still resolve
    @pytest.mark.parametrize(
        "member, expected",
        [
            (EdgeType.CALLS, "calls"),
            (EdgeType.READS, "reads"),
            (EdgeType.WRITES, "writes"),
            (EdgeType.PUBLISHES, "publishes"),
            (EdgeType.CONSUMES, "consumes"),
            (EdgeType.DEPENDS_ON, "depends_on"),
            (EdgeType.CONFIGURES, "configures"),
            (EdgeType.OWNS, "owns"),
            (EdgeType.TRIGGERS, "triggers"),
            (EdgeType.IMPORTS, "imports"),
            (EdgeType.IMPLEMENTS, "implements"),
            (EdgeType.CONTAINS, "contains"),
            (EdgeType.CROSS_REPO_CALLS, "cross_repo_calls"),
            (EdgeType.CROSS_REPO_DEPENDS_ON, "cross_repo_depends_on"),
            (EdgeType.CROSS_REPO_PUBLISHES, "cross_repo_publishes"),
            (EdgeType.CROSS_REPO_CONSUMES, "cross_repo_consumes"),
            (EdgeType.PRODUCES, "produces"),
            (EdgeType.CONSUMES_CONTRACT, "consumes_contract"),
            (EdgeType.VALIDATES, "validates"),
            (EdgeType.VIOLATES, "violates"),
        ],
    )
    def test_edge_type_values(self, member, expected):
        assert member == expected
        assert member.value == expected


class TestContractSchemaTypes:
    """Verify v0.8.0 contract-related schema types."""

    def test_contract_node_type_exists(self):
        assert NodeType.CONTRACT == "contract"

    def test_produces_edge_type_exists(self):
        assert EdgeType.PRODUCES == "produces"

    def test_consumes_contract_edge_type_exists(self):
        assert EdgeType.CONSUMES_CONTRACT == "consumes_contract"

    def test_validates_edge_type_exists(self):
        assert EdgeType.VALIDATES == "validates"

    def test_violates_edge_type_exists(self):
        assert EdgeType.VIOLATES == "violates"


class TestEnumStringBehavior:
    """StrEnum members should be usable as plain strings."""

    def test_node_type_is_str(self):
        assert isinstance(NodeType.MODULE, str)

    def test_edge_type_is_str(self):
        assert isinstance(EdgeType.IMPORTS, str)

    def test_node_type_in_format_string(self):
        assert f"type={NodeType.MODULE}" == "type=module"

    def test_edge_type_in_format_string(self):
        assert f"type={EdgeType.CONTAINS}" == "type=contains"

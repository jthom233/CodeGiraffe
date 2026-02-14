"""Node and edge type system for Code Giraffe architecture knowledge graph.

Built-in types are provided as enums for convenience and discoverability,
but any arbitrary string is valid as a node or edge type.
"""

from enum import StrEnum


class NodeType(StrEnum):
    """Built-in node types for common architectural components."""

    SERVICE = "service"
    ENDPOINT = "endpoint"
    DATABASE_TABLE = "database_table"
    QUEUE = "queue"
    ENV_VAR = "env_var"
    CONFIG = "config"
    WORKER = "worker"
    FRONTEND_COMPONENT = "frontend_component"
    EVENT = "event"
    EXTERNAL_API = "external_api"
    MODULE = "module"


class EdgeType(StrEnum):
    """Built-in edge types for common architectural relationships."""

    CALLS = "calls"
    READS = "reads"
    WRITES = "writes"
    PUBLISHES = "publishes"
    CONSUMES = "consumes"
    DEPENDS_ON = "depends_on"
    CONFIGURES = "configures"
    OWNS = "owns"
    TRIGGERS = "triggers"
    IMPORTS = "imports"
    IMPLEMENTS = "implements"
    CONTAINS = "contains"
    CROSS_REPO_CALLS = "cross_repo_calls"
    CROSS_REPO_DEPENDS_ON = "cross_repo_depends_on"
    CROSS_REPO_PUBLISHES = "cross_repo_publishes"
    CROSS_REPO_CONSUMES = "cross_repo_consumes"

"""Neo4j storage backend for Code Giraffe architecture knowledge graph.

Implements the StorageBackend protocol using the neo4j Python driver.
This is an optional dependency -- if neo4j is not installed, importing
this module still works but instantiating Neo4jStorage raises ImportError
with a helpful message.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any

from codegiraffe.graph import Edge, GraphData, Node

logger = logging.getLogger(__name__)

# Optional import with clear error
try:
    from neo4j import GraphDatabase
    HAS_NEO4J = True
except ImportError:
    GraphDatabase = None  # type: ignore[assignment, misc]
    HAS_NEO4J = False


def is_available() -> bool:
    """Check whether the neo4j driver is installed."""
    return HAS_NEO4J


# Environment variable names for connection configuration
NEO4J_URI_VAR = "NEO4J_URI"
NEO4J_USER_VAR = "NEO4J_USER"
NEO4J_PASSWORD_VAR = "NEO4J_PASSWORD"
DEFAULT_URI = "neo4j://localhost:7687"
DEFAULT_USER = "neo4j"


class Neo4jStorage:
    """StorageBackend implementation using Neo4j graph database.

    Connection is configured via environment variables:
    - ``NEO4J_URI``      (default: ``neo4j://localhost:7687``)
    - ``NEO4J_USER``     (default: ``neo4j``)
    - ``NEO4J_PASSWORD`` (required for authenticated access)

    Graph data is stored using a namespace label derived from the SHA-256 hash
    of the ``project_path``.  This isolates different projects within the same
    Neo4j database instance.

    Implements the :class:`codegiraffe.storage.StorageBackend` protocol.
    """

    def __init__(
        self,
        uri: str | None = None,
        auth: tuple[str, str] | None = None,
    ) -> None:
        if not HAS_NEO4J:
            raise ImportError(
                "Neo4j driver not installed. Install with: "
                "pip install codegiraffe[neo4j]"
            )
        self._uri = uri or os.environ.get(NEO4J_URI_VAR, DEFAULT_URI)
        if auth:
            self._auth = auth
        else:
            user = os.environ.get(NEO4J_USER_VAR, DEFAULT_USER)
            password = os.environ.get(NEO4J_PASSWORD_VAR, "")
            self._auth = (user, password)
        self._driver = None

    # ------------------------------------------------------------------
    # Driver lifecycle
    # ------------------------------------------------------------------

    def _get_driver(self):
        """Lazily create the Neo4j driver."""
        if self._driver is None:
            self._driver = GraphDatabase.driver(self._uri, auth=self._auth)
        return self._driver

    def close(self) -> None:
        """Close the driver connection."""
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    # ------------------------------------------------------------------
    # Project namespace
    # ------------------------------------------------------------------

    @staticmethod
    def _project_label(project_path: str) -> str:
        """Generate a Neo4j-safe label from a project path.

        Uses a 12-char hex prefix of the SHA-256 hash so labels are
        deterministic, collision-resistant, and contain only ``[A-Za-z0-9_]``.
        """
        h = hashlib.sha256(project_path.encode()).hexdigest()[:12]
        return f"CG_{h}"

    # ------------------------------------------------------------------
    # StorageBackend protocol
    # ------------------------------------------------------------------

    def exists(self, project_path: str) -> bool:
        """Check if any graph data exists for this project in Neo4j."""
        label = self._project_label(project_path)
        driver = self._get_driver()
        try:
            with driver.session() as session:
                result = session.run(
                    f"MATCH (n:`{label}`) RETURN count(n) > 0 AS exists LIMIT 1"
                )
                record = result.single()
                return bool(record["exists"]) if record else False
        except Exception:
            logger.warning(
                "Failed to check existence for project %s in Neo4j",
                project_path,
                exc_info=True,
            )
            return False

    def load(self, project_path: str) -> GraphData | None:
        """Load graph from Neo4j.

        Returns ``None`` if no data exists for this project or if the load
        fails due to a connection or data error.
        """
        label = self._project_label(project_path)
        driver = self._get_driver()

        try:
            with driver.session() as session:
                # 1. Check existence first
                exists_result = session.run(
                    f"MATCH (n:`{label}`) RETURN count(n) > 0 AS exists LIMIT 1"
                )
                exists_record = exists_result.single()
                if not exists_record or not exists_record["exists"]:
                    return None

                # 2. Load metadata from the meta node
                meta_result = session.run(
                    f"MATCH (m:`{label}_Meta`) RETURN m AS meta LIMIT 1"
                )
                meta_record = meta_result.single()
                if meta_record:
                    meta = meta_record.data().get("meta", {})
                else:
                    meta = {}

                pp = meta.get("project_path", project_path)
                last_scan = meta.get("last_scan")
                schema_version = meta.get("schema_version", "1.0")

                # 3. Load all nodes
                nodes_result = session.run(
                    f"MATCH (n:`{label}`) RETURN n"
                )
                nodes: dict[str, Node] = {}
                for record in nodes_result:
                    props = record.data()["n"]
                    metadata_raw = props.get("metadata", "{}")
                    if isinstance(metadata_raw, str):
                        metadata = json.loads(metadata_raw)
                    else:
                        metadata = metadata_raw or {}

                    node = Node(
                        id=props["id"],
                        type=props["type"],
                        label=props.get("label", ""),
                        file_path=props.get("file_path"),
                        metadata=metadata,
                        manual=bool(props.get("manual", False)),
                    )
                    nodes[node.id] = node

                # 4. Load all edges
                edges_result = session.run(
                    f"MATCH (a:`{label}`)-[r]->(b:`{label}`) "
                    f"RETURN a.id AS source, b.id AS target, "
                    f"r.type AS type, r.metadata AS metadata, r.manual AS manual"
                )
                edges: list[Edge] = []
                for record in edges_result:
                    props = record.data()
                    metadata_raw = props.get("metadata", "{}")
                    if isinstance(metadata_raw, str):
                        metadata = json.loads(metadata_raw)
                    else:
                        metadata = metadata_raw or {}

                    edges.append(
                        Edge(
                            source=props["source"],
                            target=props["target"],
                            type=props["type"],
                            metadata=metadata,
                            manual=bool(props.get("manual", False)),
                        )
                    )

                return GraphData(
                    nodes=nodes,
                    edges=edges,
                    project_path=pp,
                    last_scan=last_scan,
                    schema_version=schema_version,
                )
        except Exception:
            logger.warning(
                "Failed to load graph for project %s from Neo4j",
                project_path,
                exc_info=True,
            )
            return None

    def save(self, project_path: str, data: GraphData) -> None:
        """Save graph to Neo4j.

        Replaces all existing data for this project within a single
        transaction to ensure atomicity.
        """
        label = self._project_label(project_path)
        driver = self._get_driver()

        with driver.session() as session:
            tx = session.begin_transaction()
            try:
                # 1. Clear existing data for this project (nodes + meta)
                tx.run(f"MATCH (n:`{label}`) DETACH DELETE n")
                tx.run(f"MATCH (m:`{label}_Meta`) DETACH DELETE m")

                # 2. Create metadata node
                tx.run(
                    f"CREATE (m:`{label}_Meta`) "
                    f"SET m.project_path = $project_path, "
                    f"    m.last_scan = $last_scan, "
                    f"    m.schema_version = $schema_version",
                    project_path=data.project_path,
                    last_scan=data.last_scan or "",
                    schema_version=data.schema_version,
                )

                # 3. Batch-create nodes
                node_params = [
                    {
                        "id": node.id,
                        "type": node.type,
                        "label": node.label,
                        "file_path": node.file_path,
                        "metadata": json.dumps(node.metadata),
                        "manual": node.manual,
                    }
                    for node in data.nodes.values()
                ]
                if node_params:
                    tx.run(
                        f"UNWIND $nodes AS node "
                        f"CREATE (n:`{label}`) SET n = node",
                        nodes=node_params,
                    )

                # 4. Batch-create edges
                edge_params = [
                    {
                        "source": edge.source,
                        "target": edge.target,
                        "type": edge.type,
                        "metadata": json.dumps(edge.metadata),
                        "manual": edge.manual,
                    }
                    for edge in data.edges
                ]
                if edge_params:
                    tx.run(
                        f"UNWIND $edges AS edge "
                        f"MATCH (a:`{label}` {{id: edge.source}}), "
                        f"      (b:`{label}` {{id: edge.target}}) "
                        f"CREATE (a)-[r:RELATES_TO]->(b) "
                        f"SET r.type = edge.type, "
                        f"    r.metadata = edge.metadata, "
                        f"    r.manual = edge.manual",
                        edges=edge_params,
                    )

                tx.commit()
            except Exception:
                tx.rollback()
                raise

    # ------------------------------------------------------------------
    # Ad-hoc Cypher
    # ------------------------------------------------------------------

    def run_cypher(self, query: str, project_path: str | None = None) -> list[dict]:
        """Execute a read-only Cypher query and return results as dicts.

        Parameters
        ----------
        query:
            A Cypher query string.
        project_path:
            Optional project path — not currently used for scoping but
            reserved for future namespace injection.

        Returns
        -------
        list[dict]
            Each dict is a row from the Cypher result set.
        """
        driver = self._get_driver()
        with driver.session() as session:
            result = session.run(query)
            return [record.data() for record in result]

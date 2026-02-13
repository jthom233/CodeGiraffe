"""SQLite storage backend for larger architecture graphs."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from codegiraffe.graph import Edge, GraphData, Node

STORAGE_DIR = ".codegiraffe"
DB_FILENAME = "graph.db"
SCHEMA_VERSION = "1"


class SQLiteStorage:
    """SQLite-backed storage for architecture knowledge graphs.

    Stores the graph in ``{project_path}/.codegiraffe/graph.db`` with proper
    indexing for efficient node/edge queries.
    """

    def _db_path(self, project_path: str) -> Path:
        """Return the resolved path to the graph SQLite database."""
        return Path(project_path).resolve() / STORAGE_DIR / DB_FILENAME

    def _connect(self, project_path: str) -> sqlite3.Connection:
        """Open a connection to the SQLite database, creating the directory if needed."""
        path = self._db_path(project_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        """Create tables and indexes if they do not already exist."""
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS graph_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS nodes (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                label TEXT NOT NULL DEFAULT '',
                file_path TEXT DEFAULT NULL,
                metadata TEXT NOT NULL DEFAULT '{}',
                manual INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                target TEXT NOT NULL,
                type TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}',
                manual INTEGER NOT NULL DEFAULT 0,
                UNIQUE(source, target, type)
            );
            CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
            CREATE INDEX IF NOT EXISTS idx_nodes_file_path ON nodes(file_path);
            CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source);
            CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target);
            CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(type);
        """)

    def load(self, project_path: str) -> GraphData | None:
        """Load graph data from the SQLite database.

        Returns None if the database file does not exist or if the data
        is unreadable due to corruption or schema mismatch.
        """
        path = self._db_path(project_path)
        if not path.is_file():
            return None

        # Reject empty or non-SQLite files before connecting
        if path.stat().st_size == 0:
            return None

        try:
            conn = self._connect(project_path)
            self._ensure_schema(conn)

            # Load metadata
            meta: dict[str, str] = {}
            for row in conn.execute("SELECT key, value FROM graph_meta"):
                meta[row[0]] = row[1]

            # Load nodes
            nodes: dict[str, Node] = {}
            for row in conn.execute(
                "SELECT id, type, label, file_path, metadata, manual FROM nodes"
            ):
                nid, ntype, label, file_path, metadata_json, manual = row
                nodes[nid] = Node(
                    id=nid,
                    type=ntype,
                    label=label,
                    file_path=file_path,
                    metadata=json.loads(metadata_json),
                    manual=bool(manual),
                )

            # Load edges
            edges: list[Edge] = []
            for row in conn.execute(
                "SELECT source, target, type, metadata, manual FROM edges"
            ):
                source, target, etype, metadata_json, manual = row
                edges.append(
                    Edge(
                        source=source,
                        target=target,
                        type=etype,
                        metadata=json.loads(metadata_json),
                        manual=bool(manual),
                    )
                )

            conn.close()

            return GraphData(
                nodes=nodes,
                edges=edges,
                project_path=meta.get("project_path", project_path),
                last_scan=meta.get("last_scan", ""),
                schema_version=meta.get("schema_version", SCHEMA_VERSION),
            )
        except (sqlite3.Error, ValueError, TypeError):
            return None

    def save(self, project_path: str, data: GraphData) -> None:
        """Save graph data to the SQLite database.

        Creates the ``.codegiraffe`` directory and database file on first
        write if they do not already exist.  Each save replaces all existing
        data within a single transaction.
        """
        conn = self._connect(project_path)
        self._ensure_schema(conn)

        with conn:
            # Clear existing data
            conn.execute("DELETE FROM edges")
            conn.execute("DELETE FROM nodes")
            conn.execute("DELETE FROM graph_meta")

            # Save metadata
            conn.execute(
                "INSERT INTO graph_meta VALUES (?, ?)",
                ("project_path", data.project_path),
            )
            conn.execute(
                "INSERT INTO graph_meta VALUES (?, ?)",
                ("last_scan", data.last_scan or ""),
            )
            conn.execute(
                "INSERT INTO graph_meta VALUES (?, ?)",
                ("schema_version", data.schema_version),
            )

            # Save nodes
            for nid, node in data.nodes.items():
                conn.execute(
                    "INSERT INTO nodes (id, type, label, file_path, metadata, manual) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        node.id,
                        node.type,
                        node.label,
                        node.file_path,
                        json.dumps(node.metadata),
                        int(node.manual),
                    ),
                )

            # Save edges
            for edge in data.edges:
                conn.execute(
                    "INSERT OR IGNORE INTO edges (source, target, type, metadata, manual) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        edge.source,
                        edge.target,
                        edge.type,
                        json.dumps(edge.metadata),
                        int(edge.manual),
                    ),
                )

        conn.close()

    def exists(self, project_path: str) -> bool:
        """Check whether the SQLite database file exists on disk."""
        return self._db_path(project_path).is_file()

"""Storage abstraction and JSON backend for Code Giraffe graph persistence.

Provides a StorageBackend protocol for swappable persistence (FR-010) and a
concrete JSONStorage implementation that reads/writes .codegiraffe/graph.json.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Protocol

from codegiraffe.graph import GraphData

logger = logging.getLogger(__name__)

STORAGE_DIR = ".codegiraffe"
GRAPH_FILENAME = "graph.json"


class StorageBackend(Protocol):
    """Protocol for graph data persistence backends.

    Any class implementing these three methods can serve as a drop-in
    replacement for JSONStorage (e.g. SQLite, Neo4j).
    """

    def load(self, project_path: str) -> GraphData | None:
        """Load graph data for a project.

        Returns None if no persisted data exists or if the data is
        unreadable.
        """
        ...

    def save(self, project_path: str, data: GraphData) -> None:
        """Persist graph data for a project."""
        ...

    def exists(self, project_path: str) -> bool:
        """Check whether persisted graph data exists for a project."""
        ...


class JSONStorage:
    """JSON-file storage backend.

    Stores the serialized GraphData as ``{project_path}/.codegiraffe/graph.json``.
    Creates the ``.codegiraffe`` directory on first write if it doesn't exist.
    """

    def _graph_path(self, project_path: str) -> Path:
        """Return the resolved path to the graph JSON file."""
        return Path(project_path).resolve() / STORAGE_DIR / GRAPH_FILENAME

    def load(self, project_path: str) -> GraphData | None:
        """Load and validate graph data from disk.

        Returns None when the file is missing or contains malformed /
        corrupted JSON.  A warning is logged in the corruption case so
        the caller can decide whether to re-initialise.
        """
        path = self._graph_path(project_path)

        if not path.is_file():
            return None

        try:
            raw = path.read_text(encoding="utf-8")
            payload = json.loads(raw)
            return GraphData.model_validate(payload)
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.warning(
                "Corrupted graph data at %s — ignoring and returning None: %s",
                path,
                exc,
            )
            return None

    def save(self, project_path: str, data: GraphData) -> None:
        """Serialize graph data to disk.

        Creates the ``.codegiraffe`` directory if it doesn't already exist.
        Writes atomically-enough for single-user CLI usage (write + flush).
        """
        path = self._graph_path(project_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        payload = data.model_dump(mode="json")
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def exists(self, project_path: str) -> bool:
        """Check whether the graph JSON file exists on disk."""
        return self._graph_path(project_path).is_file()

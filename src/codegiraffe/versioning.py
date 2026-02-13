"""Schema evolution and versioning for Code Giraffe architecture graphs.

Tracks changes between graph states as diffs and maintains a version history
persisted as JSON in the .codegiraffe directory.  Each version records which
nodes/edges were added or removed and which node attributes changed, enabling
audit trails and rollback analysis.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from codegiraffe.graph import GraphData

logger = logging.getLogger(__name__)

# Fields on Node that we track for attribute-level change detection.
_TRACKED_ATTRS = ("type", "label", "file_path", "manual")


@dataclass
class GraphDiff:
    """Diff between two graph states."""

    nodes_added: list[str] = field(default_factory=list)
    nodes_removed: list[str] = field(default_factory=list)
    edges_added: list[tuple[str, str, str]] = field(default_factory=list)
    edges_removed: list[tuple[str, str, str]] = field(default_factory=list)
    attrs_changed: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)

    # -- serialization -------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary.

        Edge tuples are serialized as three-element lists so the result is
        valid JSON (JSON has no tuple type).
        """
        return {
            "nodes_added": self.nodes_added,
            "nodes_removed": self.nodes_removed,
            "edges_added": [list(e) for e in self.edges_added],
            "edges_removed": [list(e) for e in self.edges_removed],
            "attrs_changed": self.attrs_changed,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GraphDiff:
        """Deserialize from a dictionary, converting edge lists back to tuples."""
        return cls(
            nodes_added=data.get("nodes_added", []),
            nodes_removed=data.get("nodes_removed", []),
            edges_added=[tuple(e) for e in data.get("edges_added", [])],
            edges_removed=[tuple(e) for e in data.get("edges_removed", [])],
            attrs_changed=data.get("attrs_changed", {}),
        )


@dataclass
class GraphVersion:
    """A version entry in the graph history."""

    version_id: int
    timestamp: str
    message: str
    diff: GraphDiff

    # -- serialization -------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "timestamp": self.timestamp,
            "message": self.message,
            "diff": self.diff.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GraphVersion:
        return cls(
            version_id=data["version_id"],
            timestamp=data["timestamp"],
            message=data["message"],
            diff=GraphDiff.from_dict(data["diff"]),
        )


class VersionStore:
    """Manages graph version history with file-based persistence.

    Versions are stored in ``{project_path}/.codegiraffe/versions.json`` and
    automatically pruned to *max_versions* entries (keeping the most recent).
    """

    FILENAME = "versions.json"

    def __init__(self, max_versions: int = 100) -> None:
        self.max_versions = max_versions

    # -- path helpers --------------------------------------------------------

    def _path(self, project_path: str) -> Path:
        return Path(project_path).resolve() / ".codegiraffe" / self.FILENAME

    # -- persistence ---------------------------------------------------------

    def load_versions(self, project_path: str) -> list[GraphVersion]:
        """Load all versions from disk.

        Returns an empty list when the file is missing or contains
        malformed JSON.
        """
        path = self._path(project_path)
        if not path.is_file():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return [GraphVersion.from_dict(entry) for entry in raw]
        except (json.JSONDecodeError, TypeError, KeyError, ValueError) as exc:
            logger.warning(
                "Corrupted version history at %s — returning empty: %s",
                path,
                exc,
            )
            return []

    def save_versions(self, project_path: str, versions: list[GraphVersion]) -> None:
        """Persist the version list to disk, creating the directory if needed."""
        path = self._path(project_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps([v.to_dict() for v in versions], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    # -- diffing -------------------------------------------------------------

    def compute_diff(self, old_data: GraphData, new_data: GraphData) -> GraphDiff:
        """Compare two GraphData instances and return their diff.

        * nodes_added / nodes_removed — set difference on node IDs
        * edges_added / edges_removed — set difference on (source, target, type)
        * attrs_changed — for nodes present in both, any changed tracked fields
        """
        old_ids = set(old_data.nodes.keys())
        new_ids = set(new_data.nodes.keys())

        nodes_added = sorted(new_ids - old_ids)
        nodes_removed = sorted(old_ids - new_ids)

        # Edge identity is (source, target, type)
        old_edge_keys = {(e.source, e.target, e.type) for e in old_data.edges}
        new_edge_keys = {(e.source, e.target, e.type) for e in new_data.edges}

        edges_added = sorted(new_edge_keys - old_edge_keys)
        edges_removed = sorted(old_edge_keys - new_edge_keys)

        # Attribute changes on common nodes
        attrs_changed: dict[str, dict[str, dict[str, Any]]] = {}
        common_ids = old_ids & new_ids
        for nid in sorted(common_ids):
            old_node = old_data.nodes[nid]
            new_node = new_data.nodes[nid]
            changes: dict[str, dict[str, Any]] = {}
            for attr in _TRACKED_ATTRS:
                old_val = getattr(old_node, attr)
                new_val = getattr(new_node, attr)
                if old_val != new_val:
                    changes[attr] = {"old": old_val, "new": new_val}
            if changes:
                attrs_changed[nid] = changes

        return GraphDiff(
            nodes_added=nodes_added,
            nodes_removed=nodes_removed,
            edges_added=edges_added,
            edges_removed=edges_removed,
            attrs_changed=attrs_changed,
        )

    # -- version management --------------------------------------------------

    def add_version(
        self,
        project_path: str,
        old_data: GraphData,
        new_data: GraphData,
        message: str,
    ) -> GraphVersion:
        """Create a new version entry, append to history, and prune if needed.

        Auto-increments the version ID based on the current maximum.
        Timestamps in UTC ISO-8601 format.
        """
        versions = self.load_versions(project_path)

        next_id = (max(v.version_id for v in versions) + 1) if versions else 1
        timestamp = datetime.now(timezone.utc).isoformat()
        diff = self.compute_diff(old_data, new_data)

        version = GraphVersion(
            version_id=next_id,
            timestamp=timestamp,
            message=message,
            diff=diff,
        )
        versions.append(version)

        # Prune oldest versions if over the limit
        if len(versions) > self.max_versions:
            versions = versions[-self.max_versions :]

        self.save_versions(project_path, versions)
        return version

    def get_version(self, project_path: str, version_id: int) -> GraphVersion | None:
        """Retrieve a single version by its ID, or None if not found."""
        for v in self.load_versions(project_path):
            if v.version_id == version_id:
                return v
        return None

    def get_history(self, project_path: str) -> list[dict[str, Any]]:
        """Return a list of summary dicts for each version in the history.

        Each summary includes version_id, timestamp, message, and counts
        of nodes/edges added/removed and the number of nodes with attribute
        changes.
        """
        versions = self.load_versions(project_path)
        summaries: list[dict[str, Any]] = []
        for v in versions:
            summaries.append({
                "version_id": v.version_id,
                "timestamp": v.timestamp,
                "message": v.message,
                "nodes_added": len(v.diff.nodes_added),
                "nodes_removed": len(v.diff.nodes_removed),
                "edges_added": len(v.diff.edges_added),
                "edges_removed": len(v.diff.edges_removed),
                "attrs_changed": len(v.diff.attrs_changed),
            })
        return summaries

"""Recognizer for legacy ``packages.config`` files (NuGet, .NET Framework)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from codegiraffe.graph import Edge, Node
from codegiraffe.scanner import ScanResult
from codegiraffe.schema import EdgeType, NodeType


class PackagesConfigRecognizer:
    """Recognizer for legacy ``packages.config`` NuGet manifests.

    Only processes files whose name is exactly ``packages.config``.  For any
    other ``.config`` file the recognizer returns an empty :class:`ScanResult`.

    Associates packages with the project by looking for a ``.csproj`` file in
    the same directory as the ``packages.config``.  If no sibling ``.csproj``
    is found, a generic source project node is inferred from the directory name.

    Emits:
    - A ``module`` node for the owning project (if not already present).
    - ``depends_on`` edges for each ``<package>`` element.
    """

    def recognize(self, file_path: Path, content: str) -> ScanResult:
        """Scan *content* of a ``packages.config`` file and return nodes/edges."""
        # Only handle files literally named "packages.config".
        if Path(file_path).name.lower() != "packages.config":
            return ScanResult()

        nodes: list[Node] = []
        edges: list[Edge] = []
        rel_path = file_path.as_posix()

        # Determine owning project by finding a sibling .csproj in the same dir.
        parent_dir = Path(file_path).parent
        project_name = self._find_project_name(parent_dir)
        project_id = f"mod:{project_name}"

        # Emit a stub project node so the graph has a source for these edges.
        # The CsprojRecognizer will fill in richer metadata when the .csproj
        # itself is scanned; ScanResult.merge() will do an additive metadata merge.
        project_node = Node(
            id=project_id,
            type=NodeType.MODULE,
            label=project_name,
            file_path=rel_path,
            metadata={"kind": "project", "language": "csharp"},
        )
        nodes.append(project_node)

        # Parse packages.config XML.
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            return ScanResult(nodes=nodes, edges=edges)

        for elem in root.iter():
            # Strip potential namespace prefix.
            local = elem.tag
            if local.startswith("{"):
                local = local.split("}", 1)[1]
            if local != "package":
                continue

            pkg_id = (elem.get("id") or "").strip()
            if not pkg_id:
                continue
            version = (elem.get("version") or "").strip()

            target_id = f"mod:{pkg_id}"
            meta: dict = {"reference_type": "nuget"}
            if version:
                meta["version"] = version

            edges.append(
                Edge(
                    source=project_id,
                    target=target_id,
                    type=EdgeType.DEPENDS_ON,
                    metadata=meta,
                )
            )

        return ScanResult(nodes=nodes, edges=edges)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_project_name(directory: Path) -> str:
        """Return assembly name from the nearest sibling ``.csproj`` or fall back
        to the directory name."""
        # Look for .csproj files in the same directory (not recursively).
        try:
            csproj_files = list(directory.glob("*.csproj"))
        except OSError:
            csproj_files = []

        if csproj_files:
            # Prefer a .csproj whose stem matches the directory name.
            dir_name = directory.name
            for f in csproj_files:
                if f.stem == dir_name:
                    return f.stem
            # Fallback: use the first one found.
            return csproj_files[0].stem

        # No .csproj found — use the parent directory name as a best guess.
        return directory.name or "Unknown"

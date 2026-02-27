"""Recognizer for .csproj files — emits project module nodes and NuGet/project-reference edges."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from codegiraffe.graph import Edge, Node
from codegiraffe.scanner import ScanResult
from codegiraffe.schema import EdgeType, NodeType

# MSBuild XML namespace used by old-style (non-SDK) .csproj files.
_MSBUILD_NS = "http://schemas.microsoft.com/developer/msbuild/2003"


def _strip_ns(tag: str) -> str:
    """Strip an XML namespace prefix from an element tag name."""
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def _find_text(root: ET.Element, *local_names: str) -> str | None:
    """Search *root* (and all descendants) for the first element whose local
    tag name matches any of *local_names*.  Returns its text or ``None``."""
    for elem in root.iter():
        if _strip_ns(elem.tag) in local_names:
            if elem.text and elem.text.strip():
                return elem.text.strip()
    return None


def _iter_elements(root: ET.Element, local_name: str):
    """Yield all descendant elements whose local tag name equals *local_name*."""
    for elem in root.iter():
        if _strip_ns(elem.tag) == local_name:
            yield elem


class CsprojRecognizer:
    """Recognizer for SDK-style and old-style ``.csproj`` project files.

    Emits:
    - A ``project`` node for the project itself (``project:{AssemblyName}``).
    - ``depends_on`` edges to ``mod:{PackageName}`` for each ``<PackageReference>`` (NuGet).
    - ``depends_on`` edges to ``project:{RefName}`` for each ``<ProjectReference>``
      (project-to-project).

    Both SDK-style projects (``<Project Sdk="Microsoft.NET.Sdk">``) and
    legacy MSBuild projects (with ``xmlns="http://schemas.microsoft.com/developer/msbuild/2003"``)
    are supported.
    """

    def recognize(self, file_path: Path, content: str) -> ScanResult:
        """Scan *content* of a ``.csproj`` file and return discovered nodes/edges."""
        nodes: list[Node] = []
        edges: list[Edge] = []
        rel_path = file_path.as_posix()

        # Derive assembly name from the filename stem.
        assembly_name = Path(file_path).stem
        project_id = f"project:{assembly_name}"

        # Parse XML — tolerate broken files gracefully.
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            return ScanResult()

        # Extract target framework.
        target_framework = _find_text(root, "TargetFramework", "TargetFrameworks")

        project_node = Node(
            id=project_id,
            type=NodeType.PROJECT,
            label=assembly_name,
            file_path=rel_path,
            metadata={
                "language": "csharp",
                **({"target_framework": target_framework} if target_framework else {}),
            },
        )
        nodes.append(project_node)

        # --- PackageReference (SDK-style NuGet dependencies) ---
        for elem in _iter_elements(root, "PackageReference"):
            pkg_id = elem.get("Include") or elem.get("include")
            if not pkg_id:
                continue
            pkg_id = pkg_id.strip()
            version = (elem.get("Version") or elem.get("version") or "").strip()
            # NuGet packages are external modules, not project nodes.
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

        # --- ProjectReference (project-to-project dependencies) ---
        for elem in _iter_elements(root, "ProjectReference"):
            include_path = elem.get("Include") or elem.get("include")
            if not include_path:
                continue
            include_path = include_path.strip()
            # Derive assembly name from the path: strip dir and .csproj extension.
            ref_name = Path(include_path.replace("\\", "/")).stem
            if not ref_name:
                continue
            # Peer projects use the project: prefix.
            target_id = f"project:{ref_name}"
            edges.append(
                Edge(
                    source=project_id,
                    target=target_id,
                    type=EdgeType.DEPENDS_ON,
                    metadata={"reference_type": "project_reference"},
                )
            )

        return ScanResult(nodes=nodes, edges=edges)

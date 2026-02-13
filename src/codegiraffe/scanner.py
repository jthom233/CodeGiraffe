"""Codebase scanner for discovering architectural entities and relationships.

Scans Python source files using regex-based pattern matching to discover
architectural nodes (endpoints, database tables, workers, env vars, external
APIs, services) and edges (reads, writes, calls) between them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from codegiraffe.graph import Edge, Node
from codegiraffe.types import EdgeType, NodeType

# ---------------------------------------------------------------------------
# Scan result container
# ---------------------------------------------------------------------------


@dataclass
class ScanResult:
    """Aggregated output from scanning: discovered nodes and edges."""

    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)

    def merge(self, other: ScanResult) -> None:
        """Merge another ScanResult into this one, deduplicating by node id."""
        seen_node_ids = {n.id for n in self.nodes}
        for node in other.nodes:
            if node.id not in seen_node_ids:
                self.nodes.append(node)
                seen_node_ids.add(node.id)

        seen_edges = {(e.source, e.target, e.type) for e in self.edges}
        for edge in other.edges:
            key = (edge.source, edge.target, edge.type)
            if key not in seen_edges:
                self.edges.append(edge)
                seen_edges.add(key)


# ---------------------------------------------------------------------------
# Recognizer protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class PatternRecognizer(Protocol):
    """Interface for pattern recognizers that extract nodes/edges from source."""

    def recognize(self, file_path: Path, content: str) -> ScanResult: ...


# ---------------------------------------------------------------------------
# Compiled regex patterns
# ---------------------------------------------------------------------------

# Flask / FastAPI route decorators
# Matches: @app.route("/path"), @app.get("/path"), @router.post("/path"), etc.
_ROUTE_DECORATOR_RE = re.compile(
    r"""@\s*(?:\w+)\s*\.\s*(?:route|get|post|put|delete|patch|head|options)\s*\(\s*["']([^"']+)["']""",
    re.VERBOSE,
)

# SQLAlchemy model classes
# Matches: class User(Base):, class User(db.Model):
_SQLALCHEMY_MODEL_RE = re.compile(
    r"""^class\s+(\w+)\s*\(\s*(?:.*?\b(?:Base|db\.Model)\b.*?)\s*\)\s*:""",
    re.MULTILINE,
)

# SQLAlchemy __tablename__
_TABLENAME_RE = re.compile(
    r"""__tablename__\s*=\s*["'](\w+)["']""",
)

# Celery task decorators
# Matches: @app.task, @shared_task, @celery.task, with optional parentheses
_CELERY_TASK_RE = re.compile(
    r"""@\s*(?:(?:\w+)\s*\.\s*task|shared_task)\s*(?:\(.*?\))?\s*\n\s*(?:async\s+)?def\s+(\w+)""",
    re.DOTALL,
)

# Environment variable access
# Matches: os.environ["KEY"], os.environ.get("KEY"), os.getenv("KEY")
_ENV_VAR_RE = re.compile(
    r"""os\s*\.\s*(?:environ\s*(?:\[\s*["'](\w+)["']\s*\]|\.get\s*\(\s*["'](\w+)["'])|getenv\s*\(\s*["'](\w+)["'])""",
)

# External API calls via requests library
# Matches: requests.get("url"), requests.post("url"), etc.
_REQUESTS_CALL_RE = re.compile(
    r"""requests\s*\.\s*(?:get|post|put|delete|patch|head|options)\s*\(\s*["']([^"']+)["']""",
)

# Also catch requests calls with f-strings or variables containing a URL-like string
_REQUESTS_CALL_FSTRING_RE = re.compile(
    r"""requests\s*\.\s*(?:get|post|put|delete|patch|head|options)\s*\(\s*f?["']([^"']*https?://[^"']+)["']""",
)

# Class definitions (fallback to service nodes)
_CLASS_DEF_RE = re.compile(
    r"""^class\s+(\w+)\s*(?:\(.*?\))?\s*:""",
    re.MULTILINE,
)

# Import of a model name (used for edge inference)
_MODEL_REF_RE_TEMPLATE = r"""\b{model_name}\b"""

# ---------------------------------------------------------------------------
# Directories and files to skip
# ---------------------------------------------------------------------------

_IGNORE_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        ".env",
        ".codegiraffe",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
        "*.egg-info",
    }
)


def _should_skip(path: Path) -> bool:
    """Return True if any component of *path* matches an ignore pattern."""
    for part in path.parts:
        if part in _IGNORE_DIRS or part.endswith(".egg-info"):
            return True
    return False


# ---------------------------------------------------------------------------
# Python recognizer
# ---------------------------------------------------------------------------


class PythonRecognizer:
    """Recognizes common Python architectural patterns via regex.

    Detected patterns:
        - Flask / FastAPI route decorators  -> ``endpoint`` nodes
        - SQLAlchemy model classes          -> ``database_table`` nodes
        - Celery task decorators            -> ``worker`` nodes
        - ``os.environ`` / ``os.getenv``    -> ``env_var`` nodes
        - ``requests.*`` HTTP calls         -> ``external_api`` nodes
        - Plain class definitions           -> ``service`` nodes (fallback)

    Inferred edges:
        - Files containing both an endpoint and a reference to a DB model
          produce ``reads`` or ``writes`` edges between the endpoint and
          the table node.
    """

    def recognize(self, file_path: Path, content: str) -> ScanResult:
        """Scan *content* of a Python file and return discovered nodes/edges."""
        nodes: list[Node] = []
        edges: list[Edge] = []
        rel_path = str(file_path)

        endpoint_ids: list[str] = []
        table_ids: list[str] = []
        table_class_names: list[str] = []

        # --- Endpoints (Flask / FastAPI) ---
        for match in _ROUTE_DECORATOR_RE.finditer(content):
            route_path = match.group(1)
            node_id = f"endpoint:{route_path}"
            nodes.append(
                Node(
                    id=node_id,
                    type=NodeType.ENDPOINT,
                    label=route_path,
                    file_path=rel_path,
                    metadata={"route": route_path},
                )
            )
            endpoint_ids.append(node_id)

        # --- Database tables (SQLAlchemy) ---
        for match in _SQLALCHEMY_MODEL_RE.finditer(content):
            class_name = match.group(1)
            # Try to find __tablename__ in the class body
            tablename_match = _TABLENAME_RE.search(content)
            table_name = tablename_match.group(1) if tablename_match else class_name.lower()
            node_id = f"table:{table_name}"
            nodes.append(
                Node(
                    id=node_id,
                    type=NodeType.DATABASE_TABLE,
                    label=table_name,
                    file_path=rel_path,
                    metadata={
                        "class_name": class_name,
                        "table_name": table_name,
                    },
                )
            )
            table_ids.append(node_id)
            table_class_names.append(class_name)

        # --- Celery tasks ---
        for match in _CELERY_TASK_RE.finditer(content):
            func_name = match.group(1)
            node_id = f"worker:{func_name}"
            nodes.append(
                Node(
                    id=node_id,
                    type=NodeType.WORKER,
                    label=func_name,
                    file_path=rel_path,
                    metadata={"function": func_name},
                )
            )

        # --- Environment variables ---
        seen_env_vars: set[str] = set()
        for match in _ENV_VAR_RE.finditer(content):
            # Groups: (1) environ["KEY"], (2) environ.get("KEY"), (3) getenv("KEY")
            var_name = match.group(1) or match.group(2) or match.group(3)
            if var_name and var_name not in seen_env_vars:
                seen_env_vars.add(var_name)
                node_id = f"env:{var_name}"
                nodes.append(
                    Node(
                        id=node_id,
                        type=NodeType.ENV_VAR,
                        label=var_name,
                        file_path=rel_path,
                        metadata={"variable": var_name},
                    )
                )

        # --- External API calls (requests library) ---
        seen_urls: set[str] = set()
        for pattern in (_REQUESTS_CALL_RE, _REQUESTS_CALL_FSTRING_RE):
            for match in pattern.finditer(content):
                url = match.group(1)
                if url not in seen_urls:
                    seen_urls.add(url)
                    node_id = f"api:{url}"
                    nodes.append(
                        Node(
                            id=node_id,
                            type=NodeType.EXTERNAL_API,
                            label=url,
                            file_path=rel_path,
                            metadata={"url": url},
                        )
                    )

        # --- Class definitions (fallback to service nodes) ---
        # Only classes that weren't already captured as SQLAlchemy models
        matched_class_names = set(table_class_names)
        for match in _CLASS_DEF_RE.finditer(content):
            class_name = match.group(1)
            if class_name not in matched_class_names:
                node_id = f"service:{class_name}"
                nodes.append(
                    Node(
                        id=node_id,
                        type=NodeType.SERVICE,
                        label=class_name,
                        file_path=rel_path,
                        metadata={"class_name": class_name},
                    )
                )

        # --- Edge inference: endpoint -> database_table ---
        # If a file has endpoints and references a DB model class name,
        # infer a reads/writes edge.
        if endpoint_ids and table_class_names:
            # Tables defined in the same file get writes edges
            for ep_id in endpoint_ids:
                for tbl_id in table_ids:
                    edges.append(
                        Edge(
                            source=ep_id,
                            target=tbl_id,
                            type=EdgeType.READS,
                            metadata={"inferred": True},
                        )
                    )

        # Cross-file reference inference is handled during merge
        # (see _infer_cross_file_edges below).

        return ScanResult(nodes=nodes, edges=edges)


# ---------------------------------------------------------------------------
# Cross-file edge inference
# ---------------------------------------------------------------------------


def _infer_cross_file_edges(
    result: ScanResult,
    file_contents: dict[Path, str],
) -> None:
    """Infer edges between endpoints and DB tables across files.

    For each endpoint node, check if any file that defines that endpoint
    also references the class name of a DB table defined elsewhere.
    """
    # Build lookup: table class_name -> table node id
    table_class_to_id: dict[str, str] = {}
    for node in result.nodes:
        if node.type == NodeType.DATABASE_TABLE:
            class_name = node.metadata.get("class_name")
            if class_name:
                table_class_to_id[class_name] = node.id

    if not table_class_to_id:
        return

    # Build lookup: file_path -> endpoint node ids
    endpoint_by_file: dict[str, list[str]] = {}
    for node in result.nodes:
        if node.type == NodeType.ENDPOINT and node.file_path:
            endpoint_by_file.setdefault(node.file_path, []).append(node.id)

    # Table node ids that were already connected by same-file inference
    existing_edges = {(e.source, e.target, e.type) for e in result.edges}

    # For each file containing endpoints, check for model references
    for fpath_str, ep_ids in endpoint_by_file.items():
        fpath = Path(fpath_str)
        content = file_contents.get(fpath, "")
        if not content:
            continue

        for class_name, table_id in table_class_to_id.items():
            if re.search(rf"\b{re.escape(class_name)}\b", content):
                for ep_id in ep_ids:
                    edge_key = (ep_id, table_id, EdgeType.READS)
                    if edge_key not in existing_edges:
                        result.edges.append(
                            Edge(
                                source=ep_id,
                                target=table_id,
                                type=EdgeType.READS,
                                metadata={"inferred": True, "cross_file": True},
                            )
                        )
                        existing_edges.add(edge_key)


# ---------------------------------------------------------------------------
# Project scanner
# ---------------------------------------------------------------------------


def scan_project(
    project_path: str,
    recognizers: list[PatternRecognizer] | None = None,
) -> ScanResult:
    """Walk *project_path* and scan every ``.py`` file for architectural patterns.

    Parameters
    ----------
    project_path:
        Root directory of the project to scan.
    recognizers:
        Pattern recognizers to apply to each file. If ``None``, defaults to
        ``[PythonRecognizer()]``.

    Returns
    -------
    ScanResult
        Merged nodes and edges from all files and all recognizers.
    """
    if recognizers is None:
        recognizers = [PythonRecognizer()]

    root = Path(project_path)
    merged = ScanResult()
    file_contents: dict[Path, str] = {}

    for py_file in sorted(root.rglob("*.py")):
        if _should_skip(py_file):
            continue

        try:
            content = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        # Store content for cross-file inference later
        rel_path = py_file.relative_to(root)
        file_contents[rel_path] = content

        for recognizer in recognizers:
            file_result = recognizer.recognize(rel_path, content)
            merged.merge(file_result)

    # Second pass: infer cross-file edges
    _infer_cross_file_edges(merged, file_contents)

    return merged

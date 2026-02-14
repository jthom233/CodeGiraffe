"""Codebase scanner for discovering architectural entities and relationships.

Scans Python source files using regex-based pattern matching to discover
architectural nodes (endpoints, database tables, workers, env vars, external
APIs, services) and edges (reads, writes, calls) between them.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from codegiraffe.graph import Edge, Node

if TYPE_CHECKING:
    from codegiraffe.registry import RecognizerRegistry
from codegiraffe.schema import EdgeType, NodeType

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
    r"""^class\s+(\w+)(?:\(([^)]*?)\))?\s*:""",
    re.MULTILINE,
)

# Import of a model name (used for edge inference)
_MODEL_REF_RE_TEMPLATE = r"""\b{model_name}\b"""

# Python import statements
# Group 1: 'from X import Y' -> module path, Group 2: imported names
# Group 3: 'import X' -> module path(s)
_IMPORT_RE = re.compile(
    r"""^(?:from\s+([\w.]+)\s+import\s+(.+)|import\s+([\w.]+(?:\s*,\s*[\w.]+)*))""",
    re.MULTILINE,
)

# Relative imports: from . import X, from ..X import Y
_RELATIVE_IMPORT_RE = re.compile(
    r"""^from\s+(\.+)([\w.]*)\s+import\s+(.+)""",
    re.MULTILINE,
)

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

# Directory names that indicate test code
_TEST_DIRS: frozenset[str] = frozenset({"tests", "test"})


def _file_to_module_path(file_path: Path, project_path: str) -> str:
    """Convert an absolute file path to a dotted Python module path.

    Handles src-layout (strips everything up to and including ``src/``),
    flat-layout (uses path relative to *project_path*), and ``__init__.py``
    files (returns the package name without ``.__init__``).

    Examples
    --------
    >>> _file_to_module_path(Path("/proj/src/pkg/mod.py"), "/proj")
    'pkg.mod'
    >>> _file_to_module_path(Path("/proj/src/pkg/__init__.py"), "/proj")
    'pkg'
    """
    rel = file_path.relative_to(project_path)
    parts = list(rel.parts)

    # Strip leading 'src' directory if present (src-layout)
    if parts and parts[0] == "src":
        parts = parts[1:]

    # Remove .py / .pyi extension from the last component
    if parts:
        stem = Path(parts[-1]).stem
        parts[-1] = stem

    # If the last component is __init__, drop it (package, not sub-module)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]

    return ".".join(parts)


def _is_test_file(file_path: Path) -> bool:
    """Return True if *file_path* looks like a test file.

    Matches: ``test_*.py``, ``*_test.py``, ``conftest.py``.
    """
    name = file_path.name
    if name == "conftest.py":
        return True
    if name.startswith("test_") and name.endswith(".py"):
        return True
    if name.endswith("_test.py"):
        return True
    return False


def _should_skip(path: Path) -> bool:
    """Return True if any component of *path* matches an ignore pattern."""
    for part in path.parts:
        if part in _IGNORE_DIRS or part.endswith(".egg-info"):
            return True
    return False


def _is_in_test_dir(path: Path) -> bool:
    """Return True if any component of *path* is a test directory."""
    for part in path.parts:
        if part in _TEST_DIRS:
            return True
    return False


def _strip_strings_and_comments(text: str) -> str:
    """Remove strings and comments to prevent false-positive pattern matches.

    Processing order matters -- triple-quoted strings have highest precedence,
    then single-line comments, then regular quoted strings.
    """
    # Remove triple-quoted strings first (highest precedence)
    text = re.sub(r'"""[\s\S]*?"""', '', text)
    text = re.sub(r"'''[\s\S]*?'''", '', text)
    # Remove single-line comments
    text = re.sub(r'#[^\n]*', '', text)
    # Remove quoted strings (handles basic escapes)
    text = re.sub(r'"(?:\\.|[^"\\])*"', '', text)
    text = re.sub(r"'(?:\\.|[^'\\])*'", '', text)
    return text


def _strip_docstrings_and_comments(text: str) -> str:
    """Remove triple-quoted strings and comments only.

    Unlike :func:`_strip_strings_and_comments`, this preserves regular
    single/double-quoted strings so that patterns matching on quoted
    arguments (routes, env vars, API URLs) still work.
    """
    # Remove triple-quoted strings first (highest precedence)
    text = re.sub(r'"""[\s\S]*?"""', '', text)
    text = re.sub(r"'''[\s\S]*?'''", '', text)
    # Remove single-line comments
    text = re.sub(r'#[^\n]*', '', text)
    return text


# ---------------------------------------------------------------------------
# Import resolution
# ---------------------------------------------------------------------------


def _resolve_import(
    import_path: str,
    current_file: Path,
    project_path: str,
    project_modules: set[str],
    dot_count: int = 0,
) -> str | None:
    """Resolve an import to a project-internal dotted module path.

    Returns None for stdlib and third-party imports.
    """
    if dot_count > 0:
        # Relative import: resolve from current file's package
        current_module = _file_to_module_path(current_file, project_path)
        parts = current_module.split(".")
        # Remove dot_count levels (go up that many packages)
        base_parts = parts[: max(0, len(parts) - dot_count)]
        if import_path:
            resolved = (
                ".".join(base_parts + [import_path]) if base_parts else import_path
            )
        else:
            resolved = ".".join(base_parts)
        return resolved if resolved in project_modules else None

    # Absolute import
    top_level = import_path.split(".")[0]

    # Check stdlib
    if top_level in sys.stdlib_module_names:
        return None

    # Check if it's a project module
    if import_path in project_modules:
        return import_path

    # Check if any project module starts with this path (package import)
    for mod in project_modules:
        if mod == import_path or mod.startswith(import_path + "."):
            return import_path

    return None  # Third-party


# ---------------------------------------------------------------------------
# Import edge inference
# ---------------------------------------------------------------------------


def _infer_import_edges(
    result: ScanResult,
    file_contents: dict[Path, str],
    project_path: str,
) -> None:
    """Parse import statements and create imports edges between module nodes.

    For each Python file, extracts absolute and relative imports, resolves
    them to project-internal modules, and creates ``imports`` edges with
    metadata containing the imported symbol names and import style.
    """
    # T034: Build the set of all project-internal module paths
    project_modules: set[str] = set()
    for node in result.nodes:
        if node.type == NodeType.MODULE.value:
            module_path = node.id.removeprefix("mod:")
            project_modules.add(module_path)

    if not project_modules:
        return

    # Build lookup: relative file path -> module path
    file_to_module: dict[Path, str] = {}
    for node in result.nodes:
        if node.type == NodeType.MODULE.value and node.file_path:
            file_to_module[Path(node.file_path)] = node.id.removeprefix("mod:")

    # Collect import edges per (source_module, target_module) for deduplication
    # Key: (source_mod_id, target_mod_id) -> metadata dict
    import_map: dict[tuple[str, str], dict] = {}

    for rel_path, content in file_contents.items():
        source_module = file_to_module.get(rel_path)
        if source_module is None:
            continue

        source_mod_id = f"mod:{source_module}"

        # Strip comments to avoid false matches, but preserve import lines
        cleaned = _strip_docstrings_and_comments(content)

        # Process relative imports first (they are a subset of the from-import
        # pattern and would also match _IMPORT_RE, so we track which lines
        # we've already handled)
        relative_line_starts: set[int] = set()
        for match in _RELATIVE_IMPORT_RE.finditer(cleaned):
            relative_line_starts.add(match.start())
            dots = match.group(1)
            import_path = match.group(2) or ""
            names_str = match.group(3)

            dot_count = len(dots)
            names = [
                s.strip().split(" as ")[0].strip()
                for s in names_str.split(",")
                if s.strip()
            ]

            if import_path:
                # from .pkg import X -- resolve pkg relative to current
                resolved = _resolve_import(
                    import_path,
                    Path(project_path) / rel_path,
                    project_path,
                    project_modules,
                    dot_count=dot_count,
                )
                if resolved is None:
                    continue

                target_mod_id = f"mod:{resolved}"
                if source_mod_id == target_mod_id:
                    continue

                key = (source_mod_id, target_mod_id)
                if key not in import_map:
                    import_map[key] = {"symbols": [], "style": "relative"}
                import_map[key]["symbols"].extend(names)
            else:
                # from . import X -- each name could be a sibling submodule
                for name in names:
                    resolved = _resolve_import(
                        name,
                        Path(project_path) / rel_path,
                        project_path,
                        project_modules,
                        dot_count=dot_count,
                    )
                    if resolved is None:
                        continue

                    target_mod_id = f"mod:{resolved}"
                    if source_mod_id == target_mod_id:
                        continue

                    key = (source_mod_id, target_mod_id)
                    if key not in import_map:
                        import_map[key] = {"symbols": [], "style": "relative"}
                    import_map[key]["symbols"].append(name)

        # Process absolute imports (from X import Y and import X)
        for match in _IMPORT_RE.finditer(cleaned):
            # Skip lines already handled as relative imports
            if match.start() in relative_line_starts:
                continue

            from_module = match.group(1)
            from_names = match.group(2)
            plain_import = match.group(3)

            if from_module:
                # 'from X import Y' style
                resolved = _resolve_import(
                    from_module,
                    Path(project_path) / rel_path,
                    project_path,
                    project_modules,
                )
                if resolved is None:
                    continue

                target_mod_id = f"mod:{resolved}"

                # Skip self-imports
                if source_mod_id == target_mod_id:
                    continue

                symbols = [
                    s.strip().split(" as ")[0].strip()
                    for s in from_names.split(",")
                    if s.strip()
                ]

                key = (source_mod_id, target_mod_id)
                if key not in import_map:
                    import_map[key] = {"symbols": [], "style": "absolute"}
                import_map[key]["symbols"].extend(symbols)

            elif plain_import:
                # 'import X' style
                for mod_name in plain_import.split(","):
                    mod_name = mod_name.strip().split(" as ")[0].strip()
                    resolved = _resolve_import(
                        mod_name,
                        Path(project_path) / rel_path,
                        project_path,
                        project_modules,
                    )
                    if resolved is None:
                        continue

                    target_mod_id = f"mod:{resolved}"

                    # Skip self-imports
                    if source_mod_id == target_mod_id:
                        continue

                    key = (source_mod_id, target_mod_id)
                    if key not in import_map:
                        import_map[key] = {"symbols": [], "style": "absolute"}
                    # Plain import has no specific symbols
                    import_map[key]["symbols"].append(mod_name.split(".")[-1])

    # Create edges from the deduplicated map
    for (source_id, target_id), meta in import_map.items():
        # Deduplicate symbols while preserving order
        seen: set[str] = set()
        unique_symbols: list[str] = []
        for s in meta["symbols"]:
            if s not in seen:
                seen.add(s)
                unique_symbols.append(s)

        result.edges.append(
            Edge(
                source=source_id,
                target=target_id,
                type=EdgeType.IMPORTS,
                metadata={
                    "symbols": unique_symbols,
                    "style": meta["style"],
                    "inferred": True,
                },
            )
        )


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

        # Strip docstrings and comments to prevent false-positive matches.
        # We preserve single/double-quoted strings because many patterns
        # (routes, env vars, API URLs) match on their quoted arguments.
        cleaned = _strip_docstrings_and_comments(content)

        endpoint_ids: list[str] = []
        table_ids: list[str] = []
        table_class_names: list[str] = []

        # --- Endpoints (Flask / FastAPI) ---
        for match in _ROUTE_DECORATOR_RE.finditer(cleaned):
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
        for match in _SQLALCHEMY_MODEL_RE.finditer(cleaned):
            class_name = match.group(1)
            # Try to find __tablename__ in the cleaned content
            tablename_match = _TABLENAME_RE.search(cleaned)
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
        for match in _CELERY_TASK_RE.finditer(cleaned):
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
        for match in _ENV_VAR_RE.finditer(cleaned):
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
            for match in pattern.finditer(cleaned):
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
        for match in _CLASS_DEF_RE.finditer(cleaned):
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
# Inheritance edge inference
# ---------------------------------------------------------------------------


def _infer_inheritance_edges(
    result: ScanResult,
    class_registry: dict[str, str],
    file_contents: dict[Path, str],
) -> None:
    """Create implements edges from subclasses to their base classes.

    For each class definition that specifies base classes, look up the base
    class name in *class_registry* (which maps class names to node IDs for
    classes discovered in the project).  If a base class is found in the
    registry, an ``implements`` edge is created from the child to the parent.

    External base classes (e.g., ``BaseModel`` from Pydantic) that are not
    defined in any project file are silently skipped.
    """
    existing_edges = {(e.source, e.target, e.type) for e in result.edges}

    for fpath, content in file_contents.items():
        # Use cleaned content (strip docstrings/comments)
        cleaned = _strip_docstrings_and_comments(content)
        for match in _CLASS_DEF_RE.finditer(cleaned):
            class_name = match.group(1)
            bases_str = match.group(2)  # May be None
            if not bases_str:
                continue

            child_id = class_registry.get(class_name)
            if not child_id:
                continue

            # Parse base classes (split by comma, strip whitespace)
            bases = [b.strip() for b in bases_str.split(",") if b.strip()]
            for base_name in bases:
                # Handle dotted names like db.Model -- use last component
                simple_name = base_name.split(".")[-1]
                parent_id = class_registry.get(simple_name)
                if parent_id and parent_id != child_id:
                    edge_key = (child_id, parent_id, EdgeType.IMPLEMENTS.value)
                    if edge_key not in existing_edges:
                        same_file = False
                        # Check if both are in same file
                        child_node = next(
                            (n for n in result.nodes if n.id == child_id), None
                        )
                        parent_node = next(
                            (n for n in result.nodes if n.id == parent_id), None
                        )
                        if child_node and parent_node:
                            same_file = child_node.file_path == parent_node.file_path

                        result.edges.append(
                            Edge(
                                source=child_id,
                                target=parent_id,
                                type=EdgeType.IMPLEMENTS.value,
                                metadata={
                                    "inferred": True,
                                    "cross_file": not same_file,
                                },
                            )
                        )
                        existing_edges.add(edge_key)


# ---------------------------------------------------------------------------
# Project scanner
# ---------------------------------------------------------------------------


def scan_project(
    project_path: str,
    recognizers: list[PatternRecognizer] | None = None,
    registry: RecognizerRegistry | None = None,
    include_tests: bool = False,
) -> ScanResult:
    """Walk *project_path* and scan files for architectural patterns.

    The scanner uses a :class:`RecognizerRegistry` to determine which files
    to scan and which recognizers to apply.  There are three ways to configure
    the scan:

    1. Provide a *registry* -- full control over extensions and recognizers.
    2. Provide *recognizers* (legacy) -- wraps them in a temporary registry
       that maps to ``.py`` / ``.pyi`` extensions for backward compatibility.
    3. Provide neither -- uses the default registry which includes the
       built-in ``PythonRecognizer`` for ``.py`` / ``.pyi`` files.

    Parameters
    ----------
    project_path:
        Root directory of the project to scan.
    recognizers:
        Legacy parameter.  Pattern recognizers to apply.  Ignored when
        *registry* is provided.
    registry:
        A :class:`RecognizerRegistry` that maps file extensions to
        recognizers.

    Returns
    -------
    ScanResult
        Merged nodes and edges from all files and all recognizers.
    """
    from codegiraffe.registry import RecognizerRegistry, get_default_registry

    if registry is not None:
        active_registry = registry
    elif recognizers is not None:
        # Legacy: wrap recognizers in a temporary registry
        active_registry = RecognizerRegistry()
        for r in recognizers:
            # For legacy recognizers without extension info, default to .py
            active_registry.register(r, extensions=[".py", ".pyi"])
    else:
        active_registry = get_default_registry()

    root = Path(project_path)
    merged = ScanResult()
    file_contents: dict[Path, str] = {}

    # Determine which extensions to scan
    extensions = active_registry.registered_extensions
    has_global = bool(active_registry._global_recognizers)

    for source_file in sorted(root.rglob("*")):
        if not source_file.is_file():
            continue
        if _should_skip(source_file):
            continue

        suffix = source_file.suffix.lower()
        if not has_global and suffix not in extensions:
            continue

        # Test file handling: skip or tag based on include_tests flag
        is_test = _is_test_file(source_file) or _is_in_test_dir(source_file)
        if is_test and not include_tests:
            continue

        applicable = active_registry.get_recognizers(source_file)
        if not applicable:
            continue

        try:
            content = source_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        # Store content for cross-file inference later
        rel_path = source_file.relative_to(root)
        file_contents[rel_path] = content

        # Collect all nodes/edges from recognizers for this file
        file_nodes: list[Node] = []
        file_edges: list[Edge] = []
        for recognizer in applicable:
            file_result = recognizer.recognize(rel_path, content)
            file_nodes.extend(file_result.nodes)
            file_edges.extend(file_result.edges)

        # Tag nodes from test files with source: test metadata
        if is_test and include_tests:
            for node in file_nodes:
                node.metadata["source"] = "test"

        # T050: Create module node for Python files
        if suffix in (".py", ".pyi"):
            module_path = _file_to_module_path(source_file, project_path)
            module_id = f"mod:{module_path}"
            module_label = module_path.rsplit(".", 1)[-1] if "." in module_path else module_path

            module_node = Node(
                id=module_id,
                type=NodeType.MODULE.value,
                label=module_label,
                file_path=str(rel_path),
                metadata={
                    "package": module_path.rsplit(".", 1)[0] if "." in module_path else "",
                    "source": "test" if is_test else "production",
                },
            )
            file_nodes.append(module_node)

            # T051: Create contains edges from module to all entities in this file
            for node in file_nodes:
                if node.id != module_id:
                    file_edges.append(Edge(
                        source=module_id,
                        target=node.id,
                        type=EdgeType.CONTAINS.value,
                        metadata={"inferred": True},
                    ))

        combined = ScanResult(nodes=file_nodes, edges=file_edges)
        merged.merge(combined)

    # Second pass: infer cross-file edges
    _infer_cross_file_edges(merged, file_contents)

    # Third pass: infer import edges between modules
    _infer_import_edges(merged, file_contents, project_path)

    # Build class registry for inheritance resolution
    class_registry: dict[str, str] = {}
    for node in merged.nodes:
        if node.type == NodeType.SERVICE.value:
            class_name = node.metadata.get("class_name") or node.label
            class_registry[class_name] = node.id

    # Third pass: infer inheritance edges
    _infer_inheritance_edges(merged, class_registry, file_contents)

    return merged

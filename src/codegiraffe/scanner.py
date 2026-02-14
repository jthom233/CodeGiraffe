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
# Structured data from recognizers
# ---------------------------------------------------------------------------


@dataclass
class ImportInfo:
    """Structured import information returned by recognizers."""

    module_path: str  # Dotted module path (project-relative)
    symbols: list[str] = field(default_factory=list)
    style: str = "absolute"  # "absolute" | "relative" | "wildcard"


@dataclass
class ImplementationInfo:
    """Structured inheritance/implementation info returned by recognizers."""

    child_class: str  # Name of the implementing class/struct
    parent_class: str  # Name of the base class/interface/trait
    file_path: str  # Relative path where child is defined


# ---------------------------------------------------------------------------
# Scan result container
# ---------------------------------------------------------------------------


@dataclass
class ScanResult:
    """Aggregated output from scanning: discovered nodes and edges."""

    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    imports: list[ImportInfo] = field(default_factory=list)
    implementations: list[ImplementationInfo] = field(default_factory=list)

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

        self.imports.extend(other.imports)
        self.implementations.extend(other.implementations)


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
_TEST_DIRS: frozenset[str] = frozenset({"tests", "test", "__tests__", "spec"})

# ---------------------------------------------------------------------------
# Language suffix mapping
# ---------------------------------------------------------------------------

_SUFFIX_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".go": "go",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".rs": "rust",
    ".java": "java",
    ".cs": "csharp",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".php": "php",
    ".rb": "ruby",
}


def _suffix_to_language(suffix: str) -> str:
    """Map a file suffix to a language name."""
    return _SUFFIX_TO_LANGUAGE.get(suffix, "unknown")


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


def _file_to_module_path_universal(file_path: Path, project_path: str, suffix: str) -> str:
    """Convert a file path to a dotted module path for any language."""
    if suffix in (".py", ".pyi"):
        return _file_to_module_path(file_path, project_path)

    rel = file_path.relative_to(project_path)
    parts = list(rel.parts)

    # Strip common source layout prefixes
    if parts and parts[0] in ("src", "lib", "app", "pkg", "cmd", "internal"):
        parts = parts[1:]

    # Remove extension from last component
    if parts:
        parts[-1] = Path(parts[-1]).stem

    return ".".join(parts)


def _is_test_file(file_path: Path) -> bool:
    """Return True if *file_path* looks like a test file for any language."""
    name = file_path.name
    suffix = file_path.suffix.lower()

    # Python-specific patterns (preserved from v0.4.0)
    if suffix in (".py", ".pyi"):
        if name == "conftest.py":
            return True
        if name.startswith("test_") and name.endswith(".py"):
            return True
        if name.endswith("_test.py"):
            return True
        return False

    # Go: *_test.go
    if suffix == ".go" and name.endswith("_test.go"):
        return True

    # TypeScript/JavaScript: *.test.ts, *.spec.ts, *.test.tsx, *.spec.tsx
    if suffix in (".ts", ".tsx", ".mts", ".cts"):
        base = name.rsplit(".", 1)[0] if "." in name else name
        if base.endswith((".test", ".spec")):
            return True

    # Java: *Test.java, *Tests.java
    if suffix == ".java":
        stem = Path(name).stem
        if stem.endswith(("Test", "Tests")):
            return True

    # C#: *Test.cs, *Tests.cs
    if suffix == ".cs":
        stem = Path(name).stem
        if stem.endswith(("Test", "Tests")):
            return True

    # C/C++: *_test.cpp, *_test.c, test_*.cpp, test_*.c
    if suffix in (".c", ".cpp", ".cc", ".cxx", ".h", ".hpp"):
        stem = Path(name).stem
        if stem.endswith("_test") or stem.startswith("test_"):
            return True

    # PHP: *Test.php
    if suffix == ".php":
        stem = Path(name).stem
        if stem.endswith("Test"):
            return True

    # Ruby: *_test.rb, *_spec.rb
    if suffix == ".rb":
        stem = Path(name).stem
        if stem.endswith(("_test", "_spec")):
            return True

    # Rust: no file naming convention, but tests/ dir handled by _is_in_test_dir
    return False


def _should_skip(path: Path) -> bool:
    """Return True if any component of *path* matches an ignore pattern."""
    for part in path.parts:
        if part in _IGNORE_DIRS or part.endswith(".egg-info"):
            return True
    return False


def _is_in_test_dir(path: Path) -> bool:
    """Return True if any component of *path* is a test directory."""
    parts = path.parts
    for i, part in enumerate(parts):
        if part in _TEST_DIRS:
            return True
        # Java: src/test/ directory
        if part == "src" and i + 1 < len(parts) and parts[i + 1] == "test":
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
# Universal inference (language-agnostic)
# ---------------------------------------------------------------------------


def _infer_import_edges_universal(
    result: ScanResult,
    per_file_results: dict[Path, ScanResult],
) -> None:
    """Create imports edges from recognizer-provided ImportInfo data."""
    module_ids: set[str] = {n.id for n in result.nodes if n.type == NodeType.MODULE.value}

    file_to_mod_id: dict[str, str] = {}
    for node in result.nodes:
        if node.type == NodeType.MODULE.value and node.file_path:
            file_to_mod_id[node.file_path] = node.id

    existing_edges = {(e.source, e.target, e.type) for e in result.edges}

    for rel_path, file_result in per_file_results.items():
        source_mod_id = file_to_mod_id.get(str(rel_path))
        if not source_mod_id or not file_result.imports:
            continue

        for imp in file_result.imports:
            target_mod_id = f"mod:{imp.module_path}"
            if target_mod_id not in module_ids:
                continue
            if source_mod_id == target_mod_id:
                continue

            edge_key = (source_mod_id, target_mod_id, EdgeType.IMPORTS.value)
            if edge_key not in existing_edges:
                result.edges.append(Edge(
                    source=source_mod_id,
                    target=target_mod_id,
                    type=EdgeType.IMPORTS.value,
                    metadata={
                        "symbols": imp.symbols,
                        "style": imp.style,
                        "inferred": True,
                    },
                ))
                existing_edges.add(edge_key)


def _infer_inheritance_edges_universal(
    result: ScanResult,
    per_file_results: dict[Path, ScanResult],
) -> None:
    """Create implements edges from recognizer-provided ImplementationInfo data."""
    class_registry: dict[str, str] = {}
    for node in result.nodes:
        if node.type == NodeType.SERVICE.value:
            class_name = node.metadata.get("class_name") or node.metadata.get("struct_name") or node.label
            class_registry[class_name] = node.id

    existing_edges = {(e.source, e.target, e.type) for e in result.edges}

    for rel_path, file_result in per_file_results.items():
        for impl in file_result.implementations:
            child_id = class_registry.get(impl.child_class)
            parent_id = class_registry.get(impl.parent_class)

            if not child_id or not parent_id or child_id == parent_id:
                continue

            edge_key = (child_id, parent_id, EdgeType.IMPLEMENTS.value)
            if edge_key not in existing_edges:
                child_node = next((n for n in result.nodes if n.id == child_id), None)
                parent_node = next((n for n in result.nodes if n.id == parent_id), None)
                same_file = (child_node and parent_node and
                             child_node.file_path == parent_node.file_path)

                result.edges.append(Edge(
                    source=child_id,
                    target=parent_id,
                    type=EdgeType.IMPLEMENTS.value,
                    metadata={
                        "inferred": True,
                        "cross_file": not same_file,
                    },
                ))
                existing_edges.add(edge_key)


# ---------------------------------------------------------------------------
# Contract inference
# ---------------------------------------------------------------------------


def _infer_api_contracts(result: ScanResult) -> None:
    """Infer API contracts from matching endpoint and external_api nodes.

    When an external_api node's URL contains a path that matches an endpoint
    node's path, a contract node with ``produces`` and ``consumes_contract``
    edges is created.
    """
    existing_node_ids = {n.id for n in result.nodes}
    existing_edges = {(e.source, e.target, e.type) for e in result.edges}

    # Collect endpoint nodes and extract their paths
    endpoints: list[tuple[Node, str]] = []
    for node in result.nodes:
        if node.type == NodeType.ENDPOINT.value:
            # Node id format: "endpoint:METHOD /path" or "endpoint:/path"
            raw = node.id
            if raw.startswith("endpoint:"):
                raw = raw[len("endpoint:"):]
            # Strip method prefix if present (e.g. "GET /api/users" -> "/api/users")
            parts = raw.strip().split(None, 1)
            path = parts[-1] if parts else raw
            if path:
                endpoints.append((node, path))

    # Collect external_api nodes and extract their URLs/paths
    externals: list[tuple[Node, str]] = []
    for node in result.nodes:
        if node.type == NodeType.EXTERNAL_API.value:
            url = node.label or node.id
            if url.startswith("external_api:"):
                url = url[len("external_api:"):]
            externals.append((node, url))

    for ep_node, ep_path in endpoints:
        consumers: list[Node] = []
        for ext_node, ext_url in externals:
            if ep_path in ext_url:
                consumers.append(ext_node)

        if not consumers:
            continue

        contract_id = f"contract:api:{ep_path}"
        if contract_id in existing_node_ids:
            continue

        contract_node = Node(
            id=contract_id,
            type=NodeType.CONTRACT.value,
            label=f"API: {ep_path}",
            metadata={
                "contract_type": "api",
                "producer": ep_node.id,
                "consumers": [c.id for c in consumers],
                "status": "active",
                "inferred": True,
            },
        )
        result.nodes.append(contract_node)
        existing_node_ids.add(contract_id)

        # Producer edge
        edge_key = (ep_node.id, contract_id, EdgeType.PRODUCES.value)
        if edge_key not in existing_edges:
            result.edges.append(Edge(
                source=ep_node.id,
                target=contract_id,
                type=EdgeType.PRODUCES.value,
                metadata={"inferred": True},
            ))
            existing_edges.add(edge_key)

        # Consumer edges
        for consumer in consumers:
            edge_key = (consumer.id, contract_id, EdgeType.CONSUMES_CONTRACT.value)
            if edge_key not in existing_edges:
                result.edges.append(Edge(
                    source=consumer.id,
                    target=contract_id,
                    type=EdgeType.CONSUMES_CONTRACT.value,
                    metadata={"inferred": True},
                ))
                existing_edges.add(edge_key)


def _infer_event_contracts(result: ScanResult) -> None:
    """Infer event contracts from event nodes with matching labels.

    Groups event nodes by label.  When two or more share the same label a
    contract is created.  If one of the nodes has an incoming ``publishes``
    edge it is treated as the producer; otherwise the first node is used.
    """
    existing_node_ids = {n.id for n in result.nodes}
    existing_edges = {(e.source, e.target, e.type) for e in result.edges}

    # Group event nodes by label
    event_groups: dict[str, list[Node]] = {}
    for node in result.nodes:
        if node.type == NodeType.EVENT.value:
            event_groups.setdefault(node.label, []).append(node)

    # Build lookup: nodes that have an incoming "publishes" edge
    publishers: set[str] = set()
    for edge in result.edges:
        if edge.type == EdgeType.PUBLISHES.value:
            # The *source* of a publishes edge is the publisher; the target is
            # the event.  But for producer detection we want the event node
            # that *receives* a publishes edge (i.e. the target).
            publishers.add(edge.target)

    for label, nodes in event_groups.items():
        if len(nodes) < 2:
            continue

        contract_id = f"contract:event:{label}"
        if contract_id in existing_node_ids:
            continue

        # Determine producer: prefer the node targeted by a publishes edge
        producer: Node | None = None
        for n in nodes:
            if n.id in publishers:
                producer = n
                break
        if producer is None:
            producer = nodes[0]

        consumers = [n for n in nodes if n.id != producer.id]

        contract_node = Node(
            id=contract_id,
            type=NodeType.CONTRACT.value,
            label=f"Event: {label}",
            metadata={
                "contract_type": "event",
                "producer": producer.id,
                "consumers": [c.id for c in consumers],
                "status": "active",
                "inferred": True,
            },
        )
        result.nodes.append(contract_node)
        existing_node_ids.add(contract_id)

        # Producer edge
        edge_key = (producer.id, contract_id, EdgeType.PRODUCES.value)
        if edge_key not in existing_edges:
            result.edges.append(Edge(
                source=producer.id,
                target=contract_id,
                type=EdgeType.PRODUCES.value,
                metadata={"inferred": True},
            ))
            existing_edges.add(edge_key)

        # Consumer edges
        for consumer in consumers:
            edge_key = (consumer.id, contract_id, EdgeType.CONSUMES_CONTRACT.value)
            if edge_key not in existing_edges:
                result.edges.append(Edge(
                    source=consumer.id,
                    target=contract_id,
                    type=EdgeType.CONSUMES_CONTRACT.value,
                    metadata={"inferred": True},
                ))
                existing_edges.add(edge_key)


def _infer_config_contracts(result: ScanResult) -> None:
    """Infer config contracts when an env_var is referenced by 2+ distinct services.

    Any edge whose source or target is an ``env_var`` node counts as a
    reference.  When two or more *distinct* source/target nodes reference the
    same env_var, a config contract is created.  The producer is the
    alphabetically first referencing node.
    """
    existing_node_ids = {n.id for n in result.nodes}
    existing_edges = {(e.source, e.target, e.type) for e in result.edges}

    env_vars: dict[str, Node] = {}
    for node in result.nodes:
        if node.type == NodeType.ENV_VAR.value:
            env_vars[node.id] = node

    if not env_vars:
        return

    # For each env_var, find distinct nodes connected to it via any edge
    for env_id, env_node in env_vars.items():
        referencing_nodes: set[str] = set()
        for edge in result.edges:
            if edge.source == env_id and edge.target != env_id:
                referencing_nodes.add(edge.target)
            elif edge.target == env_id and edge.source != env_id:
                referencing_nodes.add(edge.source)

        if len(referencing_nodes) < 2:
            continue

        label = env_node.label
        contract_id = f"contract:config:{label}"
        if contract_id in existing_node_ids:
            continue

        sorted_refs = sorted(referencing_nodes)
        producer_id = sorted_refs[0]
        consumer_ids = sorted_refs[1:]

        contract_node = Node(
            id=contract_id,
            type=NodeType.CONTRACT.value,
            label=f"Config: {label}",
            metadata={
                "contract_type": "config",
                "producer": producer_id,
                "consumers": consumer_ids,
                "status": "active",
                "inferred": True,
            },
        )
        result.nodes.append(contract_node)
        existing_node_ids.add(contract_id)

        edge_key = (producer_id, contract_id, EdgeType.PRODUCES.value)
        if edge_key not in existing_edges:
            result.edges.append(Edge(
                source=producer_id,
                target=contract_id,
                type=EdgeType.PRODUCES.value,
                metadata={"inferred": True},
            ))
            existing_edges.add(edge_key)

        for cid in consumer_ids:
            edge_key = (cid, contract_id, EdgeType.CONSUMES_CONTRACT.value)
            if edge_key not in existing_edges:
                result.edges.append(Edge(
                    source=cid,
                    target=contract_id,
                    type=EdgeType.CONSUMES_CONTRACT.value,
                    metadata={"inferred": True},
                ))
                existing_edges.add(edge_key)


def _infer_data_contracts(result: ScanResult) -> None:
    """Infer data contracts when a database_table has distinct writers and readers.

    A node with a ``writes`` edge to the table is a writer; one with a
    ``reads`` edge is a reader.  When at least one writer and one reader exist
    and they are *different* nodes, a data contract is created.
    """
    existing_node_ids = {n.id for n in result.nodes}
    existing_edges = {(e.source, e.target, e.type) for e in result.edges}

    tables: dict[str, Node] = {}
    for node in result.nodes:
        if node.type == NodeType.DATABASE_TABLE.value:
            tables[node.id] = node

    if not tables:
        return

    for table_id, table_node in tables.items():
        writers: set[str] = set()
        readers: set[str] = set()
        for edge in result.edges:
            if edge.target == table_id and edge.type == EdgeType.WRITES.value:
                writers.add(edge.source)
            elif edge.target == table_id and edge.type == EdgeType.READS.value:
                readers.add(edge.source)

        # Only create a contract if there are writers and readers that differ
        distinct_readers = readers - writers
        if not writers or not distinct_readers:
            continue

        label = table_node.label
        contract_id = f"contract:data:{label}"
        if contract_id in existing_node_ids:
            continue

        sorted_writers = sorted(writers)
        sorted_readers = sorted(distinct_readers)

        contract_node = Node(
            id=contract_id,
            type=NodeType.CONTRACT.value,
            label=f"Data: {label}",
            metadata={
                "contract_type": "data",
                "producer": sorted_writers[0],
                "consumers": sorted_readers,
                "status": "active",
                "inferred": True,
            },
        )
        result.nodes.append(contract_node)
        existing_node_ids.add(contract_id)

        for writer_id in sorted_writers:
            edge_key = (writer_id, contract_id, EdgeType.PRODUCES.value)
            if edge_key not in existing_edges:
                result.edges.append(Edge(
                    source=writer_id,
                    target=contract_id,
                    type=EdgeType.PRODUCES.value,
                    metadata={"inferred": True},
                ))
                existing_edges.add(edge_key)

        for reader_id in sorted_readers:
            edge_key = (reader_id, contract_id, EdgeType.CONSUMES_CONTRACT.value)
            if edge_key not in existing_edges:
                result.edges.append(Edge(
                    source=reader_id,
                    target=contract_id,
                    type=EdgeType.CONSUMES_CONTRACT.value,
                    metadata={"inferred": True},
                ))
                existing_edges.add(edge_key)


def _infer_contract_edges(result: ScanResult) -> None:
    """Orchestrate all contract inference passes.

    Detects cross-component agreements (API, event, config, and data
    contracts) and materializes them as ``contract`` nodes with ``produces``
    and ``consumes_contract`` edges.
    """
    _infer_api_contracts(result)
    _infer_event_contracts(result)
    _infer_config_contracts(result)
    _infer_data_contracts(result)


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
    per_file_results: dict[Path, ScanResult] = {}

    # Set project root on recognizers that support it (e.g., GoRecognizer)
    _seen_recognizers: set[int] = set()
    for ext in active_registry.registered_extensions:
        for recognizer in active_registry.get_recognizers(Path(f"dummy{ext}")):
            rid = id(recognizer)
            if rid not in _seen_recognizers:
                _seen_recognizers.add(rid)
                if hasattr(recognizer, "set_project_root"):
                    recognizer.set_project_root(project_path)

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

        # Collect all nodes/edges/imports/implementations from recognizers
        file_nodes: list[Node] = []
        file_edges: list[Edge] = []
        file_imports: list[ImportInfo] = []
        file_implementations: list[ImplementationInfo] = []
        for recognizer in applicable:
            file_result = recognizer.recognize(rel_path, content)
            file_nodes.extend(file_result.nodes)
            file_edges.extend(file_result.edges)
            file_imports.extend(file_result.imports)
            file_implementations.extend(file_result.implementations)

        # Tag nodes from test files with source: test metadata
        if is_test and include_tests:
            for node in file_nodes:
                node.metadata["source"] = "test"

        # Create module node for ALL scanned languages (universal)
        module_path = _file_to_module_path_universal(source_file, project_path, suffix)
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
                "language": _suffix_to_language(suffix),
            },
        )
        file_nodes.append(module_node)

        # Create contains edges from module to all entities in this file
        for node in file_nodes:
            if node.id != module_id:
                file_edges.append(Edge(
                    source=module_id,
                    target=node.id,
                    type=EdgeType.CONTAINS.value,
                    metadata={"inferred": True},
                ))

        combined = ScanResult(
            nodes=file_nodes,
            edges=file_edges,
            imports=file_imports,
            implementations=file_implementations,
        )
        per_file_results[rel_path] = combined
        merged.merge(combined)

    # Universal import inference (processes ScanResult.imports from all languages)
    _infer_import_edges_universal(merged, per_file_results)

    # Python-specific import inference (backward compat, fills gaps)
    _infer_cross_file_edges(merged, file_contents)
    _infer_import_edges(merged, file_contents, project_path)

    # Build class registry for inheritance resolution
    class_registry: dict[str, str] = {}
    for node in merged.nodes:
        if node.type == NodeType.SERVICE.value:
            class_name = node.metadata.get("class_name") or node.label
            class_registry[class_name] = node.id

    # Universal inheritance inference (processes ScanResult.implementations)
    _infer_inheritance_edges_universal(merged, per_file_results)

    # Python-specific inheritance inference (backward compat)
    _infer_inheritance_edges(merged, class_registry, file_contents)

    # Contract inference (detects cross-component agreements)
    _infer_contract_edges(merged)

    return merged

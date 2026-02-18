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


@dataclass
class CallInfo:
    """Structured call-graph information returned by recognizers."""

    caller: str  # Enclosing function/method name (e.g., "App.Update")
    callee: str  # Called function/method name (e.g., "Save")
    receiver: str = ""  # Receiver/object (e.g., "Store" for s.Store.Save())
    file_path: str = ""  # Source file where the call occurs
    style: str = "direct"  # "direct", "method", "constructor"


@dataclass
class InterfaceInfo:
    """Structured interface declaration info returned by recognizers."""

    name: str  # Interface name (e.g., "Store")
    methods: list[str] = field(default_factory=list)  # Method signatures
    file_path: str = ""  # Source file where defined


@dataclass
class MethodSetEntry:
    """A single method in a struct's method set, for interface satisfaction matching."""

    struct_name: str  # Struct that has this method
    method_name: str  # Method name
    file_path: str = ""  # Source file where defined


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
    calls: list[CallInfo] = field(default_factory=list)
    interfaces: list[InterfaceInfo] = field(default_factory=list)
    method_sets: list[MethodSetEntry] = field(default_factory=list)

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
        self.calls.extend(other.calls)
        self.interfaces.extend(other.interfaces)
        self.method_sets.extend(other.method_sets)


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
# Python call detection (v0.9.0)
# ---------------------------------------------------------------------------

_PY_FUNC_CALL_RE = re.compile(r'(?:(\w+)\.)?(\w+)\s*\(')
_PY_FUNC_DEF_RE = re.compile(r'^(?:    |\t)?def\s+(\w+)\s*\(', re.MULTILINE)
_PY_CLASS_DEF_RE = re.compile(r'^class\s+(\w+)', re.MULTILINE)

_PYTHON_BUILTINS = frozenset({
    "print", "len", "range", "str", "int", "float", "bool", "list", "dict",
    "set", "tuple", "type", "isinstance", "issubclass", "hasattr", "getattr",
    "setattr", "delattr", "super", "property", "staticmethod", "classmethod",
    "open", "input", "enumerate", "zip", "map", "filter", "sorted", "reversed",
    "min", "max", "sum", "abs", "round", "any", "all", "next", "iter",
    "repr", "hash", "id", "dir", "vars", "globals", "locals", "exec", "eval",
    "compile", "breakpoint", "exit", "quit",
})


def _find_py_enclosing_context(content: str) -> dict[int, tuple[str, str]]:
    """Build a mapping of line_number -> (enclosing_class, enclosing_function).

    For methods inside a class, returns e.g. ("MyClass", "my_method").
    For top-level functions, returns ("", "my_function").
    """
    result: dict[int, tuple[str, str]] = {}
    lines = content.split('\n')

    # Find all class and function definitions with their line numbers
    class_ranges: list[tuple[int, str]] = []
    func_ranges: list[tuple[int, str, int]] = []  # (start_line, name, indent)

    for match in _PY_CLASS_DEF_RE.finditer(content):
        class_name = match.group(1)
        start_line = content[:match.start()].count('\n')
        class_ranges.append((start_line, class_name))

    for match in _PY_FUNC_DEF_RE.finditer(content):
        func_name = match.group(1)
        start_line = content[:match.start()].count('\n')
        line = lines[start_line] if start_line < len(lines) else ""
        indent = len(line) - len(line.lstrip())
        func_ranges.append((start_line, func_name, indent))

    for line_no in range(len(lines)):
        # Find enclosing class (most recent class def before this line)
        current_class = ""
        for cls_start, cls_name in class_ranges:
            if cls_start <= line_no:
                current_class = cls_name
            else:
                break

        # Find enclosing function (most recent func def before this line)
        current_func = ""
        for func_start, func_name, _indent in func_ranges:
            if func_start <= line_no:
                current_func = func_name
            else:
                break

        result[line_no] = (current_class, current_func)

    return result


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
                confidence=0.9,
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
        rel_path = file_path.as_posix()

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

        # --- Call detection (v0.9.0) ---
        calls: list[CallInfo] = []
        enclosing_ctx = _find_py_enclosing_context(content)
        rel_path_str = file_path.as_posix()

        for match in _PY_FUNC_CALL_RE.finditer(cleaned):
            receiver = match.group(1) or ""
            callee = match.group(2)

            # Skip builtins
            if callee in _PYTHON_BUILTINS:
                continue
            # Skip if receiver is a builtin module
            if receiver in _PYTHON_BUILTINS:
                continue

            # Skip decorators (@ lines), import statements, def/class keywords
            line_start = cleaned.rfind('\n', 0, match.start()) + 1
            line_prefix = cleaned[line_start:match.start()].lstrip()
            if line_prefix.startswith(('@', 'import ', 'from ', 'def ', 'class ')):
                continue

            line_no = content[:match.start()].count('\n')
            enc_class, enc_func = enclosing_ctx.get(line_no, ("", ""))

            # Determine caller name
            if enc_class and enc_func:
                caller = f"{enc_class}.{enc_func}"
            else:
                caller = enc_func

            # Determine style
            if receiver == "self":
                style = "method"
                # Replace "self" receiver with the enclosing class name
                receiver = enc_class
            elif receiver:
                style = "method"
            elif callee[0:1].isupper():
                style = "constructor"
            else:
                style = "direct"

            calls.append(CallInfo(
                caller=caller,
                callee=callee,
                receiver=receiver,
                file_path=rel_path_str,
                style=style,
            ))

        return ScanResult(nodes=nodes, edges=edges, calls=calls)


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
                                confidence=0.8,
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
        rel_path_str = rel_path.as_posix() if hasattr(rel_path, "as_posix") else str(rel_path)
        source_mod_id = file_to_mod_id.get(rel_path_str)
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
                    confidence=0.9,
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
                    confidence=0.8,
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
                confidence=0.5,
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
                    confidence=0.5,
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
                confidence=0.5,
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
                    confidence=0.5,
                    metadata={"inferred": True},
                ))
                existing_edges.add(edge_key)


# Structural edge types that are auto-generated by the scanner and do not
# represent intentional usage of a node.  Excluded from config contract
# reference counting to avoid false positives.
_STRUCTURAL_EDGE_TYPES = {
    EdgeType.CONTAINS.value,
    EdgeType.IMPORTS.value,
    EdgeType.IMPLEMENTS.value,
}


def _infer_config_contracts(result: ScanResult) -> None:
    """Infer config contracts when an env_var is referenced by 2+ distinct services.

    Only non-structural edges (i.e. edges whose type is not in
    ``_STRUCTURAL_EDGE_TYPES``) count as intentional references.  When two or
    more *distinct* source/target nodes reference the same env_var, a config
    contract is created.  The producer is the alphabetically first referencing
    node.
    """
    existing_node_ids = {n.id for n in result.nodes}
    existing_edges = {(e.source, e.target, e.type) for e in result.edges}

    env_vars: dict[str, Node] = {}
    for node in result.nodes:
        if node.type == NodeType.ENV_VAR.value:
            env_vars[node.id] = node

    if not env_vars:
        return

    # For each env_var, find distinct nodes connected to it via semantic edges
    # (structural edges like contains/imports/implements are excluded because
    # they are auto-generated and do not represent intentional config usage).
    for env_id, env_node in env_vars.items():
        referencing_nodes: set[str] = set()
        for edge in result.edges:
            if edge.type in _STRUCTURAL_EDGE_TYPES:
                continue
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
                confidence=0.5,
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
                    confidence=0.5,
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
                    confidence=0.5,
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
                    confidence=0.5,
                    metadata={"inferred": True},
                ))
                existing_edges.add(edge_key)


def _build_name_lookup(result: ScanResult) -> dict[str, str]:
    """Build a name -> node_id lookup dict in one O(N) pass over result.nodes.

    Keys are: label (first priority), then struct_name from metadata, then
    class_name from metadata. dict.setdefault ensures the first match wins,
    matching the precedence of _find_node_id_for_name.
    """
    lookup: dict[str, str] = {}
    for node in result.nodes:
        lookup.setdefault(node.label, node.id)
        struct_name = node.metadata.get("struct_name")
        if struct_name:
            lookup.setdefault(struct_name, node.id)
        class_name = node.metadata.get("class_name")
        if class_name:
            lookup.setdefault(class_name, node.id)
    return lookup


def _find_node_id_for_name(result: ScanResult, name: str) -> str | None:
    """Find the node ID for a given class/struct/interface name."""
    for node in result.nodes:
        if node.label == name:
            return node.id
        if node.metadata.get("struct_name") == name:
            return node.id
        if node.metadata.get("class_name") == name:
            return node.id
    return None


def _infer_interface_satisfaction(result: ScanResult) -> None:
    """Infer implements edges from Go duck-type interface satisfaction.

    Matches struct method sets against interface method lists.
    A struct satisfies an interface if its method set is a superset of
    the interface's method list.
    """
    if not result.interfaces or not result.method_sets:
        return

    existing_edges = {(e.source, e.target, e.type) for e in result.edges}

    # Build method sets per struct: struct_name -> set of method names
    struct_methods: dict[str, set[str]] = {}
    struct_files: dict[str, str] = {}
    for entry in result.method_sets:
        struct_methods.setdefault(entry.struct_name, set()).add(entry.method_name)
        if entry.file_path:
            struct_files[entry.struct_name] = entry.file_path

    # Build a single name -> node_id lookup to avoid O(N) scans inside the loop
    name_lookup = _build_name_lookup(result)

    # For each interface, find structs that satisfy it
    for iface in result.interfaces:
        if not iface.methods:
            continue
        iface_method_set = set(iface.methods)

        for struct_name, methods in struct_methods.items():
            if iface_method_set.issubset(methods):
                # Find the struct's node ID and interface's node ID
                struct_node_id = name_lookup.get(struct_name)
                iface_node_id = name_lookup.get(iface.name)

                if struct_node_id and iface_node_id:
                    edge_key = (struct_node_id, iface_node_id, EdgeType.IMPLEMENTS.value)
                    if edge_key not in existing_edges:
                        result.edges.append(Edge(
                            source=struct_node_id,
                            target=iface_node_id,
                            type=EdgeType.IMPLEMENTS.value,
                            confidence=0.7,
                            metadata={
                                "inferred": True,
                                "mechanism": "duck_type",
                                "matched_methods": sorted(iface_method_set),
                            },
                        ))
                        existing_edges.add(edge_key)


def _infer_call_edges(result: ScanResult) -> None:
    """Resolve CallInfo records into calls edges in the graph.

    Creates edges between caller and callee nodes. When a callee can be
    resolved to an existing node (via receiver matching or symbol registry),
    creates a calls edge. Creates demand-driven method-level nodes only
    when they participate in call relationships.
    """
    if not result.calls:
        return

    existing_edges = {(e.source, e.target, e.type) for e in result.edges}
    existing_node_ids = {n.id for n in result.nodes}

    # Build symbol registry: map names to node IDs
    # Maps: struct_name -> node_id, module_label -> module_node_id
    symbol_registry: dict[str, str] = {}
    module_registry: dict[str, str] = {}  # package/module label -> node_id
    for node in result.nodes:
        if node.type == "service":
            name = node.metadata.get("struct_name") or node.metadata.get("class_name") or node.label
            symbol_registry[name] = node.id
        elif node.type == "module":
            symbol_registry[node.label] = node.id
            module_registry[node.label] = node.id
            # Also map package name from metadata
            pkg = node.metadata.get("package", "")
            if pkg:
                module_registry[pkg] = node.id

    for call in result.calls:
        # Try to resolve the callee to an existing node
        callee_node_id = None

        if call.receiver:
            # receiver.callee() — try to find receiver as a known symbol
            callee_node_id = symbol_registry.get(call.receiver)
            if not callee_node_id:
                # Try matching receiver as a module/package
                callee_node_id = module_registry.get(call.receiver)
        else:
            # Direct call — try to find callee as a known symbol
            callee_node_id = symbol_registry.get(call.callee)

        if callee_node_id is None:
            continue  # Can't resolve — skip

        # Resolve caller
        caller_node_id = None
        if call.caller:
            # Try "Class.Method" format first
            if "." in call.caller:
                class_name = call.caller.split(".")[0]
                caller_node_id = symbol_registry.get(class_name)
            else:
                caller_node_id = symbol_registry.get(call.caller)

        if caller_node_id is None:
            # Try to find caller by file path — use the module node
            if call.file_path:
                for node in result.nodes:
                    if node.type == "module" and node.file_path == call.file_path:
                        caller_node_id = node.id
                        break

        if caller_node_id is None or caller_node_id == callee_node_id:
            continue  # Can't resolve caller or self-call

        edge_key = (caller_node_id, callee_node_id, EdgeType.CALLS.value)
        if edge_key not in existing_edges:
            result.edges.append(Edge(
                source=caller_node_id,
                target=callee_node_id,
                type=EdgeType.CALLS.value,
                confidence=0.8,
                metadata={
                    "inferred": True,
                    "caller": call.caller,
                    "callee": call.callee,
                    "receiver": call.receiver,
                    "style": call.style,
                },
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
# Architectural Decision Record (ADR) detection
# ---------------------------------------------------------------------------

_DECISION_HASH_RE = re.compile(r"#\s+DECISION:\s*(.+)")
_DECISION_LINE_COMMENT_RE = re.compile(r"//\s+ADR-(\d+):\s*(.+)")
_DECISION_BLOCK_COMMENT_RE = re.compile(r"/\*\s*ADR-(\d+):\s*(.+?)(?=\s*\*/|$)", re.DOTALL | re.MULTILINE)


def _detect_decision_markers(file_path: str, content: str) -> list[dict]:
    """Detect DECISION: and ADR-NNN: markers in code comments.

    Scans *content* for architectural decision markers in three styles:

    - ``# DECISION: <text>`` — Python/Ruby/Bash hash comments
    - ``// ADR-NNN: <text>`` — C/Go/Java/TypeScript line comments
    - ``/* ADR-NNN: <text> */`` — block comments

    Returns a list of dicts with keys:
        text (str), adr_id (str | None), file_path (str),
        line_number (int, 1-indexed), mined_from (str)
    """
    if not content:
        return []

    results: list[dict] = []
    lines = content.splitlines()

    for lineno, line in enumerate(lines, start=1):
        # --- Hash-style: # DECISION: <text> ---
        m = _DECISION_HASH_RE.search(line)
        if m:
            results.append(
                {
                    "text": m.group(1).strip(),
                    "adr_id": None,
                    "file_path": file_path,
                    "line_number": lineno,
                    "mined_from": "comment",
                }
            )
            continue

        # --- Line comment style: // ADR-NNN: <text> ---
        m = _DECISION_LINE_COMMENT_RE.search(line)
        if m:
            results.append(
                {
                    "text": m.group(2).strip(),
                    "adr_id": m.group(1),
                    "file_path": file_path,
                    "line_number": lineno,
                    "mined_from": "comment",
                }
            )
            continue

    # --- Block comment style: /* ADR-NNN: <text> */ ---
    # Process the entire content for block comments
    for m in _DECISION_BLOCK_COMMENT_RE.finditer(content):
        match_start = m.start()
        lineno = content[:match_start].count("\n") + 1
        text = m.group(2).strip().rstrip("*/").strip()
        results.append(
            {
                "text": text,
                "adr_id": m.group(1),
                "file_path": file_path,
                "line_number": lineno,
                "mined_from": "comment",
            }
        )

    # Deduplicate: block comment scan may re-find line comment matches in content.
    # Keep only unique (file_path, line_number) entries, preserving first occurrence.
    seen: set[tuple[str, int]] = set()
    unique: list[dict] = []
    for r in results:
        key = (r["file_path"], r["line_number"])
        if key not in seen:
            seen.add(key)
            unique.append(r)

    return unique


def _infer_decision_edges(result: ScanResult, markers: list[dict]) -> None:
    """Create decision nodes and constrains/supersedes edges from detected markers.

    For each marker:

    1. Creates a ``decision:{file_path}:{line_number}`` node.
    2. Creates ``constrains`` edges:
       - If the decision text contains an existing node ID, target that node.
       - Otherwise target the module node for the same file (fallback).
       - If no module node exists, no constrains edge is created.
    3. Creates ``supersedes`` edges between decisions sharing the same ADR ID
       (newer line number supersedes older).
    """
    if not markers:
        return

    existing_node_ids = {n.id for n in result.nodes}
    existing_edges = {(e.source, e.target, e.type) for e in result.edges}

    # Build per-file module lookup: file_path -> module node_id
    file_to_module: dict[str, str] = {}
    for node in result.nodes:
        if node.type == NodeType.MODULE.value and node.file_path:
            file_to_module[node.file_path] = node.id

    # Track created decision nodes by ADR ID for supersedes inference
    adr_id_to_decisions: dict[str, list[tuple[int, str]]] = {}

    for marker in markers:
        file_path = marker["file_path"]
        line_number = marker["line_number"]
        text = marker["text"]
        adr_id = marker.get("adr_id")

        node_id = f"decision:{file_path}:{line_number}"

        # Create the decision node
        if node_id not in existing_node_ids:
            decision_node = Node(
                id=node_id,
                type=NodeType.DECISION.value,
                label=text,
                file_path=file_path,
                metadata={
                    "text": text,
                    "adr_id": adr_id,
                    "file_path": file_path,
                    "line_number": line_number,
                    "mined_from": marker.get("mined_from", "comment"),
                },
            )
            result.nodes.append(decision_node)
            existing_node_ids.add(node_id)

        # Track for supersedes inference
        if adr_id is not None:
            adr_id_to_decisions.setdefault(adr_id, []).append((line_number, node_id))

        # --- constrains edge targeting ---
        # 1. Scan decision text for references to existing node IDs
        target_node_id: str | None = None
        for candidate_id in existing_node_ids:
            if candidate_id == node_id:
                continue
            if candidate_id in text:
                target_node_id = candidate_id
                break

        # 2. Fallback: use the module node for this file
        if target_node_id is None:
            target_node_id = file_to_module.get(file_path)

        # 3. Create constrains edge if a target was found
        if target_node_id is not None:
            edge_key = (node_id, target_node_id, EdgeType.CONSTRAINS.value)
            if edge_key not in existing_edges:
                result.edges.append(
                    Edge(
                        source=node_id,
                        target=target_node_id,
                        type=EdgeType.CONSTRAINS.value,
                        metadata={"inferred": True},
                    )
                )
                existing_edges.add(edge_key)

    # --- supersedes edges: newer line supersedes older for same ADR ID ---
    for adr_id, entries in adr_id_to_decisions.items():
        if len(entries) < 2:
            continue
        entries_sorted = sorted(entries, key=lambda t: t[0])
        for i in range(1, len(entries_sorted)):
            newer_node_id = entries_sorted[i][1]
            older_node_id = entries_sorted[i - 1][1]
            edge_key = (newer_node_id, older_node_id, EdgeType.SUPERSEDES.value)
            if edge_key not in existing_edges:
                result.edges.append(
                    Edge(
                        source=newer_node_id,
                        target=older_node_id,
                        type=EdgeType.SUPERSEDES.value,
                        metadata={"inferred": True, "adr_id": adr_id},
                    )
                )
                existing_edges.add(edge_key)


def _infer_decision_marker_edges(
    result: ScanResult, per_file_contents: dict
) -> None:
    """Orchestrate decision marker detection across all scanned files.

    Iterates over *per_file_contents* (mapping of relative_path -> content),
    detects ADR markers in each file, and calls ``_infer_decision_edges`` to
    materialise decision nodes and their associated edges.
    """
    all_markers: list[dict] = []
    for rel_path, content in per_file_contents.items():
        file_path_str = rel_path.as_posix() if hasattr(rel_path, "as_posix") else str(rel_path)
        markers = _detect_decision_markers(file_path_str, content)
        all_markers.extend(markers)

    if all_markers:
        _infer_decision_edges(result, all_markers)


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
        file_calls: list[CallInfo] = []
        file_interfaces: list[InterfaceInfo] = []
        file_method_sets: list[MethodSetEntry] = []
        for recognizer in applicable:
            file_result = recognizer.recognize(rel_path, content)
            file_nodes.extend(file_result.nodes)
            file_edges.extend(file_result.edges)
            file_imports.extend(file_result.imports)
            file_implementations.extend(file_result.implementations)
            file_calls.extend(file_result.calls)
            file_interfaces.extend(file_result.interfaces)
            file_method_sets.extend(file_result.method_sets)

        # Tag nodes from test files with source: test metadata
        if is_test and include_tests:
            for node in file_nodes:
                node.metadata["source"] = "test"

        # Create module node for ALL scanned languages (universal)
        module_path = _file_to_module_path_universal(source_file, project_path, suffix)
        module_id = f"mod:{module_path}"
        module_label = Path(source_file).stem

        module_node = Node(
            id=module_id,
            type=NodeType.MODULE.value,
            label=module_label,
            file_path=rel_path.as_posix(),
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
                    confidence=1.0,
                    metadata={"inferred": True},
                ))

        combined = ScanResult(
            nodes=file_nodes,
            edges=file_edges,
            imports=file_imports,
            implementations=file_implementations,
            calls=file_calls,
            interfaces=file_interfaces,
            method_sets=file_method_sets,
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

    # Interface satisfaction (duck-type matching across files)
    _infer_interface_satisfaction(merged)

    # Call-graph edges (resolve CallInfo into calls edges)
    _infer_call_edges(merged)

    # Contract inference (detects cross-component agreements)
    _infer_contract_edges(merged)

    # Decision marker inference (detects ADR comments in source files)
    _infer_decision_marker_edges(merged, file_contents)

    return merged


# ---------------------------------------------------------------------------
# Incremental sync (v0.12.0)
# ---------------------------------------------------------------------------


def sync_files(
    graph: "ArchGraph",
    project_path: str,
    file_paths: list[str],
    scanner_mode: str = "regex",
) -> dict:
    """Incrementally sync specific files in the architecture graph.

    For each file in *file_paths*:

    1. Find all non-manual nodes whose ``file_path`` metadata matches the
       file (stored as a path relative to *project_path*).
    2. Collect all non-manual edges where the source node is one of those
       file-local nodes (outgoing edges from the file's namespace).
    3. Remove those non-manual edges, then remove the non-manual nodes.
    4. If the file still exists on disk: re-scan it using the project
       registry and re-add the resulting nodes and edges.
    5. If the file has been deleted: the removal in step 3 is sufficient.
    6. After all files are processed, re-run scoped inference stages
       (import edges, cross-file edges, contract inference) so that
       cross-file relationships stay correct.
    7. Manual nodes and edges (``manual=True``) are never removed.

    Parameters
    ----------
    graph:
        The :class:`~codegiraffe.graph.ArchGraph` to update in-place.
    project_path:
        Absolute path to the project root (used for path resolution and
        the scanner registry).
    file_paths:
        List of **absolute** paths to the files that have changed.
    scanner_mode:
        ``"regex"`` (default) or ``"ast"`` — selects the scanner registry.

    Returns
    -------
    dict
        ``{"added": {"nodes": N, "edges": N},
           "removed": {"nodes": N, "edges": N},
           "preserved": {"nodes": N, "edges": N}}``
    """
    from codegiraffe.registry import get_default_registry

    root = Path(project_path)

    # Build the active registry
    if scanner_mode == "ast":
        from codegiraffe.ast_scanner import get_ast_registry
        active_registry = get_ast_registry()
    else:
        active_registry = get_default_registry()

    # Set project root on recognizers that support it
    _seen_recognizers: set[int] = set()
    for ext in active_registry.registered_extensions:
        for recognizer in active_registry.get_recognizers(Path(f"dummy{ext}")):
            rid = id(recognizer)
            if rid not in _seen_recognizers:
                _seen_recognizers.add(rid)
                if hasattr(recognizer, "set_project_root"):
                    recognizer.set_project_root(project_path)

    # Normalise input paths to relative strings (how they are stored in nodes)
    rel_paths: list[str] = []
    abs_paths: list[Path] = []
    for fp in file_paths:
        abs_path = Path(fp)
        try:
            rel = str(abs_path.relative_to(root))
        except ValueError:
            rel = str(abs_path)
        rel_paths.append(rel)
        abs_paths.append(root / rel)

    # Counters
    removed_nodes = 0
    removed_edges = 0
    added_nodes = 0
    added_edges = 0

    # ------------------------------------------------------------------
    # Step 1 & 2: Identify nodes and edges to remove for all changed files.
    # Defer restoration of "keep" edges until after new nodes are re-added.
    # ------------------------------------------------------------------

    # Accumulated list of edges to re-add after node replacement.
    # These are: (a) manual edges touching synced-file nodes, and
    # (b) non-manual edges whose SOURCE is from a non-synced file but whose
    #     TARGET is in a synced file (incoming cross-file edges).
    all_edges_to_restore: list[Edge] = []

    for rel_path_str in rel_paths:
        # Find non-manual nodes from this file
        file_node_ids: set[str] = set()

        for nid, attrs in list(graph.graph.nodes(data=True)):
            node = attrs.get("node")
            if node is None:
                continue
            if node.file_path == rel_path_str and not node.manual:
                file_node_ids.add(nid)

        # Categorise all edges involving file_node_ids:
        #   - outgoing non-manual from file node: REMOVE
        #   - incoming from another file (non-manual): RESTORE after node re-add
        #   - manual edges (any direction): RESTORE after node re-add
        #   - internal (both endpoints in file): REMOVE (will be re-inferred)

        edges_to_remove_keys: list[tuple[str, str]] = []

        for u, v, edge_data in list(graph.graph.edges(data=True)):
            edge = edge_data.get("edge")
            if edge is None:
                continue

            source_in_file = u in file_node_ids
            target_in_file = v in file_node_ids

            if not source_in_file and not target_in_file:
                continue  # Unrelated edge — leave alone

            if edge.manual:
                # Always preserve manual edges; defer re-add until after new nodes
                all_edges_to_restore.append(edge)
                continue

            if source_in_file:
                # Outgoing from file node (includes internal edges) — remove
                edges_to_remove_keys.append((u, v))
            elif target_in_file and not source_in_file:
                # Incoming from a non-synced file — preserve per spec
                all_edges_to_restore.append(edge)

        # Remove outgoing non-manual edges explicitly
        for u, v in edges_to_remove_keys:
            if graph.graph.has_edge(u, v):
                graph.graph.remove_edge(u, v)
                removed_edges += 1

        # Remove nodes (NetworkX also removes any still-attached incident edges)
        for nid in file_node_ids:
            if nid in graph.graph:
                graph.graph.remove_node(nid)
                removed_nodes += 1

    # Invalidate the to_data() cache after direct graph mutations above.
    # graph.graph.remove_edge/remove_node bypass ArchGraph.remove_node()
    # which is the only method that sets _cached_data = None, so we must
    # do it explicitly here to avoid stale cache reads downstream.
    graph._cached_data = None

    # ------------------------------------------------------------------
    # Step 3: Re-scan existing files and collect new nodes/edges
    # ------------------------------------------------------------------
    new_file_merged = ScanResult()
    new_file_contents: dict[Path, str] = {}
    new_per_file_results: dict[Path, ScanResult] = {}

    for rel_path_str, abs_path in zip(rel_paths, abs_paths):
        if not abs_path.exists():
            continue  # File deleted — nothing to re-add

        suffix = abs_path.suffix.lower()
        applicable = active_registry.get_recognizers(abs_path)
        if not applicable:
            continue

        try:
            content = abs_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        rel_path = Path(rel_path_str)
        new_file_contents[rel_path] = content

        file_nodes: list[Node] = []
        file_edges: list[Edge] = []
        file_imports: list[ImportInfo] = []
        file_implementations: list[ImplementationInfo] = []
        file_calls: list[CallInfo] = []
        file_interfaces: list[InterfaceInfo] = []
        file_method_sets: list[MethodSetEntry] = []

        for recognizer in applicable:
            file_result = recognizer.recognize(rel_path, content)
            file_nodes.extend(file_result.nodes)
            file_edges.extend(file_result.edges)
            file_imports.extend(file_result.imports)
            file_implementations.extend(file_result.implementations)
            file_calls.extend(file_result.calls)
            file_interfaces.extend(file_result.interfaces)
            file_method_sets.extend(file_result.method_sets)

        # Create module node (mirrors scan_project logic)
        module_path = _file_to_module_path_universal(abs_path, project_path, suffix)
        module_id = f"mod:{module_path}"
        module_label = Path(abs_path).stem

        module_node = Node(
            id=module_id,
            type=NodeType.MODULE.value,
            label=module_label,
            file_path=rel_path_str,
            metadata={
                "package": (
                    module_path.rsplit(".", 1)[0] if "." in module_path else ""
                ),
                "source": "production",
                "language": _suffix_to_language(suffix),
            },
        )
        file_nodes.append(module_node)

        # Contains edges from module to all entities in this file
        for node in file_nodes:
            if node.id != module_id:
                file_edges.append(Edge(
                    source=module_id,
                    target=node.id,
                    type=EdgeType.CONTAINS.value,
                    metadata={"inferred": True},
                    confidence=1.0,
                ))

        combined = ScanResult(
            nodes=file_nodes,
            edges=file_edges,
            imports=file_imports,
            implementations=file_implementations,
            calls=file_calls,
            interfaces=file_interfaces,
            method_sets=file_method_sets,
        )
        new_per_file_results[rel_path] = combined
        new_file_merged.merge(combined)

    # ------------------------------------------------------------------
    # Step 4: Add new nodes and direct edges to the graph
    # ------------------------------------------------------------------
    existing_node_ids: set[str] = set(graph.graph.nodes())

    for node in new_file_merged.nodes:
        if node.id not in existing_node_ids:
            graph.add_node(node)
            existing_node_ids.add(node.id)
            added_nodes += 1
        else:
            # Refresh metadata on an already-existing node (e.g. after edit)
            graph.add_node(node)

    # Existing edge set for deduplication
    existing_edge_keys: set[tuple[str, str, str]] = set()
    for u, v, edge_data in graph.graph.edges(data=True):
        e = edge_data.get("edge")
        if e is not None:
            existing_edge_keys.add((u, v, e.type))

    for edge in new_file_merged.edges:
        key = (edge.source, edge.target, edge.type)
        if key not in existing_edge_keys:
            graph.add_edge(edge)
            existing_edge_keys.add(key)
            added_edges += 1

    # ------------------------------------------------------------------
    # Step 4b: Restore deferred edges (incoming cross-file + manual).
    # Must happen AFTER new nodes are added so endpoints exist.
    # ------------------------------------------------------------------
    for edge in all_edges_to_restore:
        key = (edge.source, edge.target, edge.type)
        if key not in existing_edge_keys:
            if edge.source in graph.graph and edge.target in graph.graph:
                graph.add_edge(edge)
                existing_edge_keys.add(key)

    # ------------------------------------------------------------------
    # Step 5: Re-run scoped inference against full graph state
    # ------------------------------------------------------------------
    if new_per_file_results:
        # Build a ScanResult that represents the current full graph
        # (needed so inference functions can see all nodes)
        full_result = ScanResult()
        for nid, attrs in graph.graph.nodes(data=True):
            node = attrs.get("node")
            if node is not None:
                full_result.nodes.append(node)
        for u, v, edge_data in graph.graph.edges(data=True):
            edge = edge_data.get("edge")
            if edge is not None:
                full_result.edges.append(edge)

        # Attach structured data from new files only
        full_result.imports.extend(new_file_merged.imports)
        full_result.implementations.extend(new_file_merged.implementations)
        full_result.calls.extend(new_file_merged.calls)
        full_result.interfaces.extend(new_file_merged.interfaces)
        full_result.method_sets.extend(new_file_merged.method_sets)

        # Infer edges
        _infer_import_edges_universal(full_result, new_per_file_results)
        if new_file_contents:
            _infer_import_edges(full_result, new_file_contents, project_path)
            _infer_cross_file_edges(full_result, new_file_contents)

        class_registry: dict[str, str] = {
            (node.metadata.get("class_name") or node.label): node.id
            for node in full_result.nodes
            if node.type == NodeType.SERVICE.value
        }
        _infer_inheritance_edges_universal(full_result, new_per_file_results)
        _infer_inheritance_edges(full_result, class_registry, new_file_contents)
        _infer_interface_satisfaction(full_result)
        _infer_call_edges(full_result)
        _infer_decision_marker_edges(full_result, new_file_contents)

        # Flush newly inferred edges back into the graph (deduplicated)
        for edge in full_result.edges:
            key = (edge.source, edge.target, edge.type)
            if key not in existing_edge_keys:
                if edge.source in graph.graph and edge.target in graph.graph:
                    graph.add_edge(edge)
                    existing_edge_keys.add(key)
                    added_edges += 1

    return {
        "added": {"nodes": added_nodes, "edges": added_edges},
        "removed": {"nodes": removed_nodes, "edges": removed_edges},
        "preserved": {
            "nodes": sum(
                1 for nid, attrs in graph.graph.nodes(data=True)
                if (n := attrs.get("node")) is not None
                and n.file_path not in rel_paths
            ),
            "edges": sum(
                1 for u, v, ed in graph.graph.edges(data=True)
                if (e := ed.get("edge")) is not None
                and (sn := graph.graph.nodes.get(u, {}).get("node")) is not None
                and sn.file_path not in rel_paths
            ),
        },
    }

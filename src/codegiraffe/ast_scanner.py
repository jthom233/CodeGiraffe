"""AST-aware scanning using tree-sitter for Code Giraffe.

Provides pattern recognizers that use tree-sitter S-expression queries
for more accurate pattern detection than regex. Falls back to regex
recognizers when tree-sitter is not installed.

Optional dependencies: tree-sitter, tree-sitter-python, tree-sitter-go,
tree-sitter-typescript, tree-sitter-rust, tree-sitter-java.
Install with: ``pip install codegiraffe[ast]``
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from codegiraffe.graph import Node, Edge
from codegiraffe.scanner import ScanResult
from codegiraffe.schema import EdgeType, NodeType

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional tree-sitter imports
# ---------------------------------------------------------------------------

HAS_TREE_SITTER = False
_ts: Any = None
_ts_python: Any = None
_ts_go: Any = None
_ts_typescript: Any = None
_ts_rust: Any = None
_ts_java: Any = None

try:
    import tree_sitter as _ts  # type: ignore[no-redef]
    import tree_sitter_python as _ts_python  # type: ignore[no-redef]
    import tree_sitter_go as _ts_go  # type: ignore[no-redef]
    import tree_sitter_typescript as _ts_typescript  # type: ignore[no-redef]
    import tree_sitter_rust as _ts_rust  # type: ignore[no-redef]
    import tree_sitter_java as _ts_java  # type: ignore[no-redef]
    HAS_TREE_SITTER = True
except ImportError:
    pass


def is_available() -> bool:
    """Check whether tree-sitter and all language packages are installed."""
    return HAS_TREE_SITTER


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _text(node: Any) -> str:
    """Extract UTF-8 text from a tree-sitter node."""
    return node.text.decode("utf-8")


def _strip_quotes(s: str) -> str:
    """Remove surrounding quotes (single, double, or triple) from a string."""
    for q in ('"""', "'''", '"', "'"):
        if s.startswith(q) and s.endswith(q):
            return s[len(q):-len(q)]
    return s


def _make_parser(lang_module: Any, lang_func_name: str = "language") -> tuple[Any, Any]:
    """Create a tree-sitter Parser and Language from a language module.

    *lang_func_name* is the name of the function on the module that returns the
    language pointer (e.g. ``"language"`` for most packages, or
    ``"language_typescript"`` for the TypeScript package).

    Returns ``(parser, language)``.
    """
    lang_func = getattr(lang_module, lang_func_name)
    language = _ts.Language(lang_func())
    parser = _ts.Parser(language)
    return parser, language


def _query_matches(language: Any, query_str: str, root_node: Any) -> list[tuple[int, dict[str, list[Any]]]]:
    """Run a tree-sitter query and return all matches.

    Each match is ``(pattern_index, {capture_name: [nodes]})``.
    """
    query = _ts.Query(language, query_str)
    cursor = _ts.QueryCursor(query)
    return list(cursor.matches(root_node))


# ---------------------------------------------------------------------------
# Python AST Recognizer
# ---------------------------------------------------------------------------

_PY_DECORATED_DEF_QUERY = """
(decorated_definition
  (decorator) @dec
  definition: (function_definition
    name: (identifier) @func_name))
"""

_PY_CLASS_WITH_BASES_QUERY = """
(class_definition
  name: (identifier) @class_name
  superclasses: (argument_list) @bases
  body: (block) @body)
"""

_PY_PLAIN_CLASS_QUERY = """
(class_definition
  name: (identifier) @class_name)
"""

_PY_ATTR_CALL_QUERY = """
(call
  function: (attribute
    object: (identifier) @obj
    attribute: (identifier) @method)
  arguments: (argument_list) @args)
"""

_PY_SUBSCRIPT_QUERY = """
(subscript
  value: (attribute
    object: (identifier) @obj
    attribute: (identifier) @attr)
  subscript: (string) @key)
"""

# Regex helpers for extracting values from decorator/call text
_ROUTE_ARG_RE = re.compile(
    r"""(?:route|get|post|put|delete|patch)\s*\(\s*["']([^"']+)["']""",
    re.IGNORECASE,
)
_CELERY_TASK_DEC_RE = re.compile(r"""\.task\s*(?:\(|$)""")
_TABLENAME_RE = re.compile(r"""__tablename__\s*=\s*["']([^"']+)["']""")


class PythonASTRecognizer:
    """AST-based Python pattern recognizer using tree-sitter.

    Detected patterns:
        - Flask / FastAPI route decorators  -> ``endpoint`` nodes
        - SQLAlchemy model classes          -> ``database_table`` nodes
        - Celery task decorators            -> ``worker`` nodes
        - ``os.environ`` / ``os.getenv``    -> ``env_var`` nodes
        - ``requests.*`` HTTP calls         -> ``external_api`` nodes
        - Plain class definitions           -> ``service`` nodes (fallback)

    Inferred edges:
        - Files containing both an endpoint and a DB table produce
          ``reads`` edges between them.
    """

    def __init__(self) -> None:
        if not HAS_TREE_SITTER:
            raise ImportError("tree-sitter packages required for AST scanning")
        self._parser, self._language = _make_parser(_ts_python)

    def recognize(self, file_path: Path, content: str) -> ScanResult:
        if not content.strip():
            return ScanResult()

        tree = self._parser.parse(content.encode())
        nodes: list[Node] = []
        edges: list[Edge] = []
        rel = str(file_path)

        endpoint_ids: list[str] = []
        table_ids: list[str] = []
        table_class_names: set[str] = set()

        self._find_decorators(tree, rel, nodes, endpoint_ids)
        self._find_classes(tree, rel, nodes, table_ids, table_class_names)
        self._find_env_vars(tree, rel, content, nodes)
        self._find_external_calls(tree, rel, nodes)

        # Edge inference
        if endpoint_ids and table_ids:
            for ep in endpoint_ids:
                for tbl in table_ids:
                    edges.append(Edge(
                        source=ep, target=tbl,
                        type=EdgeType.READS,
                        metadata={"inferred": True},
                    ))

        return ScanResult(nodes=nodes, edges=edges)

    # -- decorators (routes / celery) ----------------------------------------

    def _find_decorators(
        self, tree: Any, rel: str, nodes: list[Node], endpoint_ids: list[str],
    ) -> None:
        matches = _query_matches(self._language, _PY_DECORATED_DEF_QUERY, tree.root_node)
        for _pat, caps in matches:
            dec_nodes = caps.get("dec", [])
            func_nodes = caps.get("func_name", [])
            if not dec_nodes or not func_nodes:
                continue
            dec_text = _text(dec_nodes[0])
            func_name = _text(func_nodes[0])

            # Route decorator?
            route_m = _ROUTE_ARG_RE.search(dec_text)
            if route_m:
                route_path = route_m.group(1)
                nid = f"endpoint:{route_path}"
                nodes.append(Node(
                    id=nid, type=NodeType.ENDPOINT, label=route_path,
                    file_path=rel,
                    metadata={"route": route_path, "function": func_name},
                ))
                endpoint_ids.append(nid)
                continue

            # Celery task?
            if _CELERY_TASK_DEC_RE.search(dec_text):
                nodes.append(Node(
                    id=f"worker:{func_name}", type=NodeType.WORKER,
                    label=func_name, file_path=rel,
                    metadata={"function": func_name},
                ))

    # -- classes (SQLAlchemy / fallback service) -----------------------------

    def _find_classes(
        self, tree: Any, rel: str, nodes: list[Node],
        table_ids: list[str], table_class_names: set[str],
    ) -> None:
        seen: set[str] = set()

        # Classes WITH bases (potential ORM models)
        for _pat, caps in _query_matches(self._language, _PY_CLASS_WITH_BASES_QUERY, tree.root_node):
            name_nodes = caps.get("class_name", [])
            bases_nodes = caps.get("bases", [])
            body_nodes = caps.get("body", [])
            if not name_nodes:
                continue
            cls_name = _text(name_nodes[0])
            bases_text = _text(bases_nodes[0]) if bases_nodes else ""
            body_text = _text(body_nodes[0]) if body_nodes else ""

            is_model = any(kw in bases_text for kw in ("Base", "db.Model", "Model", "DeclarativeMeta"))
            if is_model:
                tbl_m = _TABLENAME_RE.search(body_text)
                tbl_name = tbl_m.group(1) if tbl_m else cls_name.lower()
                nid = f"table:{tbl_name}"
                nodes.append(Node(
                    id=nid, type=NodeType.DATABASE_TABLE, label=tbl_name,
                    file_path=rel,
                    metadata={"class_name": cls_name, "table_name": tbl_name},
                ))
                table_ids.append(nid)
                table_class_names.add(cls_name)
            else:
                nodes.append(Node(
                    id=f"service:{cls_name}", type=NodeType.SERVICE,
                    label=cls_name, file_path=rel,
                    metadata={"class_name": cls_name},
                ))
            seen.add(cls_name)

        # Plain classes (no bases) — fallback service
        for _pat, caps in _query_matches(self._language, _PY_PLAIN_CLASS_QUERY, tree.root_node):
            name_nodes = caps.get("class_name", [])
            if not name_nodes:
                continue
            cls_name = _text(name_nodes[0])
            if cls_name not in seen:
                nodes.append(Node(
                    id=f"service:{cls_name}", type=NodeType.SERVICE,
                    label=cls_name, file_path=rel,
                    metadata={"class_name": cls_name},
                ))
                seen.add(cls_name)

    # -- env vars ------------------------------------------------------------

    def _find_env_vars(
        self, tree: Any, rel: str, content: str, nodes: list[Node],
    ) -> None:
        seen: set[str] = set()

        # os.getenv("KEY")
        for _pat, caps in _query_matches(self._language, _PY_ATTR_CALL_QUERY, tree.root_node):
            obj_nodes = caps.get("obj", [])
            method_nodes = caps.get("method", [])
            args_nodes = caps.get("args", [])
            if not obj_nodes or not method_nodes:
                continue
            obj = _text(obj_nodes[0])
            method = _text(method_nodes[0])
            args_text = _text(args_nodes[0]) if args_nodes else ""

            if obj == "os" and method == "getenv":
                self._add_env_var(args_text, rel, nodes, seen)

        # os.environ["KEY"]
        for _pat, caps in _query_matches(self._language, _PY_SUBSCRIPT_QUERY, tree.root_node):
            obj_nodes = caps.get("obj", [])
            attr_nodes = caps.get("attr", [])
            key_nodes = caps.get("key", [])
            if not obj_nodes or not attr_nodes or not key_nodes:
                continue
            if _text(obj_nodes[0]) == "os" and _text(attr_nodes[0]) == "environ":
                var = _strip_quotes(_text(key_nodes[0]))
                if var and var not in seen:
                    seen.add(var)
                    nodes.append(Node(
                        id=f"env:{var}", type=NodeType.ENV_VAR, label=var,
                        file_path=rel, metadata={"variable": var},
                    ))

        # Regex fallback for os.environ.get("KEY") (chained attribute access)
        for m in re.finditer(r'os\.environ\.get\(\s*["\']([^"\']+)["\']', content):
            var = m.group(1)
            if var not in seen:
                seen.add(var)
                nodes.append(Node(
                    id=f"env:{var}", type=NodeType.ENV_VAR, label=var,
                    file_path=rel, metadata={"variable": var},
                ))

    @staticmethod
    def _add_env_var(
        args_text: str, rel: str, nodes: list[Node], seen: set[str],
    ) -> None:
        m = re.search(r"""["']([^"']+)["']""", args_text)
        if m:
            var = m.group(1)
            if var not in seen:
                seen.add(var)
                nodes.append(Node(
                    id=f"env:{var}", type=NodeType.ENV_VAR, label=var,
                    file_path=rel, metadata={"variable": var},
                ))

    # -- external API calls --------------------------------------------------

    def _find_external_calls(self, tree: Any, rel: str, nodes: list[Node]) -> None:
        seen: set[str] = set()
        http_methods = {"get", "post", "put", "delete", "patch", "head", "options"}

        for _pat, caps in _query_matches(self._language, _PY_ATTR_CALL_QUERY, tree.root_node):
            obj_nodes = caps.get("obj", [])
            method_nodes = caps.get("method", [])
            args_nodes = caps.get("args", [])
            if not obj_nodes or not method_nodes:
                continue
            obj = _text(obj_nodes[0])
            method = _text(method_nodes[0])
            args_text = _text(args_nodes[0]) if args_nodes else ""

            if obj == "requests" and method in http_methods:
                url_m = re.search(r"""["']([^"']+)["']""", args_text)
                if url_m:
                    url = url_m.group(1)
                    if url not in seen:
                        seen.add(url)
                        nodes.append(Node(
                            id=f"api:{url}", type=NodeType.EXTERNAL_API,
                            label=url, file_path=rel,
                            metadata={"url": url},
                        ))


# ---------------------------------------------------------------------------
# Go AST Recognizer
# ---------------------------------------------------------------------------

_GO_STRUCT_QUERY = """
(type_declaration
  (type_spec
    name: (type_identifier) @struct_name
    type: (struct_type)))
"""

_GO_CALL_QUERY = """
(call_expression
  function: (selector_expression
    operand: (identifier) @obj
    field: (field_identifier) @method)
  arguments: (argument_list) @args)
"""


class GoASTRecognizer:
    """AST-based Go pattern recognizer using tree-sitter.

    Detected patterns:
        - Struct declarations   -> ``service`` nodes
        - ``os.Getenv`` calls   -> ``env_var`` nodes
    """

    def __init__(self) -> None:
        if not HAS_TREE_SITTER:
            raise ImportError("tree-sitter packages required for AST scanning")
        self._parser, self._language = _make_parser(_ts_go)

    def recognize(self, file_path: Path, content: str) -> ScanResult:
        if not content.strip():
            return ScanResult()

        tree = self._parser.parse(content.encode())
        nodes: list[Node] = []
        rel = str(file_path)

        self._find_structs(tree, rel, nodes)
        self._find_env_vars(tree, rel, nodes)

        return ScanResult(nodes=nodes, edges=[])

    def _find_structs(self, tree: Any, rel: str, nodes: list[Node]) -> None:
        for _pat, caps in _query_matches(self._language, _GO_STRUCT_QUERY, tree.root_node):
            name_nodes = caps.get("struct_name", [])
            if name_nodes:
                name = _text(name_nodes[0])
                nodes.append(Node(
                    id=f"service:{name}", type=NodeType.SERVICE, label=name,
                    file_path=rel, metadata={"struct_name": name},
                ))

    def _find_env_vars(self, tree: Any, rel: str, nodes: list[Node]) -> None:
        seen: set[str] = set()
        for _pat, caps in _query_matches(self._language, _GO_CALL_QUERY, tree.root_node):
            obj_nodes = caps.get("obj", [])
            method_nodes = caps.get("method", [])
            args_nodes = caps.get("args", [])
            if not obj_nodes or not method_nodes:
                continue
            obj = _text(obj_nodes[0])
            method = _text(method_nodes[0])
            args_text = _text(args_nodes[0]) if args_nodes else ""

            if obj == "os" and method == "Getenv":
                m = re.search(r'"([^"]+)"', args_text)
                if m:
                    var = m.group(1)
                    if var not in seen:
                        seen.add(var)
                        nodes.append(Node(
                            id=f"env:{var}", type=NodeType.ENV_VAR, label=var,
                            file_path=rel, metadata={"variable": var},
                        ))


# ---------------------------------------------------------------------------
# TypeScript AST Recognizer
# ---------------------------------------------------------------------------

_TS_CALL_QUERY = """
(call_expression
  function: (member_expression
    object: (identifier) @obj
    property: (property_identifier) @method)
  arguments: (arguments) @args)
"""

_TS_ENV_DOT_QUERY = """
(member_expression
  object: (member_expression
    object: (identifier) @outer_obj
    property: (property_identifier) @inner_prop)
  property: (property_identifier) @env_name)
"""


class TypeScriptASTRecognizer:
    """AST-based TypeScript pattern recognizer using tree-sitter.

    Detected patterns:
        - Express route calls (app.get, app.post)  -> ``endpoint`` nodes
        - ``process.env.VAR`` references            -> ``env_var`` nodes
    """

    def __init__(self) -> None:
        if not HAS_TREE_SITTER:
            raise ImportError("tree-sitter packages required for AST scanning")
        # tree-sitter-typescript exposes language_typescript(), not language()
        self._parser, self._language = _make_parser(
            _ts_typescript, "language_typescript",
        )

    def recognize(self, file_path: Path, content: str) -> ScanResult:
        if not content.strip():
            return ScanResult()

        tree = self._parser.parse(content.encode())
        nodes: list[Node] = []
        rel = str(file_path)

        self._find_routes(tree, rel, nodes)
        self._find_env_vars(tree, rel, content, nodes)

        return ScanResult(nodes=nodes, edges=[])

    def _find_routes(self, tree: Any, rel: str, nodes: list[Node]) -> None:
        seen: set[str] = set()
        http_methods = {"get", "post", "put", "delete", "patch", "head", "options"}

        for _pat, caps in _query_matches(self._language, _TS_CALL_QUERY, tree.root_node):
            obj_nodes = caps.get("obj", [])
            method_nodes = caps.get("method", [])
            args_nodes = caps.get("args", [])
            if not obj_nodes or not method_nodes:
                continue
            method = _text(method_nodes[0])
            args_text = _text(args_nodes[0]) if args_nodes else ""

            if method.lower() in http_methods:
                m = re.search(r"""["']([^"']+)["']""", args_text)
                if m:
                    route = m.group(1)
                    if route not in seen:
                        seen.add(route)
                        nodes.append(Node(
                            id=f"endpoint:{route}", type=NodeType.ENDPOINT,
                            label=route, file_path=rel,
                            metadata={"route": route, "method": method.upper()},
                        ))

    def _find_env_vars(self, tree: Any, rel: str, content: str, nodes: list[Node]) -> None:
        seen: set[str] = set()

        for _pat, caps in _query_matches(self._language, _TS_ENV_DOT_QUERY, tree.root_node):
            outer_nodes = caps.get("outer_obj", [])
            inner_nodes = caps.get("inner_prop", [])
            env_nodes = caps.get("env_name", [])
            if not outer_nodes or not inner_nodes or not env_nodes:
                continue
            outer = _text(outer_nodes[0])
            inner = _text(inner_nodes[0])
            env_name = _text(env_nodes[0])
            if outer == "process" and inner == "env" and env_name not in seen:
                seen.add(env_name)
                nodes.append(Node(
                    id=f"env:{env_name}", type=NodeType.ENV_VAR, label=env_name,
                    file_path=rel, metadata={"variable": env_name},
                ))

        # Regex fallback: process.env["KEY"]
        for m in re.finditer(r'process\.env\["([^"]+)"\]', content):
            var = m.group(1)
            if var not in seen:
                seen.add(var)
                nodes.append(Node(
                    id=f"env:{var}", type=NodeType.ENV_VAR, label=var,
                    file_path=rel, metadata={"variable": var},
                ))


# ---------------------------------------------------------------------------
# Rust AST Recognizer
# ---------------------------------------------------------------------------

_RS_STRUCT_QUERY = """
(struct_item
  name: (type_identifier) @struct_name)
"""


class RustASTRecognizer:
    """AST-based Rust pattern recognizer using tree-sitter.

    Detected patterns:
        - Actix-web route attributes (#[get], #[post])  -> ``endpoint`` nodes
        - Struct definitions                              -> ``service`` nodes
    """

    def __init__(self) -> None:
        if not HAS_TREE_SITTER:
            raise ImportError("tree-sitter packages required for AST scanning")
        self._parser, self._language = _make_parser(_ts_rust)

    def recognize(self, file_path: Path, content: str) -> ScanResult:
        if not content.strip():
            return ScanResult()

        tree = self._parser.parse(content.encode())
        nodes: list[Node] = []
        rel = str(file_path)

        self._find_routes(content, rel, nodes)
        self._find_structs(tree, rel, nodes)

        return ScanResult(nodes=nodes, edges=[])

    def _find_routes(self, content: str, rel: str, nodes: list[Node]) -> None:
        """Detect Actix-web #[get("/path")] style route attributes via regex."""
        seen: set[str] = set()
        for m in re.finditer(r'#\[(get|post|put|delete|patch|head)\("([^"]+)"\)\]', content, re.IGNORECASE):
            route = m.group(2)
            if route not in seen:
                seen.add(route)
                nodes.append(Node(
                    id=f"endpoint:{route}", type=NodeType.ENDPOINT,
                    label=route, file_path=rel,
                    metadata={"route": route, "method": m.group(1).upper()},
                ))

    def _find_structs(self, tree: Any, rel: str, nodes: list[Node]) -> None:
        for _pat, caps in _query_matches(self._language, _RS_STRUCT_QUERY, tree.root_node):
            name_nodes = caps.get("struct_name", [])
            if name_nodes:
                name = _text(name_nodes[0])
                nodes.append(Node(
                    id=f"service:{name}", type=NodeType.SERVICE, label=name,
                    file_path=rel, metadata={"struct_name": name},
                ))


# ---------------------------------------------------------------------------
# Java AST Recognizer
# ---------------------------------------------------------------------------

_JAVA_CLASS_QUERY = """
(class_declaration
  name: (identifier) @class_name)
"""

_JAVA_ANNOTATION_QUERY = """
(annotation
  name: (identifier) @ann_name
  arguments: (annotation_argument_list) @ann_args)
"""

_JAVA_MARKER_ANNOTATION_QUERY = """
(marker_annotation
  name: (identifier) @ann_name)
"""


class JavaASTRecognizer:
    """AST-based Java pattern recognizer using tree-sitter.

    Detected patterns:
        - Spring ``@GetMapping`` / ``@PostMapping``  -> ``endpoint`` nodes
        - ``@RequestMapping``                         -> ``endpoint`` nodes
        - ``@Entity`` / ``@Table``                   -> ``database_table`` nodes
        - Class definitions                           -> ``service`` nodes (fallback)
    """

    def __init__(self) -> None:
        if not HAS_TREE_SITTER:
            raise ImportError("tree-sitter packages required for AST scanning")
        self._parser, self._language = _make_parser(_ts_java)

    def recognize(self, file_path: Path, content: str) -> ScanResult:
        if not content.strip():
            return ScanResult()

        tree = self._parser.parse(content.encode())
        nodes: list[Node] = []
        rel = str(file_path)

        entity_classes: set[str] = set()
        self._find_annotations(tree, rel, nodes, entity_classes)
        self._find_classes(tree, rel, nodes, entity_classes)

        return ScanResult(nodes=nodes, edges=[])

    def _find_annotations(
        self, tree: Any, rel: str, nodes: list[Node], entity_classes: set[str],
    ) -> None:
        seen_routes: set[str] = set()
        seen_tables: set[str] = set()
        mapping_annotations = {
            "GetMapping", "PostMapping", "PutMapping", "DeleteMapping",
            "PatchMapping", "RequestMapping",
        }

        # Annotations with arguments
        for _pat, caps in _query_matches(self._language, _JAVA_ANNOTATION_QUERY, tree.root_node):
            ann_nodes = caps.get("ann_name", [])
            args_nodes = caps.get("ann_args", [])
            if not ann_nodes:
                continue
            ann_name = _text(ann_nodes[0])
            ann_args = _text(args_nodes[0]) if args_nodes else ""

            if ann_name in mapping_annotations:
                m = re.search(r'"([^"]+)"', ann_args)
                if m:
                    route = m.group(1)
                    if route not in seen_routes:
                        seen_routes.add(route)
                        nodes.append(Node(
                            id=f"endpoint:{route}", type=NodeType.ENDPOINT,
                            label=route, file_path=rel,
                            metadata={"route": route, "annotation": ann_name},
                        ))

            elif ann_name == "Table":
                m = re.search(r'name\s*=\s*"([^"]+)"', ann_args)
                if m:
                    tbl = m.group(1)
                    if tbl not in seen_tables:
                        seen_tables.add(tbl)
                        nodes.append(Node(
                            id=f"table:{tbl}", type=NodeType.DATABASE_TABLE,
                            label=tbl, file_path=rel,
                            metadata={"table_name": tbl},
                        ))

        # Marker annotations (no arguments) like @Entity
        for _pat, caps in _query_matches(self._language, _JAVA_MARKER_ANNOTATION_QUERY, tree.root_node):
            ann_nodes = caps.get("ann_name", [])
            if not ann_nodes:
                continue
            ann_name = _text(ann_nodes[0])
            if ann_name == "Entity":
                # Walk up to find the class name
                marker_node = ann_nodes[0].parent  # marker_annotation
                if marker_node and marker_node.parent:
                    container = marker_node.parent
                    for child in container.children:
                        if child.type == "class_declaration":
                            for sub in child.children:
                                if sub.type == "identifier":
                                    entity_classes.add(_text(sub))
                                    break

        # @Entity without @Table -> derive table from class name
        for cls in entity_classes:
            tbl = cls.lower()
            if tbl not in seen_tables:
                seen_tables.add(tbl)
                nodes.append(Node(
                    id=f"table:{tbl}", type=NodeType.DATABASE_TABLE,
                    label=tbl, file_path=rel,
                    metadata={"class_name": cls, "table_name": tbl},
                ))

    def _find_classes(
        self, tree: Any, rel: str, nodes: list[Node], entity_classes: set[str],
    ) -> None:
        existing_ids = {n.id for n in nodes}
        for _pat, caps in _query_matches(self._language, _JAVA_CLASS_QUERY, tree.root_node):
            name_nodes = caps.get("class_name", [])
            if not name_nodes:
                continue
            cls = _text(name_nodes[0])
            nid = f"service:{cls}"
            if cls not in entity_classes and nid not in existing_ids:
                existing_ids.add(nid)
                nodes.append(Node(
                    id=nid, type=NodeType.SERVICE, label=cls,
                    file_path=rel, metadata={"class_name": cls},
                ))


# ---------------------------------------------------------------------------
# Registry helper
# ---------------------------------------------------------------------------


def get_ast_registry() -> "RecognizerRegistry":
    """Create a :class:`RecognizerRegistry` populated with AST-based recognizers.

    Raises :class:`ImportError` if tree-sitter packages are not installed.
    """
    from codegiraffe.registry import RecognizerRegistry

    if not HAS_TREE_SITTER:
        raise ImportError("tree-sitter packages required for AST registry")

    registry = RecognizerRegistry()
    registry.register(PythonASTRecognizer(), extensions=[".py", ".pyi"])
    registry.register(GoASTRecognizer(), extensions=[".go"])
    registry.register(TypeScriptASTRecognizer(), extensions=[".ts", ".tsx"])
    registry.register(RustASTRecognizer(), extensions=[".rs"])
    registry.register(JavaASTRecognizer(), extensions=[".java"])
    return registry

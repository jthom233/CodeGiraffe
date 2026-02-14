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
from codegiraffe.scanner import CallInfo, ScanResult
from codegiraffe.schema import EdgeType, NodeType

# Import Go stdlib package set for filtering (shared with regex recognizer)
from codegiraffe.recognizers.go import _GO_STDLIB_PACKAGES

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

# T096: Python call expression queries for AST-based call detection
_PY_SIMPLE_CALL_QUERY = """
(call
  function: (identifier) @func_name
  arguments: (argument_list) @args)
"""

# Python builtins to filter from call detection (mirrors scanner.py _PYTHON_BUILTINS)
_PY_AST_BUILTINS = frozenset({
    "print", "len", "range", "str", "int", "float", "bool", "list", "dict",
    "set", "tuple", "type", "isinstance", "issubclass", "hasattr", "getattr",
    "setattr", "delattr", "super", "property", "staticmethod", "classmethod",
    "open", "input", "enumerate", "zip", "map", "filter", "sorted", "reversed",
    "min", "max", "sum", "abs", "round", "any", "all", "next", "iter",
    "repr", "hash", "id", "dir", "vars", "globals", "locals", "exec", "eval",
    "compile", "breakpoint", "exit", "quit",
})

# Go builtins to filter from call detection
_GO_AST_BUILTINS = frozenset({
    "make", "append", "len", "cap", "copy", "delete",
    "close", "panic", "recover", "new", "print", "println",
})

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

        # T097: Call detection via AST
        calls = self._find_calls(tree, rel)

        return ScanResult(nodes=nodes, edges=edges, calls=calls)

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

    # -- call detection (v0.9.0 Phase 4) ------------------------------------

    @staticmethod
    def _find_enclosing_func_ast(node: Any) -> tuple[str, str]:
        """Walk tree-sitter parents to find enclosing class and function.

        Returns ``(class_name, func_name)`` where either may be empty.
        """
        func_name = ""
        class_name = ""
        current = node.parent
        while current is not None:
            if current.type == "function_definition":
                for child in current.children:
                    if child.type == "identifier":
                        func_name = _text(child)
                        break
            elif current.type == "class_definition":
                for child in current.children:
                    if child.type == "identifier":
                        class_name = _text(child)
                        break
            current = current.parent
        return class_name, func_name

    def _find_calls(self, tree: Any, rel: str) -> list[CallInfo]:
        """T097: Extract call expressions from Python AST and produce CallInfo records."""
        calls: list[CallInfo] = []

        # Attribute calls: obj.method(args)
        for _pat, caps in _query_matches(self._language, _PY_ATTR_CALL_QUERY, tree.root_node):
            obj_nodes = caps.get("obj", [])
            method_nodes = caps.get("method", [])
            if not obj_nodes or not method_nodes:
                continue
            receiver = _text(obj_nodes[0])
            callee = _text(method_nodes[0])

            # Skip builtins as receiver or callee
            if receiver in _PY_AST_BUILTINS or callee in _PY_AST_BUILTINS:
                continue
            # Skip known library calls (requests, os, etc.)
            if receiver in ("requests", "os", "sys", "re", "json", "logging"):
                continue

            call_node = obj_nodes[0]
            # Walk up to find the call_expression node
            while call_node is not None and call_node.type != "call":
                call_node = call_node.parent

            enc_class, enc_func = self._find_enclosing_func_ast(
                call_node if call_node else obj_nodes[0],
            )

            if receiver == "self":
                style = "method"
                receiver = enc_class
            else:
                style = "method"

            caller = f"{enc_class}.{enc_func}" if enc_class and enc_func else enc_func

            calls.append(CallInfo(
                caller=caller,
                callee=callee,
                receiver=receiver,
                file_path=rel,
                style=style,
            ))

        # Simple calls: FunctionName(args) -- constructors or plain functions
        for _pat, caps in _query_matches(self._language, _PY_SIMPLE_CALL_QUERY, tree.root_node):
            func_nodes = caps.get("func_name", [])
            if not func_nodes:
                continue
            callee = _text(func_nodes[0])

            # Skip builtins
            if callee in _PY_AST_BUILTINS:
                continue

            call_node = func_nodes[0]
            while call_node is not None and call_node.type != "call":
                call_node = call_node.parent

            enc_class, enc_func = self._find_enclosing_func_ast(
                call_node if call_node else func_nodes[0],
            )

            caller = f"{enc_class}.{enc_func}" if enc_class and enc_func else enc_func

            # Uppercase first letter -> constructor style
            style = "constructor" if callee[0:1].isupper() else "direct"

            calls.append(CallInfo(
                caller=caller,
                callee=callee,
                receiver="",
                file_path=rel,
                style=style,
            ))

        return calls


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

# Broader call query that matches chained selectors (e.g. a.store.Save())
_GO_BROAD_CALL_QUERY = """
(call_expression
  function: (selector_expression
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

        # T095: Call detection via AST
        calls = self._find_calls(tree, rel)

        return ScanResult(nodes=nodes, edges=[], calls=calls)

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

    # -- call detection (v0.9.0 Phase 4) ------------------------------------

    @staticmethod
    def _find_enclosing_func_ast(node: Any) -> str:
        """T094: Walk tree-sitter parents to find enclosing function/method.

        For method declarations like ``func (a *App) Update()``, returns "App.Update".
        For plain functions like ``func main()``, returns "main".
        Returns empty string if no enclosing function is found.
        """
        current = node.parent
        while current is not None:
            if current.type == "function_declaration":
                # Plain function: func FuncName(
                for child in current.children:
                    if child.type == "identifier":
                        return _text(child)
            elif current.type == "method_declaration":
                # Method with receiver: func (r *Type) MethodName(
                receiver_type = ""
                method_name = ""
                for child in current.children:
                    if child.type == "parameter_list":
                        # This is the receiver parameter list
                        for param_child in child.children:
                            if param_child.type == "parameter_declaration":
                                for pc in param_child.children:
                                    if pc.type == "pointer_type":
                                        for pt in pc.children:
                                            if pt.type == "type_identifier":
                                                receiver_type = _text(pt)
                                    elif pc.type == "type_identifier":
                                        receiver_type = _text(pc)
                    elif child.type == "field_identifier":
                        method_name = _text(child)
                if receiver_type and method_name:
                    return f"{receiver_type}.{method_name}"
                elif method_name:
                    return method_name
            current = current.parent
        return ""

    @staticmethod
    def _extract_receiver(method_node: Any) -> str:
        """Extract receiver name from a selector_expression's operand.

        For ``a.store.Save``, the method_node is ``Save`` and the receiver
        is derived from the operand. For chained selectors like ``a.store``,
        the last ``field_identifier`` (``store``) is returned as the receiver.
        For simple selectors like ``db.Query``, the ``identifier`` (``db``)
        is returned.
        """
        sel_expr = method_node.parent  # selector_expression
        if sel_expr is None:
            return ""
        operand = sel_expr.children[0] if sel_expr.children else None
        if operand is None:
            return ""
        if operand.type == "identifier":
            return _text(operand)
        elif operand.type == "selector_expression":
            # Chained: get the last field_identifier (e.g. "store" from "a.store")
            for child in reversed(operand.children):
                if child.type == "field_identifier":
                    return _text(child)
            # Fallback: get identifier at the start of the chain
            for child in operand.children:
                if child.type == "identifier":
                    return _text(child)
        return _text(operand)

    def _find_calls(self, tree: Any, rel: str) -> list[CallInfo]:
        """T093: Extract call expressions from Go AST and produce CallInfo records.

        Uses ``_GO_BROAD_CALL_QUERY`` to find ``receiver.Method(args)`` patterns
        including chained selectors (e.g. ``a.store.Save()``). Filters stdlib
        packages and Go builtins.
        """
        calls: list[CallInfo] = []

        for _pat, caps in _query_matches(self._language, _GO_BROAD_CALL_QUERY, tree.root_node):
            method_nodes = caps.get("method", [])
            if not method_nodes:
                continue
            callee = _text(method_nodes[0])
            receiver = self._extract_receiver(method_nodes[0])

            # T092: Filter stdlib packages
            if receiver.lower() in _GO_STDLIB_PACKAGES or receiver in _GO_STDLIB_PACKAGES:
                continue
            # Filter Go builtins
            if callee in _GO_AST_BUILTINS:
                continue

            # Find enclosing function context
            call_node = method_nodes[0]
            while call_node is not None and call_node.type != "call_expression":
                call_node = call_node.parent

            caller = self._find_enclosing_func_ast(
                call_node if call_node else method_nodes[0],
            )

            calls.append(CallInfo(
                caller=caller,
                callee=callee,
                receiver=receiver,
                file_path=rel,
                style="method",
            ))

        return calls


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

        # T098: Call detection via AST
        calls = self._find_calls(tree, rel)

        return ScanResult(nodes=nodes, edges=[], calls=calls)

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

    # -- call detection (v0.9.0 Phase 4) ------------------------------------

    # TypeScript builtins to skip in call detection
    _TS_AST_BUILTINS = frozenset({
        "console", "Math", "JSON", "Object", "Array", "String", "Number",
        "Boolean", "Date", "RegExp", "Error", "Promise", "Map", "Set",
        "parseInt", "parseFloat", "setTimeout", "setInterval",
        "clearTimeout", "clearInterval", "require", "process",
    })

    @staticmethod
    def _find_enclosing_func_ast(node: Any) -> tuple[str, str]:
        """Walk tree-sitter parents to find enclosing class and function.

        Returns ``(class_name, func_name)``.
        """
        func_name = ""
        class_name = ""
        current = node.parent
        while current is not None:
            if current.type in ("function_declaration", "method_definition",
                                "arrow_function"):
                for child in current.children:
                    if child.type in ("identifier", "property_identifier"):
                        func_name = _text(child)
                        break
            elif current.type == "class_declaration":
                for child in current.children:
                    if child.type == "type_identifier":
                        class_name = _text(child)
                        break
            current = current.parent
        return class_name, func_name

    def _find_calls(self, tree: Any, rel: str) -> list[CallInfo]:
        """T098: Extract call expressions from TypeScript AST and produce CallInfo records."""
        calls: list[CallInfo] = []

        for _pat, caps in _query_matches(self._language, _TS_CALL_QUERY, tree.root_node):
            obj_nodes = caps.get("obj", [])
            method_nodes = caps.get("method", [])
            if not obj_nodes or not method_nodes:
                continue
            receiver = _text(obj_nodes[0])
            callee = _text(method_nodes[0])

            # Skip TS builtins
            if receiver in self._TS_AST_BUILTINS or callee in self._TS_AST_BUILTINS:
                continue

            # Skip HTTP route methods (already handled by _find_routes)
            http_methods = {"get", "post", "put", "delete", "patch", "head", "options"}
            if callee.lower() in http_methods:
                continue

            call_node = obj_nodes[0]
            while call_node is not None and call_node.type != "call_expression":
                call_node = call_node.parent

            enc_class, enc_func = self._find_enclosing_func_ast(
                call_node if call_node else obj_nodes[0],
            )

            if receiver == "this":
                style = "method"
                receiver = enc_class
            else:
                style = "method"

            caller = f"{enc_class}.{enc_func}" if enc_class and enc_func else enc_func

            calls.append(CallInfo(
                caller=caller,
                callee=callee,
                receiver=receiver,
                file_path=rel,
                style=style,
            ))

        return calls


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

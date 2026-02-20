"""TypeScript/JavaScript pattern recognizer for Code Giraffe.

Detects architectural patterns in .ts and .tsx files including:
    - Express/Fastify/Koa routes and NestJS decorators -> endpoint nodes
    - TypeORM entities and Prisma models               -> database_table nodes
    - process.env access                               -> env_var nodes
    - fetch/axios HTTP calls                           -> external_api nodes
    - EventEmitter emit/on/once                        -> event nodes
    - React/Vue component exports                      -> frontend_component nodes
    - Bull/BullMQ queue/worker definitions             -> worker nodes
    - Class definitions (fallback)                     -> service nodes
"""

from __future__ import annotations

import re
from pathlib import Path

from codegiraffe.graph import Edge, Node
from codegiraffe.scanner import ScanResult, ImportInfo, ImplementationInfo, CallInfo
from codegiraffe.schema import EdgeType, NodeType

# ---------------------------------------------------------------------------
# Compiled regex patterns
# ---------------------------------------------------------------------------

# Express/Fastify/Koa routes
_TS_ROUTE_RE = re.compile(
    r"""(?:app|router|server)\s*\.\s*(?:get|post|put|delete|patch|options|all)\s*\(\s*['"](\/[^'"]*?)['"]""",
    re.IGNORECASE,
)

# NestJS decorators
_TS_NEST_ROUTE_RE = re.compile(
    r"""@(?:Get|Post|Put|Delete|Patch|Options|All)\s*\(\s*['"](\/[^'"]*?)['"]""",
)

# TypeORM Entity
_TS_TYPEORM_RE = re.compile(
    r"""@Entity\s*\(\s*(?:['"]([\w]+)['"])?\s*\)""",
)

# Prisma model
_TS_PRISMA_RE = re.compile(
    r"""^\s*model\s+(\w+)\s*\{""",
    re.MULTILINE,
)

# process.env
_TS_ENV_RE = re.compile(
    r"""process\.env\.(\w+)|process\.env\s*\[\s*['"]([\w]+)['"]\s*\]""",
)

# fetch/axios
_TS_FETCH_RE = re.compile(
    r"""(?:fetch|axios\.(?:get|post|put|delete|patch))\s*\(\s*['"](https?://[^'"]+?)['"]""",
)

# Event emitter
_TS_EVENT_EMIT_RE = re.compile(
    r"""\.(?:emit|on|once)\s*\(\s*['"]([\w:.]+?)['"]""",
)

# TypeScript enum (exported or non-exported, const or plain)
_TS_ENUM_RE = re.compile(
    r"""^\s*(?:export\s+)?(?:const\s+)?enum\s+([A-Z]\w*)""",
    re.MULTILINE,
)

# React/Vue component export — negative lookahead prevents `const enum` from matching.
# Use const(?!\s+enum\b) so `const` does NOT consume whitespace; the outer \s+ handles it.
_TS_COMPONENT_RE = re.compile(
    r"""^\s*export\s+(?:default\s+)?(?:function|const(?!\s+enum\b)|class)\s+(\w+)""",
    re.MULTILINE,
)

# Class definitions -- require PascalCase to avoid false positives from keywords
# like `is`, `manually`, `on`, `new`, `export` that appear after `class` in
# comments or template literals that survived stripping.
_TS_CLASS_RE = re.compile(
    r"""^\s*(?:export\s+)?(?:abstract\s+)?class\s+([A-Z]\w*)""",
    re.MULTILINE,
)

# Queue (Bull/BullMQ)
_TS_QUEUE_RE = re.compile(
    r"""new\s+(?:Queue|Worker)\s*\(\s*['"]([\w-]+?)['"]""",
)


# ES6 import patterns (v0.6.0)
_TS_NAMED_IMPORT_RE = re.compile(r"""import\s+\{([^}]+)\}\s+from\s+['"]([^'"]+)['"]""")
_TS_DEFAULT_IMPORT_RE = re.compile(r"""import\s+(\w+)\s+from\s+['"]([^'"]+)['"]""")
_TS_NAMESPACE_IMPORT_RE = re.compile(r"""import\s+\*\s+as\s+\w+\s+from\s+['"]([^'"]+)['"]""")
_TS_CLASS_EXTENDS_RE = re.compile(r'^\s*(?:export\s+)?(?:abstract\s+)?class\s+(\w+)\s+extends\s+(\w+)', re.MULTILINE)
_TS_CLASS_IMPLEMENTS_RE = re.compile(r'^\s*(?:export\s+)?(?:abstract\s+)?class\s+(\w+)\s+(?:extends\s+\w+\s+)?implements\s+([\w,\s<>]+?)(?:\s*\{)', re.MULTILINE)

# ---------------------------------------------------------------------------
# TypeScript call detection (v0.9.0)
# ---------------------------------------------------------------------------

_TS_METHOD_CALL_RE = re.compile(r'(?:(\w+)\.)?(\w+)\s*\(')
_TS_FUNC_DEF_RE = re.compile(
    r'(?:(?:async\s+)?function\s+(\w+)|(?:export\s+)?(?:async\s+)?(\w+)\s*\([^)]*\)\s*(?::\s*[\w<>\[\]|&\s]+)?\s*\{)',
    re.MULTILINE,
)
_TS_CLASS_DEF_RE = re.compile(r'^\s*(?:export\s+)?(?:abstract\s+)?class\s+(\w+)', re.MULTILINE)
_TS_NEW_CONSTRUCTOR_RE = re.compile(r'new\s+(\w+)\s*\(')

_TS_BUILTINS = frozenset({
    "console", "JSON", "Math", "Object", "Array", "String", "Number",
    "Boolean", "Date", "RegExp", "Error", "Promise", "Map", "Set",
    "parseInt", "parseFloat", "isNaN", "isFinite", "setTimeout",
    "setInterval", "clearTimeout", "clearInterval", "fetch",
    "require", "module", "exports",
})


def _find_ts_enclosing_context(content: str) -> dict[int, tuple[str, str]]:
    """Build a mapping of line_number -> (enclosing_class, enclosing_function).

    For methods inside a class, returns e.g. ("App", "render").
    For top-level functions, returns ("", "handler").
    """
    result: dict[int, tuple[str, str]] = {}
    lines = content.split('\n')

    class_ranges: list[tuple[int, str]] = []
    func_ranges: list[tuple[int, str]] = []

    for match in _TS_CLASS_DEF_RE.finditer(content):
        class_name = match.group(1)
        start_line = content[:match.start()].count('\n')
        class_ranges.append((start_line, class_name))

    for match in _TS_FUNC_DEF_RE.finditer(content):
        func_name = match.group(1) or match.group(2) or ""
        if func_name:
            start_line = content[:match.start()].count('\n')
            func_ranges.append((start_line, func_name))

    for line_no in range(len(lines)):
        current_class = ""
        for cls_start, cls_name in class_ranges:
            if cls_start <= line_no:
                current_class = cls_name
            else:
                break

        current_func = ""
        for func_start, func_name in func_ranges:
            if func_start <= line_no:
                current_func = func_name
            else:
                break

        result[line_no] = (current_class, current_func)

    return result


def _is_internal_ts_import(import_path: str) -> bool:
    return import_path.startswith(("./", "../", "@/", "~/"))

def _ts_import_to_module_path(import_path: str) -> str:
    cleaned = import_path.lstrip("./")
    for ext in (".ts", ".tsx", ".js", ".jsx", ".mts", ".cts", "/index"):
        if cleaned.endswith(ext):
            cleaned = cleaned[:-len(ext)]
    return cleaned.replace("/", ".")


# ---------------------------------------------------------------------------
# Comment stripping
# ---------------------------------------------------------------------------

def _strip_ts_comments(text: str) -> str:
    """Remove JS/TS comments and template literal content while preserving string literals.

    Template literal *content* is replaced with an equivalent number of newlines so
    that line-based regex patterns (e.g. _TS_CLASS_RE with re.MULTILINE) still match
    at the correct line numbers.  Only the backtick delimiters are kept.
    """
    def _replacer(match: re.Match) -> str:
        if match.group(1) is not None:  # single-quoted string
            return match.group(0)
        if match.group(2) is not None:  # double-quoted string
            return match.group(0)
        if match.group(3) is not None:  # template literal -- blank out contents
            inner = match.group(3)
            # Preserve only the newlines so multiline patterns stay aligned
            newlines = "\n" * inner.count("\n")
            return f"`{newlines}`"
        return ""  # comment -- remove it

    return re.sub(
        r"""('(?:\\.|[^'\\])*')"""       # group 1: single-quoted string
        r"""|("(?:\\.|[^"\\])*")"""      # group 2: double-quoted string
        r"""|(`(?:\\.|[^`\\])*`)"""      # group 3: template literal
        r"""|(\/\*[\s\S]*?\*\/)"""       # group 4: block comment
        r"""|(\/\/[^\n]*)""",            # group 5: line comment
        _replacer,
        text,
    )


# ---------------------------------------------------------------------------
# Recognizer
# ---------------------------------------------------------------------------


class TypeScriptRecognizer:
    """Recognizes common TypeScript/JavaScript architectural patterns via regex.

    Detected patterns:
        - Express/Fastify/Koa routes and NestJS decorators -> ``endpoint`` nodes
        - TypeORM entities and Prisma models               -> ``database_table`` nodes
        - ``process.env`` access                           -> ``env_var`` nodes
        - ``fetch`` / ``axios`` HTTP calls                 -> ``external_api`` nodes
        - EventEmitter emit/on/once                        -> ``event`` nodes
        - React/Vue component exports                      -> ``frontend_component`` nodes
        - Bull/BullMQ queue/worker definitions             -> ``worker`` nodes
        - Class definitions (fallback)                     -> ``service`` nodes
    """

    def recognize(self, file_path: Path, content: str) -> ScanResult:
        """Scan *content* of a TypeScript file and return discovered nodes/edges."""
        # Strip comments to prevent false positives from JSDoc/block comments
        content = _strip_ts_comments(content)
        nodes: list[Node] = []
        edges: list[Edge] = []
        rel_path = file_path.as_posix()

        endpoint_ids: list[str] = []
        table_ids: list[str] = []
        captured_class_names: set[str] = set()

        # --- Endpoints (Express/Fastify/Koa) ---
        seen_routes: set[str] = set()
        for match in _TS_ROUTE_RE.finditer(content):
            route_path = match.group(1)
            if route_path not in seen_routes:
                seen_routes.add(route_path)
                node_id = f"endpoint:{route_path}"
                nodes.append(
                    Node(
                        id=node_id,
                        type=NodeType.ENDPOINT,
                        label=route_path,
                        file_path=rel_path,
                        metadata={"route": route_path, "framework": "express"},
                    )
                )
                endpoint_ids.append(node_id)

        # --- Endpoints (NestJS decorators) ---
        for match in _TS_NEST_ROUTE_RE.finditer(content):
            route_path = match.group(1)
            if route_path not in seen_routes:
                seen_routes.add(route_path)
                node_id = f"endpoint:{route_path}"
                nodes.append(
                    Node(
                        id=node_id,
                        type=NodeType.ENDPOINT,
                        label=route_path,
                        file_path=rel_path,
                        metadata={"route": route_path, "framework": "nestjs"},
                    )
                )
                endpoint_ids.append(node_id)

        # --- Database tables (TypeORM) ---
        for match in _TS_TYPEORM_RE.finditer(content):
            entity_name = match.group(1)
            if entity_name:
                node_id = f"table:{entity_name}"
                nodes.append(
                    Node(
                        id=node_id,
                        type=NodeType.DATABASE_TABLE,
                        label=entity_name,
                        file_path=rel_path,
                        metadata={"entity": entity_name, "orm": "typeorm"},
                    )
                )
                table_ids.append(node_id)

        # --- Database tables (Prisma) ---
        for match in _TS_PRISMA_RE.finditer(content):
            model_name = match.group(1)
            node_id = f"table:{model_name}"
            nodes.append(
                Node(
                    id=node_id,
                    type=NodeType.DATABASE_TABLE,
                    label=model_name,
                    file_path=rel_path,
                    metadata={"model": model_name, "orm": "prisma"},
                )
            )
            table_ids.append(node_id)

        # --- Environment variables ---
        seen_env_vars: set[str] = set()
        for match in _TS_ENV_RE.finditer(content):
            var_name = match.group(1) or match.group(2)
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

        # --- External API calls (fetch/axios) ---
        seen_urls: set[str] = set()
        for match in _TS_FETCH_RE.finditer(content):
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

        # --- Events (emit/on/once) ---
        seen_events: set[str] = set()
        for match in _TS_EVENT_EMIT_RE.finditer(content):
            event_name = match.group(1)
            if event_name not in seen_events:
                seen_events.add(event_name)
                node_id = f"event:{event_name}"
                nodes.append(
                    Node(
                        id=node_id,
                        type=NodeType.EVENT,
                        label=event_name,
                        file_path=rel_path,
                        metadata={"event": event_name},
                    )
                )

        # --- Workers (Bull/BullMQ) ---
        seen_queues: set[str] = set()
        for match in _TS_QUEUE_RE.finditer(content):
            queue_name = match.group(1)
            if queue_name not in seen_queues:
                seen_queues.add(queue_name)
                node_id = f"worker:{queue_name}"
                nodes.append(
                    Node(
                        id=node_id,
                        type=NodeType.WORKER,
                        label=queue_name,
                        file_path=rel_path,
                        metadata={"queue": queue_name},
                    )
                )

        # --- Enums (exported/non-exported, const or plain) ---
        seen_enums: set[str] = set()
        for match in _TS_ENUM_RE.finditer(content):
            enum_name = match.group(1)
            if enum_name not in seen_enums:
                seen_enums.add(enum_name)
                captured_class_names.add(enum_name)
                node_id = f"component:{enum_name}"
                nodes.append(
                    Node(
                        id=node_id,
                        type=NodeType.FRONTEND_COMPONENT,
                        label=enum_name,
                        file_path=rel_path,
                        metadata={"component": enum_name, "kind": "enum"},
                    )
                )

        # --- Frontend components (React/Vue exports) ---
        seen_components: set[str] = set()
        for match in _TS_COMPONENT_RE.finditer(content):
            component_name = match.group(1)
            if component_name not in seen_components:
                seen_components.add(component_name)
                captured_class_names.add(component_name)
                node_id = f"component:{component_name}"
                nodes.append(
                    Node(
                        id=node_id,
                        type=NodeType.FRONTEND_COMPONENT,
                        label=component_name,
                        file_path=rel_path,
                        metadata={"component": component_name},
                    )
                )

        # --- Class definitions (fallback to service nodes) ---
        for match in _TS_CLASS_RE.finditer(content):
            class_name = match.group(1)
            if class_name not in captured_class_names:
                captured_class_names.add(class_name)
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
        if endpoint_ids and table_ids:
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

        # Import parsing (v0.6.0)
        imports: list[ImportInfo] = []
        for match in _TS_NAMED_IMPORT_RE.finditer(content):
            symbols_str, import_path = match.group(1), match.group(2)
            if _is_internal_ts_import(import_path):
                symbols = [s.strip().split(" as ")[0].strip() for s in symbols_str.split(",") if s.strip()]
                imports.append(ImportInfo(
                    module_path=_ts_import_to_module_path(import_path),
                    symbols=symbols,
                    style="relative" if import_path.startswith(("./", "../")) else "absolute",
                ))
        for match in _TS_DEFAULT_IMPORT_RE.finditer(content):
            default_name, import_path = match.group(1), match.group(2)
            if _is_internal_ts_import(import_path):
                imports.append(ImportInfo(
                    module_path=_ts_import_to_module_path(import_path),
                    symbols=[default_name],
                    style="relative" if import_path.startswith(("./", "../")) else "absolute",
                ))
        for match in _TS_NAMESPACE_IMPORT_RE.finditer(content):
            import_path = match.group(1)
            if _is_internal_ts_import(import_path):
                imports.append(ImportInfo(module_path=_ts_import_to_module_path(import_path), symbols=[], style="wildcard"))

        # Inheritance detection (v0.6.0)
        implementations: list[ImplementationInfo] = []
        for match in _TS_CLASS_EXTENDS_RE.finditer(content):
            implementations.append(ImplementationInfo(child_class=match.group(1), parent_class=match.group(2), file_path=str(file_path)))
        for match in _TS_CLASS_IMPLEMENTS_RE.finditer(content):
            child = match.group(1)
            for parent in [p.strip().split("<")[0].strip() for p in match.group(2).split(",") if p.strip()]:
                if parent:
                    implementations.append(ImplementationInfo(child_class=child, parent_class=parent, file_path=str(file_path)))

        # --- Call detection (v0.9.0) ---
        calls: list[CallInfo] = []
        enclosing_ctx = _find_ts_enclosing_context(content)
        rel_path_str = file_path.as_posix()

        # Detect "new Constructor()" calls
        for match in _TS_NEW_CONSTRUCTOR_RE.finditer(content):
            callee = match.group(1)
            if callee in _TS_BUILTINS:
                continue
            line_no = content[:match.start()].count('\n')
            enc_class, enc_func = enclosing_ctx.get(line_no, ("", ""))
            caller = f"{enc_class}.{enc_func}" if enc_class and enc_func else enc_func
            calls.append(CallInfo(
                caller=caller,
                callee=callee,
                receiver="",
                file_path=rel_path_str,
                style="constructor",
            ))

        # Detect regular method/function calls
        for match in _TS_METHOD_CALL_RE.finditer(content):
            receiver = match.group(1) or ""
            callee = match.group(2)

            # Skip builtins (both as receiver and callee)
            if receiver in _TS_BUILTINS or callee in _TS_BUILTINS:
                continue
            # Skip "this" as callee itself
            if callee == "this":
                continue

            # Skip import/export/function/class declaration lines
            line_start = content.rfind('\n', 0, match.start()) + 1
            line_prefix = content[line_start:match.start()].lstrip()
            if line_prefix.startswith(('import ', 'export ', 'function ', 'class ', 'interface ')):
                continue
            # Skip "new X(" — already handled above
            pre_text = content[max(0, match.start() - 4):match.start()]
            if pre_text.rstrip().endswith('new'):
                continue

            line_no = content[:match.start()].count('\n')
            enc_class, enc_func = enclosing_ctx.get(line_no, ("", ""))
            caller = f"{enc_class}.{enc_func}" if enc_class and enc_func else enc_func

            # Determine style
            if receiver == "this":
                style = "method"
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

        return ScanResult(nodes=nodes, edges=edges, imports=imports, implementations=implementations, calls=calls)

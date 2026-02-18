"""Go pattern recognizer for Code Giraffe.

Detects architectural patterns in .go files including:
    - net/http, Gin, Echo, Chi route handlers -> endpoint nodes
    - GORM models and db.Table calls          -> database_table nodes
    - os.Getenv / os.LookupEnv access        -> env_var nodes
    - http.Get / http.Post calls              -> external_api nodes
    - Struct definitions (fallback)           -> service nodes
    - Goroutine worker patterns               -> worker nodes
    - Interface definitions                   -> service nodes (kind=interface)
    - Internal package imports                -> depends_on edges
    - Bubbletea message types (*Msg structs)  -> event nodes
    - sql.Open database connections           -> database_table nodes
    - IPC unix socket patterns                -> queue nodes
    - Method receivers                        -> implements edge inference
    - Service-to-env_var configures edges
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from codegiraffe.graph import Edge, Node
from codegiraffe.scanner import (
    CallInfo,
    ImplementationInfo,
    ImportInfo,
    InterfaceInfo,
    MethodSetEntry,
    ScanResult,
)
from codegiraffe.schema import EdgeType, NodeType

# ---------------------------------------------------------------------------
# Compiled regex patterns
# ---------------------------------------------------------------------------

# net/http handlers: http.HandleFunc("/path", ...)
_GO_HTTP_HANDLE_RE = re.compile(
    r"""(?:http|mux)\s*\.\s*(?:HandleFunc|Handle)\s*\(\s*['"](\/[^'"]*?)['"]""",
)

# Gin/Echo/Chi router methods: r.GET("/path", ...), e.GET("/path", ...)
_GO_ROUTER_RE = re.compile(
    r"""\w+\s*\.\s*(?:GET|POST|PUT|DELETE|PATCH|OPTIONS|HEAD|Any|Group)\s*\(\s*['"](\/[^'"]*?)['"]""",
)

# GORM model: type Name struct with gorm.Model embedded
_GO_GORM_MODEL_RE = re.compile(
    r"""type\s+(\w+)\s+struct\s*\{[^}]*gorm\.Model""",
    re.DOTALL,
)

# db.Table("name")
_GO_DB_TABLE_RE = re.compile(
    r"""(?:db|tx)\s*\.\s*Table\s*\(\s*['"]([\w]+)['"]""",
)

# os.Getenv / os.LookupEnv
_GO_ENV_RE = re.compile(
    r"""os\s*\.\s*(?:Getenv|LookupEnv)\s*\(\s*['"]([\w]+)['"]""",
)

# External HTTP calls: http.Get("url"), http.Post("url", ...)
_GO_HTTP_CALL_RE = re.compile(
    r"""http\s*\.\s*(?:Get|Post|Head)\s*\(\s*['"](https?://[^'"]+?)['"]""",
)

# Struct definitions (fallback): type Name struct
_GO_STRUCT_RE = re.compile(
    r"""type\s+(\w+)\s+struct\s*\{""",
)

# Goroutine worker patterns: go func() near queue-like operations
_GO_WORKER_RE = re.compile(
    r"""go\s+(?:func\s*\(|(\w+)\s*\()""",
)

# --- New patterns (v0.3.0) ---

# Interface definitions: type Store interface {
_GO_INTERFACE_RE = re.compile(r'type\s+(\w+)\s+interface\s*\{')

# Internal package imports: "github.com/user/project/internal/store"
_GO_INTERNAL_IMPORT_RE = re.compile(r'"[^"]+/internal/(\w+)"')

# Package declaration: package tui
_GO_PACKAGE_RE = re.compile(r'^package\s+(\w+)', re.MULTILINE)

# Bubbletea message types: type SessionDetachedMsg struct {
_GO_MSG_TYPE_RE = re.compile(r'type\s+(\w+Msg)\s+struct\s*\{')

# sql.Open("sqlite", path)
_GO_SQL_OPEN_RE = re.compile(r'sql\.Open\(\s*"(\w+)"')

# IPC patterns: net.Listen("unix", ...) and net.Dial("unix", ...)
_GO_IPC_LISTEN_RE = re.compile(r'net\.Listen\(\s*"unix"')
_GO_IPC_DIAL_RE = re.compile(r'net\.Dial\(\s*"unix"')

# Method receivers: func (s *Store) Method(
_GO_METHOD_RECEIVER_RE = re.compile(r'func\s+\(\w+\s+\*?(\w+)\)\s+(\w+)\s*\(')

# Full import parsing (v0.6.0)
# Single import: import "path/to/package"
_GO_SINGLE_IMPORT_RE = re.compile(r'import\s+"([^"]+)"')

# Grouped import block: import ( "path1" \n "path2" )
_GO_GROUPED_IMPORT_RE = re.compile(r'import\s*\(([\s\S]*?)\)', re.MULTILINE)

# Individual import line within a group (handles aliases)
_GO_IMPORT_LINE_RE = re.compile(r'(?:\w+\s+)?"([^"]+)"')

# Interface body extraction
_GO_INTERFACE_BODY_RE = re.compile(
    r'type\s+(\w+)\s+interface\s*\{([^}]*)\}',
    re.DOTALL,
)

# Method signature inside interface body
_GO_INTERFACE_METHOD_RE = re.compile(r'(\w+)\s*\(')

# Call detection (v0.9.0)
_GO_FUNC_CALL_RE = re.compile(
    r'(?:(\w+)\.)?(\w+)\s*\(',  # Optional receiver.Method(
)
_GO_FUNC_DEF_RE = re.compile(
    r'^func\s+(?:\(\s*\w+\s+\*?\w+\s*\)\s+)?(\w+)\s*\(',
    re.MULTILINE,
)
_GO_STDLIB_PACKAGES = frozenset({
    "fmt", "log", "os", "io", "net", "http", "strings", "strconv",
    "bytes", "bufio", "context", "crypto", "encoding", "errors",
    "flag", "math", "path", "reflect", "regexp", "runtime", "sort",
    "sync", "testing", "time", "unicode", "unsafe", "filepath",
    "json", "xml", "sql", "template", "exec", "signal", "atomic",
    "slog", "slices", "maps", "cmp",
})


def _find_enclosing_func(content: str) -> dict[int, str]:
    """Build a mapping of line_number -> enclosing function name.

    For method receivers like ``func (a *App) Update()``, returns "App.Update".
    For plain functions like ``func main()``, returns "main".
    """
    result: dict[int, str] = {}
    func_ranges: list[tuple[int, str]] = []

    lines = content.split('\n')

    for match in _GO_FUNC_DEF_RE.finditer(content):
        func_name = match.group(1)
        start_line = content[:match.start()].count('\n')

        # Check if it's a method receiver
        line = lines[start_line] if start_line < len(lines) else ""
        receiver_match = re.match(r'func\s+\(\s*\w+\s+\*?(\w+)\s*\)\s+(\w+)', line)
        if receiver_match:
            func_name = f"{receiver_match.group(1)}.{receiver_match.group(2)}"

        func_ranges.append((start_line, func_name))

    # For each line, find the most recent func definition before it
    for line_no in range(len(lines)):
        current_func = ""
        for func_start, func_name in func_ranges:
            if func_start <= line_no:
                current_func = func_name
            else:
                break
        if current_func:
            result[line_no] = current_func

    return result


# ---------------------------------------------------------------------------
# Recognizer
# ---------------------------------------------------------------------------


class GoRecognizer:
    """Recognizes common Go architectural patterns via regex.

    Detected patterns:
        - net/http, Gin, Echo, Chi route handlers -> ``endpoint`` nodes
        - GORM models and db.Table calls          -> ``database_table`` nodes
        - ``os.Getenv`` / ``os.LookupEnv``       -> ``env_var`` nodes
        - ``http.Get`` / ``http.Post`` calls      -> ``external_api`` nodes
        - Struct definitions (fallback)           -> ``service`` nodes
        - Goroutine worker patterns               -> ``worker`` nodes
        - Interface definitions                   -> ``service`` nodes (kind=interface)
        - Internal package imports                -> ``depends_on`` edges
        - Bubbletea message types (*Msg structs)  -> ``event`` nodes
        - ``sql.Open`` database connections       -> ``database_table`` nodes
        - IPC unix socket patterns                -> ``queue`` nodes
        - Method receivers                        -> ``implements`` edge inference
        - Service-to-env_var configures edges
    """

    def __init__(self) -> None:
        self._go_module_path: str | None = None
        self._project_root: str | None = None

    def set_project_root(self, project_root: str) -> None:
        """Set project root for internal import classification via go.mod."""
        self._project_root = project_root
        go_mod = Path(project_root) / "go.mod"
        if go_mod.exists():
            try:
                for line in go_mod.read_text(encoding="utf-8").splitlines():
                    if line.startswith("module "):
                        self._go_module_path = line.split(None, 1)[1].strip()
                        break
            except OSError:
                pass

    def _is_internal_import(self, import_path: str) -> bool:
        """Return True if import_path is project-internal."""
        if not self._go_module_path:
            return False
        return import_path.startswith(self._go_module_path + "/")

    def _import_to_module_path(self, import_path: str) -> str:
        """Convert a Go import path to a dotted module path relative to project."""
        if self._go_module_path:
            relative = import_path.removeprefix(self._go_module_path + "/")
        else:
            relative = import_path
        return relative.replace("/", ".")

    def _parse_imports(self, content: str) -> list[str]:
        """Parse all import paths from Go source content."""
        import_paths: list[str] = []

        # Grouped imports: import ( "path1" \n "path2" )
        for block_match in _GO_GROUPED_IMPORT_RE.finditer(content):
            block = block_match.group(1)
            for line_match in _GO_IMPORT_LINE_RE.finditer(block):
                import_paths.append(line_match.group(1))

        # Single imports: import "path" (not inside a group)
        # Need to avoid matching imports already captured in grouped blocks
        grouped_ranges = [(m.start(), m.end()) for m in _GO_GROUPED_IMPORT_RE.finditer(content)]
        for match in _GO_SINGLE_IMPORT_RE.finditer(content):
            in_group = any(start <= match.start() <= end for start, end in grouped_ranges)
            if not in_group:
                import_paths.append(match.group(1))

        return import_paths

    def recognize(self, file_path: Path, content: str) -> ScanResult:
        """Scan *content* of a Go file and return discovered nodes/edges."""
        nodes: list[Node] = []
        edges: list[Edge] = []
        rel_path = file_path.as_posix()

        endpoint_ids: list[str] = []
        table_ids: list[str] = []
        captured_struct_names: set[str] = set()
        package_node_names: set[str] = set()
        env_var_ids: list[str] = []
        service_node_ids: list[str] = []

        # --- Extract package name ---
        pkg_match = _GO_PACKAGE_RE.search(content)
        current_package = pkg_match.group(1) if pkg_match else None

        # --- Endpoints (net/http) ---
        seen_routes: set[str] = set()
        for match in _GO_HTTP_HANDLE_RE.finditer(content):
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
                        metadata={"route": route_path, "framework": "net/http"},
                    )
                )
                endpoint_ids.append(node_id)

        # --- Endpoints (Gin/Echo/Chi) ---
        for match in _GO_ROUTER_RE.finditer(content):
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
                        metadata={"route": route_path, "framework": "gin/echo/chi"},
                    )
                )
                endpoint_ids.append(node_id)

        # --- Database tables (GORM models) ---
        for match in _GO_GORM_MODEL_RE.finditer(content):
            model_name = match.group(1)
            captured_struct_names.add(model_name)
            node_id = f"table:{model_name}"
            nodes.append(
                Node(
                    id=node_id,
                    type=NodeType.DATABASE_TABLE,
                    label=model_name,
                    file_path=rel_path,
                    metadata={"model": model_name, "orm": "gorm"},
                )
            )
            table_ids.append(node_id)

        # --- Database tables (db.Table) ---
        seen_tables: set[str] = set()
        for match in _GO_DB_TABLE_RE.finditer(content):
            table_name = match.group(1)
            if table_name not in seen_tables:
                seen_tables.add(table_name)
                node_id = f"table:{table_name}"
                nodes.append(
                    Node(
                        id=node_id,
                        type=NodeType.DATABASE_TABLE,
                        label=table_name,
                        file_path=rel_path,
                        metadata={"table": table_name},
                    )
                )
                table_ids.append(node_id)

        # --- Environment variables ---
        seen_env_vars: set[str] = set()
        for match in _GO_ENV_RE.finditer(content):
            var_name = match.group(1)
            if var_name not in seen_env_vars:
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
                env_var_ids.append(node_id)

        # --- External HTTP calls ---
        seen_urls: set[str] = set()
        for match in _GO_HTTP_CALL_RE.finditer(content):
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

        # --- Interface definitions ---
        for match in _GO_INTERFACE_RE.finditer(content):
            iface_name = match.group(1)
            captured_struct_names.add(iface_name)
            node_id = f"service:{iface_name}"
            nodes.append(
                Node(
                    id=node_id,
                    type=NodeType.SERVICE,
                    label=iface_name,
                    file_path=rel_path,
                    metadata={"kind": "interface", "interface_name": iface_name},
                )
            )
            service_node_ids.append(node_id)

        # --- Bubbletea message types (*Msg structs -> event nodes) ---
        for match in _GO_MSG_TYPE_RE.finditer(content):
            msg_name = match.group(1)
            captured_struct_names.add(msg_name)
            node_id = f"event:{msg_name}"
            nodes.append(
                Node(
                    id=node_id,
                    type=NodeType.EVENT,
                    label=msg_name,
                    file_path=rel_path,
                    metadata={"event": msg_name},
                )
            )

        # --- SQL database connections ---
        seen_drivers: set[str] = set()
        for match in _GO_SQL_OPEN_RE.finditer(content):
            driver_name = match.group(1)
            if driver_name not in seen_drivers:
                seen_drivers.add(driver_name)
                node_id = f"table:db:{driver_name}"
                nodes.append(
                    Node(
                        id=node_id,
                        type=NodeType.DATABASE_TABLE,
                        label=f"db:{driver_name}",
                        file_path=rel_path,
                        metadata={"driver": driver_name},
                    )
                )

        # --- IPC patterns (unix sockets) ---
        has_listen = bool(_GO_IPC_LISTEN_RE.search(content))
        has_dial = bool(_GO_IPC_DIAL_RE.search(content))

        ipc_server_id = None
        ipc_client_id = None

        if has_listen and current_package:
            ipc_server_id = f"ipc:server:{current_package}"
            nodes.append(
                Node(
                    id=ipc_server_id,
                    type=NodeType.QUEUE,
                    label=f"ipc:server:{current_package}",
                    file_path=rel_path,
                    metadata={"kind": "unix_socket", "role": "server"},
                )
            )

        if has_dial and current_package:
            ipc_client_id = f"ipc:client:{current_package}"
            nodes.append(
                Node(
                    id=ipc_client_id,
                    type=NodeType.QUEUE,
                    label=f"ipc:client:{current_package}",
                    file_path=rel_path,
                    metadata={"kind": "unix_socket", "role": "client"},
                )
            )

        if ipc_client_id and ipc_server_id:
            edges.append(
                Edge(
                    source=ipc_client_id,
                    target=ipc_server_id,
                    type=EdgeType.CALLS,
                    metadata={"inferred": True, "mechanism": "unix_socket"},
                )
            )

        # --- Method receivers (for implements inference) ---
        struct_methods: dict[str, set[str]] = defaultdict(set)
        for match in _GO_METHOD_RECEIVER_RE.finditer(content):
            receiver_type = match.group(1)
            method_name = match.group(2)
            struct_methods[receiver_type].add(method_name)

        # --- Struct definitions (fallback to service nodes) ---
        for match in _GO_STRUCT_RE.finditer(content):
            struct_name = match.group(1)
            if struct_name not in captured_struct_names:
                captured_struct_names.add(struct_name)
                node_id = f"service:{struct_name}"
                nodes.append(
                    Node(
                        id=node_id,
                        type=NodeType.SERVICE,
                        label=struct_name,
                        file_path=rel_path,
                        metadata={"struct_name": struct_name},
                    )
                )
                service_node_ids.append(node_id)

        # --- Package node (always created if package declaration exists) ---
        if current_package and current_package not in package_node_names:
            package_node_names.add(current_package)
            nodes.append(
                Node(
                    id=f"pkg:{current_package}",
                    type=NodeType.SERVICE,
                    label=current_package,
                    file_path=rel_path,
                    metadata={"kind": "package"},
                )
            )

        # --- Internal package imports -> depends_on edges ---
        if current_package:
            seen_imports: set[str] = set()
            for match in _GO_INTERNAL_IMPORT_RE.finditer(content):
                imported_pkg = match.group(1)
                if imported_pkg not in seen_imports and imported_pkg != current_package:
                    seen_imports.add(imported_pkg)

                    src_pkg_id = f"pkg:{current_package}"
                    tgt_pkg_id = f"pkg:{imported_pkg}"

                    if imported_pkg not in package_node_names:
                        package_node_names.add(imported_pkg)
                        nodes.append(
                            Node(
                                id=tgt_pkg_id,
                                type=NodeType.SERVICE,
                                label=imported_pkg,
                                file_path=rel_path,
                                metadata={"kind": "package"},
                            )
                        )

                    edges.append(
                        Edge(
                            source=src_pkg_id,
                            target=tgt_pkg_id,
                            type=EdgeType.DEPENDS_ON,
                            metadata={"inferred": True},
                        )
                    )

        # ---------------------------------------------------------------
        # Edge inference
        # ---------------------------------------------------------------

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

        # --- Edge inference: service configures env_var ---
        if service_node_ids and env_var_ids:
            for svc_id in service_node_ids:
                for env_id in env_var_ids:
                    edges.append(
                        Edge(
                            source=svc_id,
                            target=env_id,
                            type=EdgeType.CONFIGURES,
                            metadata={"inferred": True},
                        )
                    )

        # --- Full import parsing for universal pipeline (v0.6.0) ---
        imports: list[ImportInfo] = []
        all_import_paths = self._parse_imports(content)
        for import_path in all_import_paths:
            if self._is_internal_import(import_path):
                module_path = self._import_to_module_path(import_path)
                imports.append(ImportInfo(
                    module_path=module_path,
                    symbols=[],  # Go imports entire packages
                    style="absolute",
                ))

        # --- Interface implementation detection (v0.6.0) ---
        implementations: list[ImplementationInfo] = []
        interface_methods: dict[str, set[str]] = {}
        for match in _GO_INTERFACE_BODY_RE.finditer(content):
            iface_name = match.group(1)
            body = match.group(2)
            methods = set(_GO_INTERFACE_METHOD_RE.findall(body))
            if methods:
                interface_methods[iface_name] = methods

        for struct_name, methods in struct_methods.items():
            for iface_name, iface_meths in interface_methods.items():
                if iface_meths and iface_meths.issubset(methods):
                    implementations.append(ImplementationInfo(
                        child_class=struct_name,
                        parent_class=iface_name,
                        file_path=rel_path,
                    ))

        # --- Call detection (v0.9.0) ---
        calls: list[CallInfo] = []
        enclosing = _find_enclosing_func(content)
        rel_path_str = rel_path

        for match in _GO_FUNC_CALL_RE.finditer(content):
            receiver = match.group(1) or ""
            callee = match.group(2)

            # Skip stdlib packages
            if receiver.lower() in _GO_STDLIB_PACKAGES or receiver in _GO_STDLIB_PACKAGES:
                continue
            # Skip common Go builtins
            if callee in (
                "make", "append", "len", "cap", "copy", "delete",
                "close", "panic", "recover", "new", "print", "println",
            ):
                continue
            # Skip lowercase-only callees that look like local vars (Go exports are uppercase)
            # But allow if there's a receiver
            if not receiver and callee[0:1].islower():
                continue

            line_no = content[:match.start()].count('\n')
            caller = enclosing.get(line_no, "")
            style = "method" if receiver else "direct"

            calls.append(CallInfo(
                caller=caller,
                callee=callee,
                receiver=receiver,
                file_path=rel_path_str,
                style=style,
            ))

        # --- Interface info (v0.9.0) ---
        interfaces: list[InterfaceInfo] = []
        for match in _GO_INTERFACE_RE.finditer(content):
            iface_name = match.group(1)
            body_match = _GO_INTERFACE_BODY_RE.search(content[match.start():])
            iface_methods: list[str] = []
            if body_match:
                for method_match in _GO_INTERFACE_METHOD_RE.finditer(body_match.group(2)):
                    iface_methods.append(method_match.group(1))
            interfaces.append(InterfaceInfo(
                name=iface_name,
                methods=iface_methods,
                file_path=rel_path_str,
            ))

        # --- Method set entries (v0.9.0) ---
        method_sets: list[MethodSetEntry] = []
        for match in _GO_METHOD_RECEIVER_RE.finditer(content):
            struct_name = match.group(1)
            method_name = match.group(2)
            method_sets.append(MethodSetEntry(
                struct_name=struct_name,
                method_name=method_name,
                file_path=rel_path_str,
            ))

        return ScanResult(
            nodes=nodes,
            edges=edges,
            imports=imports,
            implementations=implementations,
            calls=calls,
            interfaces=interfaces,
            method_sets=method_sets,
        )

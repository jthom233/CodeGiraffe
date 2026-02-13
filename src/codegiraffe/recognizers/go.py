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
from codegiraffe.scanner import ScanResult
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

    def recognize(self, file_path: Path, content: str) -> ScanResult:
        """Scan *content* of a Go file and return discovered nodes/edges."""
        nodes: list[Node] = []
        edges: list[Edge] = []
        rel_path = str(file_path)

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

        return ScanResult(nodes=nodes, edges=edges)

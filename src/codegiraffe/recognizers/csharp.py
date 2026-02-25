"""C# pattern recognizer for Code Giraffe.

Detects architectural patterns in .cs files including:
    - ASP.NET route attributes             -> endpoint nodes
    - Entity Framework DbSet/Table attrs   -> database_table nodes
    - Environment.GetEnvironmentVariable   -> env_var nodes
    - HttpClient calls                     -> external_api nodes
    - SignalR hubs (: Hub)                 -> service nodes (kind=signalr_hub)
    - MediatR handlers                     -> worker nodes
    - DI registrations                     -> service nodes
"""

from __future__ import annotations

import re
from pathlib import Path

from codegiraffe.graph import Edge, Node
from codegiraffe.scanner import ScanResult, ImportInfo, ImplementationInfo
from codegiraffe.schema import EdgeType, NodeType

# ---------------------------------------------------------------------------
# Compiled regex patterns
# ---------------------------------------------------------------------------

# ASP.NET route attributes: [HttpGet("/path")], [HttpPost("/path")], etc.
# Group 1: verb (Get/Post/Put/Delete/Patch), Group 2: route path
_CS_HTTP_ATTR_RE = re.compile(
    r"""\[Http(Get|Post|Put|Delete|Patch)\s*\(\s*"([^"]*)"\s*\)""",
)

# ASP.NET verb-only attributes with no route argument: [HttpGet], [HttpPost], etc.
# Group 1: verb (Get/Post/Put/Delete/Patch)
_CS_HTTP_VERB_ONLY_RE = re.compile(
    r"""\[Http(Get|Post|Put|Delete|Patch)\s*\]""",
)

# [Route("path")] attribute
_CS_ROUTE_ATTR_RE = re.compile(
    r"""\[Route\s*\(\s*"([^"]*)"\s*\)""",
)

# Entity Framework [Table("name")] attribute
_CS_TABLE_ATTR_RE = re.compile(
    r"""\[Table\s*\(\s*"(\w+)"\s*\)""",
)

# Entity Framework DbSet<TypeName> property
_CS_DBSET_RE = re.compile(
    r"""DbSet<(\w+)>""",
)

# Environment.GetEnvironmentVariable("KEY")
_CS_ENV_RE = re.compile(
    r"""Environment\.GetEnvironmentVariable\s*\(\s*"(\w+)"\s*\)""",
)

# HttpClient calls with URL strings
_CS_HTTPCLIENT_RE = re.compile(
    r"""(?:HttpClient|_httpClient|client)\s*\.(?:GetAsync|PostAsync|PutAsync|DeleteAsync|GetStringAsync|SendAsync)\s*\(\s*"(https?://[^"]+)"\s*\)""",
)

# SignalR hubs: classes inheriting from Hub or Hub<T>
_CS_SIGNALR_HUB_RE = re.compile(
    r"""class\s+(\w+)\s*:\s*Hub(?:<\w+>)?""",
)

# MediatR handlers: IRequestHandler<T> or INotificationHandler<T>
_CS_MEDIATR_RE = re.compile(
    r"""class\s+(\w+)\s*.*?:\s*.*?I(?:Request|Notification)Handler""",
)

# DI registrations: services.AddScoped<T>(), services.AddTransient<T>(), services.AddSingleton<T>()
_CS_DI_RE = re.compile(
    r"""services\.Add(?:Scoped|Transient|Singleton)<(\w+)>""",
)

_CS_USING_STMT_RE = re.compile(r'using\s+([\w.]+)\s*;', re.MULTILINE)
_CS_NAMESPACE_DECL_RE = re.compile(r'namespace\s+([\w.]+)', re.MULTILINE)
_CS_CLASS_INHERITANCE_RE = re.compile(r'class\s+(\w+)(?:<[^>]*>)?\s*:\s*([\w\s,.<>]+?)(?:\s*\{|\s*where)')

# ---------------------------------------------------------------------------
# Recognizer
# ---------------------------------------------------------------------------


class CSharpRecognizer:
    """Recognizes common C# architectural patterns via regex.

    Detected patterns:
        - ASP.NET route attributes             -> ``endpoint`` nodes
        - Entity Framework DbSet/Table attrs   -> ``database_table`` nodes
        - ``Environment.GetEnvironmentVariable`` -> ``env_var`` nodes
        - ``HttpClient`` calls                 -> ``external_api`` nodes
        - SignalR hubs (``Hub``)               -> ``service`` nodes (kind=signalr_hub)
        - MediatR handlers                     -> ``worker`` nodes
        - DI registrations                     -> ``service`` nodes
    """

    def __init__(self) -> None:
        self._project_namespaces: set[str] = set()

    def set_project_root(self, project_root: str) -> None:
        self._project_namespaces = set()
        root = Path(project_root)
        for cs_file in root.rglob("*.cs"):
            try:
                text = cs_file.read_text(encoding="utf-8", errors="replace")[:1000]
                for match in _CS_NAMESPACE_DECL_RE.finditer(text):
                    parts = match.group(1).split(".")
                    if parts:
                        self._project_namespaces.add(parts[0])
            except OSError:
                continue

    def recognize(self, file_path: Path, content: str) -> ScanResult:
        """Scan *content* of a C# file and return discovered nodes/edges."""
        nodes: list[Node] = []
        edges: list[Edge] = []
        rel_path = file_path.as_posix()

        endpoint_ids: list[str] = []
        table_ids: list[str] = []
        captured_class_names: set[str] = set()

        # --- Endpoints (ASP.NET route composition) ---
        # Two-pass approach: first extract class-level route prefix, then compose
        # method-level routes against it.
        seen_routes: set[str] = set()
        lines = content.split('\n')

        # Pass 1: Find the class-level [Route("...")] prefix.
        # A class-level [Route] appears on a line before a `class` declaration
        # (within a small look-ahead window). Skip templates that contain
        # [controller] tokens since those are resolved at runtime by ASP.NET.
        class_route_prefix = ""
        class_route_lines: set[int] = set()
        for i, line in enumerate(lines):
            route_match = _CS_ROUTE_ATTR_RE.search(line)
            if route_match:
                route_path = route_match.group(1)
                if "[controller]" in route_path.lower():
                    class_route_lines.add(i)
                    continue
                # Look ahead up to 5 lines for a class declaration
                for j in range(i + 1, min(i + 6, len(lines))):
                    if re.search(r'\bclass\b', lines[j]):
                        class_route_prefix = route_path.rstrip('/')
                        class_route_lines.add(i)
                        break

        # Pass 2: Find method-level Http verb attributes and compose full routes.
        for i, line in enumerate(lines):
            stripped = line.strip()

            # Match [HttpVerb("route")] — verb + explicit route string
            http_match = _CS_HTTP_ATTR_RE.search(stripped)
            if http_match:
                verb = http_match.group(1).upper()
                method_route = http_match.group(2)
                if class_route_prefix and not method_route.startswith('/'):
                    full_route = f"{class_route_prefix}/{method_route}"
                else:
                    full_route = method_route
                if full_route not in seen_routes:
                    seen_routes.add(full_route)
                    node_id = f"endpoint:/{full_route}" if not full_route.startswith('/') else f"endpoint:{full_route}"
                    nodes.append(
                        Node(
                            id=node_id,
                            type=NodeType.ENDPOINT,
                            label=full_route,
                            file_path=rel_path,
                            metadata={"route": full_route, "framework": "aspnet", "http_method": verb},
                        )
                    )
                    endpoint_ids.append(node_id)
                continue

            # Match [HttpVerb] with no route argument — route is just the class prefix
            verb_only_match = _CS_HTTP_VERB_ONLY_RE.search(stripped)
            if verb_only_match:
                verb = verb_only_match.group(1).upper()
                full_route = class_route_prefix if class_route_prefix else ""
                if full_route and full_route not in seen_routes:
                    seen_routes.add(full_route)
                    node_id = f"endpoint:/{full_route}" if not full_route.startswith('/') else f"endpoint:{full_route}"
                    nodes.append(
                        Node(
                            id=node_id,
                            type=NodeType.ENDPOINT,
                            label=full_route,
                            file_path=rel_path,
                            metadata={"route": full_route, "framework": "aspnet", "http_method": verb},
                        )
                    )
                    endpoint_ids.append(node_id)
                continue

            # Match non-class-level [Route("...")] as standalone endpoints
            route_match = _CS_ROUTE_ATTR_RE.search(stripped)
            if route_match and i not in class_route_lines:
                route_path = route_match.group(1)
                if "[controller]" not in route_path.lower() and route_path not in seen_routes:
                    seen_routes.add(route_path)
                    node_id = f"endpoint:{route_path}"
                    nodes.append(
                        Node(
                            id=node_id,
                            type=NodeType.ENDPOINT,
                            label=route_path,
                            file_path=rel_path,
                            metadata={"route": route_path, "framework": "aspnet", "http_method": "ANY"},
                        )
                    )
                    endpoint_ids.append(node_id)

        # --- Database tables (Entity Framework [Table] attribute) ---
        seen_tables: set[str] = set()
        for match in _CS_TABLE_ATTR_RE.finditer(content):
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
                        metadata={"table": table_name, "orm": "entity_framework"},
                    )
                )
                table_ids.append(node_id)

        # --- Database tables (Entity Framework DbSet<T>) ---
        for match in _CS_DBSET_RE.finditer(content):
            entity_name = match.group(1)
            if entity_name not in seen_tables:
                seen_tables.add(entity_name)
                node_id = f"table:{entity_name}"
                nodes.append(
                    Node(
                        id=node_id,
                        type=NodeType.DATABASE_TABLE,
                        label=entity_name,
                        file_path=rel_path,
                        metadata={"entity": entity_name, "orm": "entity_framework"},
                    )
                )
                table_ids.append(node_id)

        # --- Environment variables ---
        seen_env_vars: set[str] = set()
        for match in _CS_ENV_RE.finditer(content):
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

        # --- External API calls (HttpClient) ---
        seen_urls: set[str] = set()
        for match in _CS_HTTPCLIENT_RE.finditer(content):
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

        # --- SignalR hubs ---
        for match in _CS_SIGNALR_HUB_RE.finditer(content):
            hub_name = match.group(1)
            captured_class_names.add(hub_name)
            node_id = f"service:{hub_name}"
            nodes.append(
                Node(
                    id=node_id,
                    type=NodeType.SERVICE,
                    label=hub_name,
                    file_path=rel_path,
                    metadata={"class_name": hub_name, "kind": "signalr_hub"},
                )
            )

        # --- MediatR handlers ---
        for match in _CS_MEDIATR_RE.finditer(content):
            handler_name = match.group(1)
            if handler_name not in captured_class_names:
                captured_class_names.add(handler_name)
                node_id = f"worker:{handler_name}"
                nodes.append(
                    Node(
                        id=node_id,
                        type=NodeType.WORKER,
                        label=handler_name,
                        file_path=rel_path,
                        metadata={"handler": handler_name, "framework": "mediatr"},
                    )
                )

        # --- DI registrations ---
        for match in _CS_DI_RE.finditer(content):
            service_name = match.group(1)
            if service_name not in captured_class_names:
                captured_class_names.add(service_name)
                node_id = f"service:{service_name}"
                nodes.append(
                    Node(
                        id=node_id,
                        type=NodeType.SERVICE,
                        label=service_name,
                        file_path=rel_path,
                        metadata={"class_name": service_name, "registration": "di"},
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

        imports: list[ImportInfo] = []
        _external_ns = {"System", "Microsoft", "Newtonsoft", "NUnit", "Xunit"}
        for match in _CS_USING_STMT_RE.finditer(content):
            using_path = match.group(1)
            root_ns = using_path.split(".")[0]
            if root_ns in self._project_namespaces and root_ns not in _external_ns:
                imports.append(ImportInfo(module_path=using_path, symbols=[using_path.split(".")[-1]], style="absolute"))

        implementations: list[ImplementationInfo] = []
        for match in _CS_CLASS_INHERITANCE_RE.finditer(content):
            child = match.group(1)
            for base in [b.strip().split("<")[0].strip() for b in match.group(2).split(",") if b.strip()]:
                if base and base[0].isupper():
                    implementations.append(ImplementationInfo(child_class=child, parent_class=base, file_path=file_path.as_posix()))

        return ScanResult(nodes=nodes, edges=edges, imports=imports, implementations=implementations)

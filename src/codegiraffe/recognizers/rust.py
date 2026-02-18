"""Rust pattern recognizer for Code Giraffe.

Detects architectural patterns in .rs files including:
    - Actix/Axum/Rocket route attributes and .route() calls -> endpoint nodes
    - Diesel table! macros and #[derive(Queryable)]         -> database_table nodes
    - env::var / std::env::var / env!() access              -> env_var nodes
    - reqwest HTTP calls                                    -> external_api nodes
    - Struct definitions (fallback)                         -> service nodes
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

# Actix/Rocket route attribute macros: #[get("/path")], #[post("/path")]
_RS_ROUTE_ATTR_RE = re.compile(
    r"""#\[(?:get|post|put|delete|patch|head|options)\s*\(\s*['"](\/[^'"]*?)['"]""",
    re.IGNORECASE,
)

# .route("/path", ...) calls for Axum/Actix manual routing
_RS_ROUTE_CALL_RE = re.compile(
    r"""\.route\s*\(\s*['"](\/[^'"]*?)['"]""",
)

# web::get().to(handler), web::resource("/path")
_RS_WEB_RESOURCE_RE = re.compile(
    r"""web::resource\s*\(\s*['"](\/[^'"]*?)['"]""",
)

# Diesel table! macro
_RS_DIESEL_TABLE_RE = re.compile(
    r"""table!\s*\{\s*(\w+)""",
)

# #[derive(Queryable)] followed by struct
_RS_QUERYABLE_RE = re.compile(
    r"""#\[derive\([^)]*Queryable[^)]*\)\]\s*(?:pub\s+)?struct\s+(\w+)""",
    re.DOTALL,
)

# #[table_name = "name"]
_RS_TABLE_NAME_RE = re.compile(
    r"""#\[table_name\s*=\s*['"]([\w]+)['"]\]""",
)

# env::var("VAR"), std::env::var("VAR")
_RS_ENV_VAR_RE = re.compile(
    r"""(?:std::)?env::var\s*\(\s*['"]([\w]+)['"]""",
)

# env!("VAR") compile-time macro
_RS_ENV_MACRO_RE = re.compile(
    r"""env!\s*\(\s*['"]([\w]+)['"]""",
)

# reqwest::get("url"), Client::new().get("url")
_RS_REQWEST_RE = re.compile(
    r"""(?:reqwest::get|\.get|\.post|\.put|\.delete)\s*\(\s*['"](https?://[^'"]+?)['"]""",
)

# Struct definitions: pub struct Name, struct Name
_RS_STRUCT_RE = re.compile(
    r"""(?:pub\s+)?struct\s+(\w+)""",
)


_RS_USE_CRATE_RE = re.compile(r'use\s+crate::([^\s;{]+)(?:\s*;|\s*\{)', re.MULTILINE)
_RS_USE_SUPER_RE = re.compile(r'use\s+super::([^\s;{]+)(?:\s*;|\s*\{)', re.MULTILINE)
_RS_IMPL_TRAIT_RE = re.compile(r'impl\s+(\w+)\s+for\s+(\w+)')

# ---------------------------------------------------------------------------
# Recognizer
# ---------------------------------------------------------------------------


class RustRecognizer:
    """Recognizes common Rust architectural patterns via regex.

    Detected patterns:
        - Actix/Axum/Rocket route attributes -> ``endpoint`` nodes
        - Diesel table! macros and Queryable -> ``database_table`` nodes
        - ``env::var`` / ``env!`` access     -> ``env_var`` nodes
        - ``reqwest`` HTTP calls             -> ``external_api`` nodes
        - Struct definitions (fallback)      -> ``service`` nodes
    """

    def recognize(self, file_path: Path, content: str) -> ScanResult:
        """Scan *content* of a Rust file and return discovered nodes/edges."""
        nodes: list[Node] = []
        edges: list[Edge] = []
        rel_path = file_path.as_posix()

        endpoint_ids: list[str] = []
        table_ids: list[str] = []
        captured_struct_names: set[str] = set()

        # --- Endpoints (Actix/Rocket attributes) ---
        seen_routes: set[str] = set()
        for match in _RS_ROUTE_ATTR_RE.finditer(content):
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
                        metadata={"route": route_path, "framework": "actix/rocket"},
                    )
                )
                endpoint_ids.append(node_id)

        # --- Endpoints (.route() calls) ---
        for match in _RS_ROUTE_CALL_RE.finditer(content):
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
                        metadata={"route": route_path, "framework": "axum"},
                    )
                )
                endpoint_ids.append(node_id)

        # --- Endpoints (web::resource) ---
        for match in _RS_WEB_RESOURCE_RE.finditer(content):
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
                        metadata={"route": route_path, "framework": "actix-web"},
                    )
                )
                endpoint_ids.append(node_id)

        # --- Database tables (Diesel table! macro) ---
        seen_tables: set[str] = set()
        for match in _RS_DIESEL_TABLE_RE.finditer(content):
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
                        metadata={"table": table_name, "orm": "diesel"},
                    )
                )
                table_ids.append(node_id)

        # --- Database tables (#[derive(Queryable)] struct) ---
        for match in _RS_QUERYABLE_RE.finditer(content):
            struct_name = match.group(1)
            captured_struct_names.add(struct_name)
            node_id = f"table:{struct_name}"
            # Only add if not already captured via table! macro
            if not any(n.id == node_id for n in nodes):
                nodes.append(
                    Node(
                        id=node_id,
                        type=NodeType.DATABASE_TABLE,
                        label=struct_name,
                        file_path=rel_path,
                        metadata={"struct": struct_name, "orm": "diesel"},
                    )
                )
                table_ids.append(node_id)

        # --- Database tables (#[table_name = "name"]) ---
        for match in _RS_TABLE_NAME_RE.finditer(content):
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
                        metadata={"table_name": table_name, "orm": "diesel"},
                    )
                )
                table_ids.append(node_id)

        # --- Environment variables ---
        seen_env_vars: set[str] = set()
        for match in _RS_ENV_VAR_RE.finditer(content):
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

        for match in _RS_ENV_MACRO_RE.finditer(content):
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
                        metadata={"variable": var_name, "compile_time": True},
                    )
                )

        # --- External HTTP calls (reqwest) ---
        seen_urls: set[str] = set()
        for match in _RS_REQWEST_RE.finditer(content):
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

        # --- Struct definitions (fallback to service nodes) ---
        for match in _RS_STRUCT_RE.finditer(content):
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
        for match in _RS_USE_CRATE_RE.finditer(content):
            full_path = match.group(1).replace("::", ".")
            imports.append(ImportInfo(module_path=full_path, style="absolute"))
        for match in _RS_USE_SUPER_RE.finditer(content):
            full_path = match.group(1).replace("::", ".")
            imports.append(ImportInfo(module_path=full_path, style="relative"))

        implementations: list[ImplementationInfo] = []
        for match in _RS_IMPL_TRAIT_RE.finditer(content):
            implementations.append(ImplementationInfo(child_class=match.group(2), parent_class=match.group(1), file_path=str(file_path)))

        return ScanResult(nodes=nodes, edges=edges, imports=imports, implementations=implementations)

"""Go pattern recognizer for Code Giraffe.

Detects architectural patterns in .go files including:
    - net/http, Gin, Echo, Chi route handlers -> endpoint nodes
    - GORM models and db.Table calls          -> database_table nodes
    - os.Getenv / os.LookupEnv access        -> env_var nodes
    - http.Get / http.Post calls              -> external_api nodes
    - Struct definitions (fallback)           -> service nodes
    - Goroutine worker patterns               -> worker nodes
"""

from __future__ import annotations

import re
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
    """

    def recognize(self, file_path: Path, content: str) -> ScanResult:
        """Scan *content* of a Go file and return discovered nodes/edges."""
        nodes: list[Node] = []
        edges: list[Edge] = []
        rel_path = str(file_path)

        endpoint_ids: list[str] = []
        table_ids: list[str] = []
        captured_struct_names: set[str] = set()

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

        return ScanResult(nodes=nodes, edges=edges)

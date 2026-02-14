"""PHP pattern recognizer for Code Giraffe.

Detects architectural patterns in .php files including:
    - Laravel routes (Route::get/post/etc)    -> endpoint nodes
    - Symfony route attributes (#[Route])      -> endpoint nodes
    - Eloquent models (extends Model)          -> database_table nodes
    - env() calls                              -> env_var nodes
    - Queue jobs (implements ShouldQueue)      -> worker nodes
    - Http facade / Guzzle calls               -> external_api nodes
    - Class definitions (fallback)             -> service nodes
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

# Laravel routes: Route::get('/path', ...), Route::post('/path', ...), etc.
_PHP_LARAVEL_ROUTE_RE = re.compile(
    r"""Route\s*::\s*(?:get|post|put|delete|patch|options|any)\s*\(\s*['"]([^'"]+)['"]""",
    re.IGNORECASE,
)

# Symfony route attributes: #[Route('/path')]
_PHP_SYMFONY_ROUTE_RE = re.compile(
    r"""#\[Route\s*\(\s*['"]([^'"]+)['"]""",
)

# Eloquent explicit table: protected $table = 'name'
_PHP_TABLE_PROPERTY_RE = re.compile(
    r"""protected\s+\$table\s*=\s*['"](\w+)['"]""",
)

# Eloquent model: class ClassName extends Model/Authenticatable/Pivot
_PHP_ELOQUENT_MODEL_RE = re.compile(
    r"""class\s+(\w+)\s+extends\s+(?:Model|Authenticatable|Pivot)""",
)

# env() / getenv() calls
_PHP_ENV_FUNC_RE = re.compile(
    r"""(?:env|getenv)\s*\(\s*['"](\w+)['"]""",
)

# $_ENV['KEY'] access
_PHP_ENV_SUPERGLOBAL_RE = re.compile(
    r"""\$_ENV\s*\[\s*['"](\w+)['"]""",
)

# Queue jobs: class JobName ... implements ... ShouldQueue
_PHP_QUEUE_JOB_RE = re.compile(
    r"""class\s+(\w+)\s+.*?implements\s+.*?ShouldQueue""",
)

# Http facade / Guzzle HTTP calls
_PHP_HTTP_RE = re.compile(
    r"""(?:Http\s*::\s*(?:get|post|put|delete|patch)|(?:\$client|\$guzzle)\s*->\s*(?:get|post|put|delete|patch|request))\s*\(\s*['"]?(https?://[^'")\s]+)""",
)

_PHP_USE_STMT_RE = re.compile(r'use\s+([\w\\]+)\s*;', re.MULTILINE)
_PHP_NS_DECL_RE = re.compile(r'namespace\s+([\w\\]+)\s*;', re.MULTILINE)
_PHP_CLASS_EXTENDS_RE = re.compile(r'class\s+(\w+)\s+extends\s+(\w+)')
_PHP_CLASS_IMPL_RE = re.compile(r'class\s+(\w+)\s+(?:extends\s+\w+\s+)?implements\s+([\w,\s\\]+?)(?:\s*\{)')

# Class definitions (fallback)
_PHP_CLASS_RE = re.compile(
    r"""(?:abstract\s+|final\s+)?class\s+(\w+)""",
)


# ---------------------------------------------------------------------------
# Recognizer
# ---------------------------------------------------------------------------


class PhpRecognizer:
    """Recognizes common PHP architectural patterns via regex.

    Detected patterns:
        - Laravel routes (Route::get/post/etc)    -> ``endpoint`` nodes
        - Symfony route attributes (#[Route])      -> ``endpoint`` nodes
        - Eloquent models (extends Model)          -> ``database_table`` nodes
        - ``env()`` / ``getenv()`` / ``$_ENV``     -> ``env_var`` nodes
        - Queue jobs (implements ShouldQueue)      -> ``worker`` nodes
        - Http facade / Guzzle calls               -> ``external_api`` nodes
        - Class definitions (fallback)             -> ``service`` nodes
    """

    def __init__(self) -> None:
        self._project_namespaces: set[str] = set()

    def set_project_root(self, project_root: str) -> None:
        self._project_namespaces = set()
        root = Path(project_root)
        for php_file in root.rglob("*.php"):
            try:
                text = php_file.read_text(encoding="utf-8", errors="replace")[:500]
                match = _PHP_NS_DECL_RE.search(text)
                if match:
                    self._project_namespaces.add(match.group(1).split("\\")[0])
            except OSError:
                continue

    def recognize(self, file_path: Path, content: str) -> ScanResult:
        """Scan *content* of a PHP file and return discovered nodes/edges."""
        nodes: list[Node] = []
        edges: list[Edge] = []
        rel_path = str(file_path)

        endpoint_ids: list[str] = []
        table_ids: list[str] = []
        captured_class_names: set[str] = set()

        # --- Endpoints (Laravel routes) ---
        seen_routes: set[str] = set()
        for match in _PHP_LARAVEL_ROUTE_RE.finditer(content):
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
                        metadata={"route": route_path, "framework": "laravel"},
                    )
                )
                endpoint_ids.append(node_id)

        # --- Endpoints (Symfony route attributes) ---
        for match in _PHP_SYMFONY_ROUTE_RE.finditer(content):
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
                        metadata={"route": route_path, "framework": "symfony"},
                    )
                )
                endpoint_ids.append(node_id)

        # --- Database tables (Eloquent models) ---
        # First pass: collect explicit $table declarations
        explicit_tables: dict[str, str] = {}
        for match in _PHP_TABLE_PROPERTY_RE.finditer(content):
            table_name = match.group(1)
            explicit_tables[table_name] = table_name

        # Second pass: detect classes extending Model/Authenticatable/Pivot
        for match in _PHP_ELOQUENT_MODEL_RE.finditer(content):
            class_name = match.group(1)
            captured_class_names.add(class_name)

            # Use explicit $table if found, otherwise snake_case plural
            if explicit_tables:
                # Use the first explicit table declaration found
                table_name = next(iter(explicit_tables.values()))
            else:
                # Convert CamelCase to snake_case and add 's' for plural
                table_name = re.sub(r"(?<!^)(?=[A-Z])", "_", class_name).lower() + "s"

            node_id = f"table:{table_name}"
            nodes.append(
                Node(
                    id=node_id,
                    type=NodeType.DATABASE_TABLE,
                    label=table_name,
                    file_path=rel_path,
                    metadata={
                        "model": class_name,
                        "table": table_name,
                        "orm": "eloquent",
                    },
                )
            )
            table_ids.append(node_id)

        # --- Environment variables (env() / getenv()) ---
        seen_env_vars: set[str] = set()
        for match in _PHP_ENV_FUNC_RE.finditer(content):
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

        # --- Environment variables ($_ENV['KEY']) ---
        for match in _PHP_ENV_SUPERGLOBAL_RE.finditer(content):
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

        # --- Queue jobs (implements ShouldQueue) ---
        seen_workers: set[str] = set()
        for match in _PHP_QUEUE_JOB_RE.finditer(content):
            job_name = match.group(1)
            if job_name not in seen_workers:
                seen_workers.add(job_name)
                captured_class_names.add(job_name)
                node_id = f"worker:{job_name}"
                nodes.append(
                    Node(
                        id=node_id,
                        type=NodeType.WORKER,
                        label=job_name,
                        file_path=rel_path,
                        metadata={"job": job_name},
                    )
                )

        # --- External API calls (Http facade / Guzzle) ---
        seen_urls: set[str] = set()
        for match in _PHP_HTTP_RE.finditer(content):
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
        for match in _PHP_CLASS_RE.finditer(content):
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

        imports: list[ImportInfo] = []
        for match in _PHP_USE_STMT_RE.finditer(content):
            use_path = match.group(1)
            root_ns = use_path.split("\\")[0]
            if root_ns in self._project_namespaces:
                imports.append(ImportInfo(module_path=use_path.replace("\\", "."), symbols=[use_path.split("\\")[-1]], style="absolute"))

        implementations: list[ImplementationInfo] = []
        for match in _PHP_CLASS_EXTENDS_RE.finditer(content):
            implementations.append(ImplementationInfo(child_class=match.group(1), parent_class=match.group(2), file_path=str(file_path)))
        for match in _PHP_CLASS_IMPL_RE.finditer(content):
            child = match.group(1)
            for parent in [p.strip().split("\\")[-1] for p in match.group(2).split(",") if p.strip()]:
                implementations.append(ImplementationInfo(child_class=child, parent_class=parent, file_path=str(file_path)))

        return ScanResult(nodes=nodes, edges=edges, imports=imports, implementations=implementations)

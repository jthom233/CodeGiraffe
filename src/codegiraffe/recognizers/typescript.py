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
from codegiraffe.scanner import ScanResult
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
    r"""model\s+(\w+)\s*\{""",
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

# React/Vue component export
_TS_COMPONENT_RE = re.compile(
    r"""export\s+(?:default\s+)?(?:function|const|class)\s+(\w+)""",
)

# Class definitions
_TS_CLASS_RE = re.compile(
    r"""(?:export\s+)?class\s+(\w+)""",
)

# Queue (Bull/BullMQ)
_TS_QUEUE_RE = re.compile(
    r"""new\s+(?:Queue|Worker)\s*\(\s*['"]([\w-]+?)['"]""",
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
        nodes: list[Node] = []
        edges: list[Edge] = []
        rel_path = str(file_path)

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

        return ScanResult(nodes=nodes, edges=edges)

"""Java pattern recognizer for Code Giraffe.

Detects architectural patterns in .java files including:
    - Spring Boot @XxxMapping annotations       -> endpoint nodes
    - JPA/Hibernate @Entity and @Table           -> database_table nodes
    - System.getenv and @Value access            -> env_var nodes
    - HTTP client patterns (URL, RestTemplate)   -> external_api nodes
    - @RabbitListener, @KafkaListener, @JmsListener -> worker nodes
    - @EventListener, ApplicationEventPublisher  -> event nodes
    - Class definitions (fallback)               -> service nodes
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

# Spring Boot mappings: @GetMapping("/path"), @PostMapping("/path"), etc.
_JAVA_MAPPING_RE = re.compile(
    r"""@(?:Get|Post|Put|Delete|Patch)Mapping\s*\(\s*(?:value\s*=\s*)?['"](\/[^'"]*?)['"]""",
)

# @RequestMapping("/path")
_JAVA_REQUEST_MAPPING_RE = re.compile(
    r"""@RequestMapping\s*\(\s*(?:value\s*=\s*)?['"](\/[^'"]*?)['"]""",
)

# JPA @Entity — marks next class as a DB entity
_JAVA_ENTITY_RE = re.compile(
    r"""@Entity\s*(?:\(.*?\))?\s*(?:@\w+\s*(?:\(.*?\))?\s*)*(?:public\s+)?class\s+(\w+)""",
    re.DOTALL,
)

# @Table(name = "name")
_JAVA_TABLE_RE = re.compile(
    r"""@Table\s*\(\s*(?:name\s*=\s*)?['"]([\w]+)['"]""",
)

# System.getenv("VAR")
_JAVA_GETENV_RE = re.compile(
    r"""System\s*\.\s*getenv\s*\(\s*['"]([\w]+)['"]""",
)

# @Value("${var}")
_JAVA_VALUE_RE = re.compile(
    r"""@Value\s*\(\s*['"]\$\{([\w.]+)\}['"]""",
)

# new URL("url")
_JAVA_URL_RE = re.compile(
    r"""new\s+URL\s*\(\s*['"](https?://[^'"]+?)['"]""",
)

# RestTemplate / WebClient method calls with URL
_JAVA_REST_TEMPLATE_RE = re.compile(
    r"""(?:restTemplate|webClient)\s*\.\s*(?:getForObject|getForEntity|postForObject|postForEntity|exchange|get|post)\s*\(\s*['"](https?://[^'"]+?)['"]""",
    re.IGNORECASE,
)

# Message queue listeners: @RabbitListener, @KafkaListener, @JmsListener
_JAVA_MQ_LISTENER_RE = re.compile(
    r"""@(?:Rabbit|Kafka|Jms)Listener\s*\(\s*(?:queues|topics)\s*=\s*['"]([\w.-]+)['"]""",
)

# Event handling: @EventListener
_JAVA_EVENT_LISTENER_RE = re.compile(
    r"""@EventListener""",
)

# ApplicationEventPublisher
_JAVA_EVENT_PUBLISHER_RE = re.compile(
    r"""ApplicationEventPublisher""",
)

# Class definitions: public class Name, class Name
_JAVA_CLASS_RE = re.compile(
    r"""(?:public\s+)?(?:abstract\s+)?class\s+(\w+)""",
)


# ---------------------------------------------------------------------------
# Recognizer
# ---------------------------------------------------------------------------


class JavaRecognizer:
    """Recognizes common Java architectural patterns via regex.

    Detected patterns:
        - Spring Boot @XxxMapping annotations       -> ``endpoint`` nodes
        - JPA/Hibernate @Entity and @Table           -> ``database_table`` nodes
        - ``System.getenv`` and ``@Value`` access    -> ``env_var`` nodes
        - HTTP client patterns                       -> ``external_api`` nodes
        - @RabbitListener, @KafkaListener            -> ``worker`` nodes
        - @EventListener                             -> ``event`` nodes
        - Class definitions (fallback)               -> ``service`` nodes
    """

    def recognize(self, file_path: Path, content: str) -> ScanResult:
        """Scan *content* of a Java file and return discovered nodes/edges."""
        nodes: list[Node] = []
        edges: list[Edge] = []
        rel_path = str(file_path)

        endpoint_ids: list[str] = []
        table_ids: list[str] = []
        captured_class_names: set[str] = set()

        # --- Endpoints (Spring Boot @XxxMapping) ---
        seen_routes: set[str] = set()
        for match in _JAVA_MAPPING_RE.finditer(content):
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
                        metadata={"route": route_path, "framework": "spring"},
                    )
                )
                endpoint_ids.append(node_id)

        # --- Endpoints (@RequestMapping) ---
        for match in _JAVA_REQUEST_MAPPING_RE.finditer(content):
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
                        metadata={"route": route_path, "framework": "spring"},
                    )
                )
                endpoint_ids.append(node_id)

        # --- Database tables (@Table) ---
        seen_tables: set[str] = set()
        for match in _JAVA_TABLE_RE.finditer(content):
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
                        metadata={"table": table_name, "orm": "jpa"},
                    )
                )
                table_ids.append(node_id)

        # --- Database tables (@Entity class) ---
        for match in _JAVA_ENTITY_RE.finditer(content):
            class_name = match.group(1)
            captured_class_names.add(class_name)
            # Only add as table if not already captured via @Table
            node_id = f"table:{class_name}"
            if not any(n.id == node_id for n in nodes):
                nodes.append(
                    Node(
                        id=node_id,
                        type=NodeType.DATABASE_TABLE,
                        label=class_name,
                        file_path=rel_path,
                        metadata={"entity": class_name, "orm": "jpa"},
                    )
                )
                table_ids.append(node_id)

        # --- Environment variables (System.getenv) ---
        seen_env_vars: set[str] = set()
        for match in _JAVA_GETENV_RE.finditer(content):
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

        # --- Environment variables (@Value) ---
        for match in _JAVA_VALUE_RE.finditer(content):
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
                        metadata={"variable": var_name, "spring_value": True},
                    )
                )

        # --- External API calls (new URL) ---
        seen_urls: set[str] = set()
        for match in _JAVA_URL_RE.finditer(content):
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

        # --- External API calls (RestTemplate/WebClient) ---
        for match in _JAVA_REST_TEMPLATE_RE.finditer(content):
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

        # --- Workers (message queue listeners) ---
        seen_queues: set[str] = set()
        for match in _JAVA_MQ_LISTENER_RE.finditer(content):
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

        # --- Events (@EventListener, ApplicationEventPublisher) ---
        if _JAVA_EVENT_LISTENER_RE.search(content) or _JAVA_EVENT_PUBLISHER_RE.search(content):
            node_id = f"event:{file_path.stem}"
            nodes.append(
                Node(
                    id=node_id,
                    type=NodeType.EVENT,
                    label=f"{file_path.stem} events",
                    file_path=rel_path,
                    metadata={"source": file_path.stem},
                )
            )

        # --- Class definitions (fallback to service nodes) ---
        for match in _JAVA_CLASS_RE.finditer(content):
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

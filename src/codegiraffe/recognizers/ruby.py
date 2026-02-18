"""Ruby pattern recognizer for Code Giraffe.

Detects architectural patterns in .rb files including:
    - Rails routes (get/post/put/delete)       -> endpoint nodes
    - ActiveRecord models (< ApplicationRecord) -> database_table nodes
    - Sidekiq workers (include Sidekiq::Worker) -> worker nodes
    - ENV[] / ENV.fetch access                  -> env_var nodes
    - Net::HTTP / Faraday / HTTParty calls      -> external_api nodes
    - Class definitions (fallback)              -> service nodes
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

# Rails explicit routes: get '/path', post '/path', etc.
_RB_ROUTE_RE = re.compile(
    r"""(?:get|post|put|delete|patch|match)\s+['"](\/[^'"]*?)['"]""",
)

# Rails resource routes: resources :users, resource :session
_RB_RESOURCES_RE = re.compile(
    r"""resources?\s+:(\w+)""",
)

# ActiveRecord model: class User < ApplicationRecord or class User < ActiveRecord::Base
_RB_ACTIVERECORD_RE = re.compile(
    r"""class\s+(\w+)\s*<\s*(?:ApplicationRecord|ActiveRecord::Base)""",
)

# Sidekiq worker: class MyWorker ... include Sidekiq::Worker or Sidekiq::Job
# Uses a negative lookahead to avoid crossing class boundaries.
_RB_SIDEKIQ_RE = re.compile(
    r"""class\s+(\w+)(?:(?!\bclass\b)[\s\S])*?include\s+Sidekiq::(?:Worker|Job)""",
)

# ENV access: ENV['KEY'], ENV["KEY"], ENV.fetch('KEY'), ENV.fetch("KEY")
_RB_ENV_RE = re.compile(
    r"""ENV\s*(?:\[|\.fetch\s*\(\s*)['"]([\w]+)['"]""",
)

# External HTTP calls: Net::HTTP, Faraday, HTTParty, RestClient
_RB_HTTP_RE = re.compile(
    r"""(?:Net::HTTP|Faraday|HTTParty|RestClient)\s*\.(?:get|post|put|delete|patch|new)\s*\(\s*(?:URI\s*\(\s*)?['"]?(https?://[^'")\s]+)""",
)

_RB_REQUIRE_RELATIVE_RE = re.compile(r"require_relative\s+['\"]([^'\"]+)['\"]")
_RB_CLASS_INHERIT_RE = re.compile(r'class\s+(\w+)\s*<\s*(\w+(?:::\w+)*)')
_RB_EXTERNAL_BASES = frozenset({
    "ApplicationRecord", "ActiveRecord::Base", "ApplicationController",
    "ActionController::Base", "ApplicationMailer", "ActionMailer::Base",
    "ApplicationJob", "ActiveJob::Base", "Struct", "BasicObject", "Object",
})

# Class definitions (fallback) — anchored to line start to avoid matching in comments
_RB_CLASS_RE = re.compile(
    r"""^\s*class\s+(\w+)""",
    re.MULTILINE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _camel_to_snake(name: str) -> str:
    """Convert CamelCase to snake_case.

    Example: ``UserProfile`` -> ``user_profile``
    """
    result = re.sub(r"([A-Z])", r"_\1", name).lower().lstrip("_")
    return result


def _pluralize(name: str) -> str:
    """Naively pluralize a snake_case name by appending 's'.

    Example: ``user_profile`` -> ``user_profiles``
    """
    return name + "s"


# ---------------------------------------------------------------------------
# Recognizer
# ---------------------------------------------------------------------------


class RubyRecognizer:
    """Recognizes common Ruby architectural patterns via regex.

    Detected patterns:
        - Rails routes (get/post/put/delete/patch/match)     -> ``endpoint`` nodes
        - Rails resource routes (resources/resource)         -> ``endpoint`` nodes
        - ActiveRecord models (< ApplicationRecord)          -> ``database_table`` nodes
        - Sidekiq workers (include Sidekiq::Worker/Job)      -> ``worker`` nodes
        - ``ENV[]`` / ``ENV.fetch`` access                   -> ``env_var`` nodes
        - Net::HTTP / Faraday / HTTParty / RestClient calls  -> ``external_api`` nodes
        - Class definitions (fallback)                       -> ``service`` nodes
    """

    def recognize(self, file_path: Path, content: str) -> ScanResult:
        """Scan *content* of a Ruby file and return discovered nodes/edges."""
        nodes: list[Node] = []
        edges: list[Edge] = []
        rel_path = file_path.as_posix()

        endpoint_ids: list[str] = []
        table_ids: list[str] = []
        captured_class_names: set[str] = set()

        # --- Endpoints (explicit routes) ---
        seen_routes: set[str] = set()
        for match in _RB_ROUTE_RE.finditer(content):
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
                        metadata={"route": route_path, "framework": "rails"},
                    )
                )
                endpoint_ids.append(node_id)

        # --- Endpoints (resource routes) ---
        for match in _RB_RESOURCES_RE.finditer(content):
            resource_name = match.group(1)
            route_path = f"/{resource_name}"
            if route_path not in seen_routes:
                seen_routes.add(route_path)
                node_id = f"endpoint:{route_path}"
                nodes.append(
                    Node(
                        id=node_id,
                        type=NodeType.ENDPOINT,
                        label=route_path,
                        file_path=rel_path,
                        metadata={
                            "route": route_path,
                            "framework": "rails",
                            "resource": resource_name,
                        },
                    )
                )
                endpoint_ids.append(node_id)

        # --- Database tables (ActiveRecord) ---
        for match in _RB_ACTIVERECORD_RE.finditer(content):
            class_name = match.group(1)
            table_name = _pluralize(_camel_to_snake(class_name))
            captured_class_names.add(class_name)
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
                        "orm": "activerecord",
                    },
                )
            )
            table_ids.append(node_id)

        # --- Workers (Sidekiq) ---
        for match in _RB_SIDEKIQ_RE.finditer(content):
            worker_name = match.group(1)
            captured_class_names.add(worker_name)
            node_id = f"worker:{worker_name}"
            nodes.append(
                Node(
                    id=node_id,
                    type=NodeType.WORKER,
                    label=worker_name,
                    file_path=rel_path,
                    metadata={"class_name": worker_name, "framework": "sidekiq"},
                )
            )

        # --- Environment variables ---
        seen_env_vars: set[str] = set()
        for match in _RB_ENV_RE.finditer(content):
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

        # --- External API calls (Net::HTTP / Faraday / HTTParty / RestClient) ---
        seen_urls: set[str] = set()
        for match in _RB_HTTP_RE.finditer(content):
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
        for match in _RB_CLASS_RE.finditer(content):
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
        for match in _RB_REQUIRE_RELATIVE_RE.finditer(content):
            imports.append(ImportInfo(module_path=match.group(1).replace("/", "."), style="relative"))

        implementations: list[ImplementationInfo] = []
        for match in _RB_CLASS_INHERIT_RE.finditer(content):
            child, parent = match.group(1), match.group(2)
            if parent not in _RB_EXTERNAL_BASES:
                implementations.append(ImplementationInfo(child_class=child, parent_class=parent, file_path=file_path.as_posix()))

        return ScanResult(nodes=nodes, edges=edges, imports=imports, implementations=implementations)

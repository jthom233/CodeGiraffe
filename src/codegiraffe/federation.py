"""Cross-repo graph federation for Code Giraffe.

Manages multiple repository architecture graphs and composes them into a
unified federated view with namespace isolation. Each repo's node IDs are
prefixed with ``repo:{name}::`` to prevent collisions across repositories.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from codegiraffe.graph import ArchGraph, Edge, GraphData, Node
from codegiraffe.storage import JSONStorage

logger = logging.getLogger(__name__)

FEDERATION_DIR = Path.home() / ".codegiraffe"
FEDERATION_FILE = FEDERATION_DIR / "federation.json"

# Cross-repo edge types
CROSS_REPO_EDGE_TYPES = frozenset({
    "cross_repo_calls",
    "cross_repo_depends_on",
    "cross_repo_publishes",
    "cross_repo_consumes",
})


class GraphFederation:
    """Manages federated architecture graphs across multiple repositories.

    Provides namespace isolation so that node IDs from different repos
    never collide, and supports composing all registered repos into a
    single unified graph for cross-repo querying.
    """

    def __init__(self) -> None:
        self._repos: dict[str, str] = {}  # repo_name -> repo_path
        self._graphs: dict[str, GraphData] = {}  # repo_name -> graph data

    @staticmethod
    def _repo_name(repo_path: str) -> str:
        """Extract repo name from path (last directory component)."""
        return Path(repo_path).name

    def register_repo(self, repo_path: str) -> str:
        """Register a repo and load its graph. Returns repo name.

        Uses :class:`JSONStorage` to load the repo's graph from
        ``.codegiraffe/graph.json``. Raises :class:`FileNotFoundError`
        if no graph data exists for the repo.
        """
        storage = JSONStorage()
        data = storage.load(repo_path)
        if data is None:
            raise FileNotFoundError(
                f"No graph data found for repo at '{repo_path}'. "
                f"Run codegiraffe_init first."
            )

        name = self._repo_name(repo_path)
        self._repos[name] = repo_path
        self._graphs[name] = data
        return name

    def namespace_node_id(self, repo_name: str, node_id: str) -> str:
        """Prefix node ID with repo namespace: ``repo:{name}::{id}``."""
        return f"repo:{repo_name}::{node_id}"

    def parse_namespace(self, namespaced_id: str) -> tuple[str, str]:
        """Parse ``repo:name::node_id`` into ``(repo_name, node_id)``.

        Raises :class:`ValueError` if the ID does not match the expected
        ``repo:{name}::`` namespace format.
        """
        prefix = "repo:"
        if not namespaced_id.startswith(prefix):
            raise ValueError(
                f"Invalid namespaced ID '{namespaced_id}': "
                f"expected format 'repo:{{name}}::{{node_id}}'."
            )

        # Find the '::' separator after the 'repo:' prefix
        rest = namespaced_id[len(prefix):]
        sep_idx = rest.find("::")
        if sep_idx == -1:
            raise ValueError(
                f"Invalid namespaced ID '{namespaced_id}': "
                f"missing '::' separator."
            )

        repo_name = rest[:sep_idx]
        node_id = rest[sep_idx + 2:]
        return repo_name, node_id

    def get_unified_graph(self) -> GraphData:
        """Compose all repo graphs into a single federated GraphData.

        All node IDs are prefixed with ``repo:{name}::`` to ensure
        namespace isolation. Edge source and target fields are
        similarly namespaced.
        """
        merged_nodes: dict[str, Node] = {}
        merged_edges: list[Edge] = []

        for repo_name, graph_data in self._graphs.items():
            # Namespace nodes
            for node_id, node in graph_data.nodes.items():
                ns_id = self.namespace_node_id(repo_name, node_id)
                merged_nodes[ns_id] = Node(
                    id=ns_id,
                    type=node.type,
                    label=node.label,
                    metadata=dict(node.metadata),
                    file_path=node.file_path,
                    manual=node.manual,
                )

            # Namespace edge endpoints
            for edge in graph_data.edges:
                ns_source = self.namespace_node_id(repo_name, edge.source)
                ns_target = self.namespace_node_id(repo_name, edge.target)
                merged_edges.append(
                    Edge(
                        source=ns_source,
                        target=ns_target,
                        type=edge.type,
                        metadata=dict(edge.metadata),
                        manual=edge.manual,
                    )
                )

        return GraphData(
            nodes=merged_nodes,
            edges=merged_edges,
            project_path="federation",
            schema_version="1.0",
        )

    def get_cross_repo_edges(self) -> list[Edge]:
        """Return all edges that cross repository boundaries.

        An edge is considered cross-repo if its source and target belong
        to different repo namespaces (different ``repo:{name}`` prefixes).
        """
        unified = self.get_unified_graph()
        cross_edges: list[Edge] = []

        for edge in unified.edges:
            try:
                source_repo, _ = self.parse_namespace(edge.source)
                target_repo, _ = self.parse_namespace(edge.target)
            except ValueError:
                continue

            if source_repo != target_repo:
                cross_edges.append(edge)

        return cross_edges

    def query_federated(self, node_id: str, depth: int = 2) -> GraphData:
        """Query the federated graph for a node (expects namespaced ID).

        Builds the unified graph, wraps it in an :class:`ArchGraph`, and
        extracts a subgraph centered on *node_id* up to *depth* hops.
        Returns an empty :class:`GraphData` if the node is not found.
        """
        unified = self.get_unified_graph()
        arch = ArchGraph(unified)
        return arch.get_subgraph(node_id, depth)

    def save_federation(self) -> None:
        """Persist federation config to ``~/.codegiraffe/federation.json``.

        Saves the repo name to path mapping so it can be restored later.
        """
        FEDERATION_DIR.mkdir(parents=True, exist_ok=True)
        config = {
            "repos": dict(self._repos),
        }
        FEDERATION_FILE.write_text(
            json.dumps(config, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def load_federation(cls) -> GraphFederation:
        """Load federation config and rebuild from persisted state.

        Reads the repo path list from ``~/.codegiraffe/federation.json``
        and re-registers all repos (reloading their graphs). If the
        federation file does not exist, returns an empty federation.
        """
        fed = cls()

        if not FEDERATION_FILE.is_file():
            return fed

        try:
            raw = FEDERATION_FILE.read_text(encoding="utf-8")
            config = json.loads(raw)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "Could not load federation config from %s: %s",
                FEDERATION_FILE,
                exc,
            )
            return fed

        repos: dict[str, str] = config.get("repos", {})
        for repo_name, repo_path in repos.items():
            try:
                fed.register_repo(repo_path)
            except FileNotFoundError:
                logger.warning(
                    "Skipping repo '%s' at '%s': graph not found.",
                    repo_name,
                    repo_path,
                )

        return fed

"""MCP server entry point for Code Giraffe.

Exposes architecture knowledge graph tools via the FastMCP protocol,
allowing MCP clients to initialize, query, annotate, and synchronize
architectural graphs for Python projects.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import networkx as nx
from mcp.server.fastmcp import FastMCP

from codegiraffe.coordination import CoordinationStore
from codegiraffe.federation import GraphFederation
from codegiraffe.graph import ArchGraph, Edge, GraphData, Node
from codegiraffe.query import (
    compute_blast_radius,
    context_for_task,
    detect_drift,
    file_coupling,
    generate_impact_summary,
    get_contracts,
    map_files_to_nodes,
    query_by_node,
    query_by_type,
    suggest_tests,
    validate_changes,
    validate_contracts,
)
from codegiraffe.diff_parser import parse_diff
from codegiraffe.git_utils import (
    get_changed_files,
    get_uncommitted_diff,
    is_git_repo,
    NotAGitRepoError,
)
from codegiraffe.scanner import scan_project
from codegiraffe.storage import JSONStorage, StorageBackend
from codegiraffe.versioning import VersionStore

# ---------------------------------------------------------------------------
# Server and shared state
# ---------------------------------------------------------------------------

mcp = FastMCP("codegiraffe")

_storage: StorageBackend = JSONStorage()
_graph: ArchGraph | None = None
_coordinator = CoordinationStore()
_version_store = VersionStore()
_federation = GraphFederation()


def _get_storage(backend: str = "json"):
    """Get a storage backend by name."""
    if backend == "sqlite":
        from codegiraffe.sqlite_storage import SQLiteStorage

        return SQLiteStorage()
    elif backend == "neo4j":
        from codegiraffe.neo4j_storage import Neo4jStorage

        return Neo4jStorage()
    return JSONStorage()


def _ensure_graph(project_path: str) -> ArchGraph:
    """Load the graph from storage, raising if no graph has been initialized.

    On the first call for a given project the graph is loaded from disk and
    cached in the module-level ``_graph`` variable.  Subsequent calls reuse
    the cached instance unless the project path changes.
    """
    global _graph  # noqa: PLW0603

    if _graph is not None:
        data = _graph.to_data()
        if data.project_path == project_path:
            return _graph

    stored = _storage.load(project_path)
    if stored is None:
        raise RuntimeError(
            f"No architecture graph found for '{project_path}'. "
            "Run codegiraffe_init first."
        )

    _graph = ArchGraph(stored)
    return _graph


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def codegiraffe_init(
    project_path: str,
    rescan: bool = False,
    backend: str = "json",
    scanner_mode: str = "regex",
    include_tests: bool = False,
) -> str:
    """Initialize or re-scan the architecture knowledge graph for a project.

    Scans the project directory for architectural patterns (endpoints,
    database tables, workers, env vars, external APIs, services) and builds
    a graph. When *rescan* is True and an existing graph is found, manually
    added annotations are preserved.

    Use *backend* to select the storage backend: ``"json"`` (default),
    ``"sqlite"`` for a SQLite database, or ``"neo4j"`` for Neo4j.

    Use *scanner_mode* to choose the scanning strategy: ``"regex"`` (default)
    for regex-based pattern matching, or ``"ast"`` for tree-sitter AST-based
    scanning (requires tree-sitter packages).

    Returns a summary of the initialized graph.
    """
    global _graph, _storage  # noqa: PLW0603

    try:
        _storage = _get_storage(backend)
        # Preserve manual annotations when rescanning
        old_data: GraphData | None = None
        if rescan:
            old_data = _storage.load(project_path)

        # Select scanner registry based on mode
        registry = None
        if scanner_mode == "ast":
            from codegiraffe.ast_scanner import get_ast_registry

            registry = get_ast_registry()

        # Scan the project
        result = scan_project(project_path, registry=registry, include_tests=include_tests)

        # Build graph data from scan results
        nodes: dict[str, Node] = {node.id: node for node in result.nodes}
        edges = result.edges

        data = GraphData(
            nodes=nodes,
            edges=edges,
            project_path=project_path,
            last_scan=datetime.now(timezone.utc).isoformat(),
        )

        graph = ArchGraph(data)

        # Merge back manual annotations from previous graph
        if rescan and old_data is not None:
            graph.merge_manual_annotations(old_data)

        # Persist and cache
        _storage.save(project_path, graph.to_data())
        _graph = graph

        # Auto-version after init/rescan
        prev_data = old_data if old_data is not None else GraphData()
        _version_store.add_version(
            project_path, prev_data, graph.to_data(),
            "Rescan" if rescan else "Init",
        )

        final_data = graph.to_data()
        return (
            f"Initialized graph with {len(final_data.nodes)} nodes "
            f"and {len(final_data.edges)} edges"
        )
    except Exception as exc:
        return f"Error initializing graph: {exc}"


@mcp.tool()
def codegiraffe_query(
    project_path: str,
    node_id: str | None = None,
    node_type: str | None = None,
    depth: int = 2,
) -> str:
    """Query the architecture graph by node ID or node type.

    Provide *node_id* to extract a subgraph centered on that node (up to
    *depth* hops), or *node_type* to retrieve all nodes of that type with
    their direct edges. Returns the subgraph as formatted JSON.
    """
    try:
        graph = _ensure_graph(project_path)

        if node_id is not None:
            subgraph = query_by_node(graph, node_id, depth)
        elif node_type is not None:
            subgraph = query_by_type(graph, node_type)
        else:
            return "Error: provide either node_id or node_type"

        return subgraph.model_dump_json(indent=2)
    except Exception as exc:
        return f"Error querying graph: {exc}"


@mcp.tool()
def codegiraffe_add_relation(
    project_path: str,
    source: str,
    target: str,
    relation_type: str,
    source_type: str = "service",
    target_type: str = "service",
    metadata: str = "{}",
) -> str:
    """Add a manual relationship (edge) between two architectural nodes.

    If *source* or *target* nodes do not exist they are auto-created with
    the given types. The edge is marked as ``manual=True`` so it survives
    automated re-scans. *metadata* is a JSON string of extra key/value pairs.
    """
    try:
        graph = _ensure_graph(project_path)

        # Parse metadata JSON
        try:
            meta = json.loads(metadata)
        except json.JSONDecodeError:
            return "Error: metadata is not valid JSON"

        # Auto-create source node if missing
        if source not in graph.graph:
            graph.add_node(
                Node(
                    id=source,
                    type=source_type,
                    label=source,
                    manual=True,
                )
            )

        # Auto-create target node if missing
        if target not in graph.graph:
            graph.add_node(
                Node(
                    id=target,
                    type=target_type,
                    label=target,
                    manual=True,
                )
            )

        # Add the manual edge
        graph.add_edge(
            Edge(
                source=source,
                target=target,
                type=relation_type,
                metadata=meta,
                manual=True,
            )
        )

        # Persist
        _storage.save(project_path, graph.to_data())

        return (
            f"Added manual relation: {source} --[{relation_type}]--> {target}"
        )
    except Exception as exc:
        return f"Error adding relation: {exc}"


@mcp.tool()
def codegiraffe_context_for(
    project_path: str,
    task: str,
    max_nodes: int = 20,
    use_embeddings: bool = True,
    include_impact: bool = False,
    include_changes: bool = False,
) -> str:
    """Get the most relevant subgraph for a natural-language task description.

    When sentence-transformers is installed and *use_embeddings* is True, uses
    embedding-based semantic similarity for scoring.  Otherwise falls back to
    keyword overlap scoring.  Returns the top-matching nodes with their
    immediate neighbors, capped at *max_nodes*.

    When *include_impact* is True, each node in the result is augmented with
    ``_blast_radius_count`` and ``_risk_score`` metadata fields.

    When *include_changes* is True, nodes affected by uncommitted git changes
    receive a score boost and ``_recently_changed`` / ``_in_change_blast_radius``
    metadata annotations.

    Useful for scoping what parts of the architecture are relevant before
    making changes.
    """
    try:
        graph = _ensure_graph(project_path)
        subgraph = context_for_task(graph, task, max_nodes, use_embeddings=use_embeddings)

        if include_impact:
            total_nodes = len(graph.graph)
            degree = nx.degree_centrality(graph.graph) if total_nodes > 0 else {}
            betweenness = graph.get_betweenness_centrality() if total_nodes > 0 else {}
            for nid, node in subgraph.nodes.items():
                desc_count = len(graph.get_all_descendants(nid))
                risk = (
                    degree.get(nid, 0.0) * 0.4
                    + betweenness.get(nid, 0.0) * 0.4
                    + (desc_count / total_nodes * 0.2 if total_nodes > 0 else 0.0)
                )
                node.metadata["_blast_radius_count"] = desc_count
                node.metadata["_risk_score"] = round(risk, 4)

        if include_changes:
            try:
                changed_files = get_changed_files(project_path)
                if changed_files:
                    file_node_map = map_files_to_nodes(graph, changed_files)
                    changed_node_ids: set[str] = set()
                    for node_ids in file_node_map.values():
                        changed_node_ids.update(node_ids)

                    # Compute blast radius for changed nodes
                    blast_node_ids: set[str] = set()
                    for nid in changed_node_ids:
                        if nid in graph.graph:
                            descendants = graph.get_all_descendants(nid)
                            blast_node_ids.update(descendants)
                    # Remove the changed nodes themselves from blast set
                    blast_node_ids -= changed_node_ids

                    # Apply score boosts and metadata annotations
                    for nid, node in subgraph.nodes.items():
                        if nid in changed_node_ids:
                            current_score = node.metadata.get("_relevance_score", 0.0)
                            node.metadata["_relevance_score"] = round(
                                current_score + 0.3, 4
                            )
                            node.metadata["_recently_changed"] = True
                        elif nid in blast_node_ids:
                            current_score = node.metadata.get("_relevance_score", 0.0)
                            node.metadata["_relevance_score"] = round(
                                current_score + 0.15, 4
                            )
                            node.metadata["_in_change_blast_radius"] = True
            except Exception:
                # Silent fallback — don't break existing behavior
                pass

        return subgraph.model_dump_json(indent=2)
    except Exception as exc:
        return f"Error computing context: {exc}"


@mcp.tool()
def codegiraffe_detect_drift(project_path: str) -> str:
    """Detect drift between the architecture graph and the actual codebase.

    Re-scans the project and compares the results against the stored graph.
    Reports nodes that exist in the graph but not in code, nodes found in
    code but missing from the graph, and potential renames.

    Returns a JSON array of drift records.
    """
    try:
        graph = _ensure_graph(project_path)
        drifts = detect_drift(graph, project_path)
        return json.dumps(drifts, indent=2)
    except Exception as exc:
        return f"Error detecting drift: {exc}"


@mcp.tool()
def codegiraffe_hotspots(
    project_path: str, top_n: int = 10, metrics: str = "degree"
) -> str:
    """Find the most connected nodes (architectural hotspots) in the graph.

    Ranks nodes by degree centrality -- highly connected nodes are likely
    architectural hotspots that deserve extra attention during changes.

    Use *metrics* to select the ranking strategy:
    - ``"degree"`` (default): rank by degree centrality
    - ``"betweenness"``: rank by betweenness centrality (bottleneck nodes)
    - ``"combined"``: rank by 0.5*degree + 0.5*betweenness

    Returns a JSON array of {node_id, label, type, score} objects.
    """
    try:
        graph = _ensure_graph(project_path)

        if metrics == "betweenness":
            betweenness = graph.get_betweenness_centrality()
            scored_pairs = sorted(
                betweenness.items(), key=lambda x: x[1], reverse=True
            )[:top_n]
            result = []
            for nid, score in scored_pairs:
                node_data = graph.graph.nodes[nid].get("node")
                if node_data is None:
                    continue
                result.append({
                    "node_id": nid,
                    "label": node_data.label,
                    "type": node_data.type,
                    "score": round(score, 4),
                })
            return json.dumps(result, indent=2)

        elif metrics == "combined":
            degree = nx.degree_centrality(graph.graph)
            betweenness = graph.get_betweenness_centrality()
            combined = {
                nid: degree.get(nid, 0.0) * 0.5 + betweenness.get(nid, 0.0) * 0.5
                for nid in graph.graph.nodes
            }
            scored_pairs = sorted(
                combined.items(), key=lambda x: x[1], reverse=True
            )[:top_n]
            result = []
            for nid, score in scored_pairs:
                node_data = graph.graph.nodes[nid].get("node")
                if node_data is None:
                    continue
                result.append({
                    "node_id": nid,
                    "label": node_data.label,
                    "type": node_data.type,
                    "score": round(score, 4),
                })
            return json.dumps(result, indent=2)

        else:
            # Default: degree centrality (original behavior)
            hotspots = graph.get_hotspots(top_n)
            result = [
                {
                    "node_id": node.id,
                    "label": node.label,
                    "type": node.type,
                    "score": round(score, 4),
                }
                for node, score in hotspots
            ]
            return json.dumps(result, indent=2)
    except Exception as exc:
        return f"Error computing hotspots: {exc}"


# ---------------------------------------------------------------------------
# Actionable intelligence tools (v0.7.0)
# ---------------------------------------------------------------------------


@mcp.tool()
def codegiraffe_blast_radius(
    project_path: str,
    node_id: str,
    include_upstream: bool = False,
    max_depth: int | None = None,
) -> str:
    """Analyze the blast radius of changing a specific node.

    Shows what breaks if you change this node -- downstream dependencies
    ranked by severity (direct, transitive, indirect), plus any circular
    dependencies and hotspots in the impact zone.

    Returns a human-readable markdown impact report.
    """
    try:
        graph = _ensure_graph(project_path)
        blast = compute_blast_radius(
            graph, node_id, include_upstream=include_upstream, max_depth=max_depth
        )
        return generate_impact_summary(blast, graph)
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return f"Error computing blast radius: {exc}"


@mcp.tool()
def codegiraffe_risk_assessment(
    project_path: str,
    node_ids: list[str] | None = None,
) -> str:
    """Assess architectural risk for specific nodes or the entire graph.

    Risk score = (degree_centrality * 0.4) + (betweenness_centrality * 0.4)
                 + (descendant_count / total_nodes * 0.2)

    If node_ids provided: assess those nodes. If None: top-10 riskiest nodes.
    Returns markdown report ranked by risk score.
    """
    try:
        graph = _ensure_graph(project_path)
        total_nodes = len(graph.graph)
        if total_nodes == 0:
            return "Graph is empty -- no nodes to assess."

        degree = nx.degree_centrality(graph.graph)
        betweenness = graph.get_betweenness_centrality()

        target_ids = node_ids if node_ids is not None else list(graph.graph.nodes)

        scored: list[dict] = []
        for nid in target_ids:
            if nid not in graph.graph:
                continue
            node_data = graph.graph.nodes[nid].get("node")
            if node_data is None:
                continue
            desc_count = len(graph.get_all_descendants(nid))
            risk = (
                degree.get(nid, 0.0) * 0.4
                + betweenness.get(nid, 0.0) * 0.4
                + (desc_count / total_nodes) * 0.2
            )
            scored.append({
                "node_id": nid,
                "label": node_data.label,
                "type": node_data.type,
                "risk_score": round(risk, 4),
                "degree_centrality": round(degree.get(nid, 0.0), 4),
                "betweenness_centrality": round(betweenness.get(nid, 0.0), 4),
                "blast_radius_count": desc_count,
                "file_path": node_data.file_path,
            })

        scored.sort(key=lambda x: x["risk_score"], reverse=True)
        if node_ids is None:
            scored = scored[:10]

        return _format_risk_report(scored, total_nodes)
    except Exception as exc:
        return f"Error computing risk assessment: {exc}"


@mcp.tool()
def codegiraffe_cycles(project_path: str, max_cycles: int = 20) -> str:
    """Detect circular dependencies in the architecture graph.

    Returns markdown-formatted list of cycles with path, edge types,
    severity (shorter cycles are more severe), and files involved.
    """
    try:
        graph = _ensure_graph(project_path)
        cycles = graph.detect_cycles(max_cycles=max_cycles)
        if not cycles:
            return "No circular dependencies detected."
        lines = ["## Circular Dependencies", ""]
        lines.append(f"**{len(cycles)} cycle(s) detected**")
        lines.append("")
        for i, cycle in enumerate(cycles, 1):
            display_path = cycle + [cycle[0]]
            path_str = " -> ".join(display_path)
            severity = (
                "high" if len(cycle) <= 2
                else "medium" if len(cycle) <= 4
                else "low"
            )
            lines.append(
                f"### Cycle {i} (length {len(cycle)}, severity: {severity})"
            )
            lines.append("```")
            lines.append(path_str)
            lines.append("```")
            edge_types: list[str] = []
            for j in range(len(cycle)):
                src = cycle[j]
                tgt = cycle[(j + 1) % len(cycle)]
                edge_data = graph.graph.edges.get((src, tgt), {})
                edge_obj = edge_data.get("edge")
                if edge_obj:
                    edge_types.append(f"{src} --[{edge_obj.type}]--> {tgt}")
            if edge_types:
                lines.append("**Edges:**")
                for et in edge_types:
                    lines.append(f"- {et}")
            files: list[str] = []
            for nid in cycle:
                node_data = graph.graph.nodes[nid].get("node")
                if node_data and node_data.file_path:
                    files.append(f"{nid}: {node_data.file_path}")
            if files:
                lines.append("**Files:**")
                for f in files:
                    lines.append(f"- {f}")
            lines.append("")
        return "\n".join(lines)
    except Exception as exc:
        return f"Error detecting cycles: {exc}"


# ---------------------------------------------------------------------------
# Contract tools
# ---------------------------------------------------------------------------

VALID_CONTRACT_TYPES = {"api", "event", "data", "config"}


@mcp.tool()
def codegiraffe_contracts(
    project_path: str,
    contract_type: str | None = None,
    status: str | None = None,
    node_id: str | None = None,
) -> str:
    """List all contracts in the architecture graph.

    Contracts represent agreements between components (APIs, events, data
    schemas, config). Optionally filter by contract_type, status, or a
    specific producer/consumer node_id.
    """
    try:
        graph = _ensure_graph(project_path)
        contracts = get_contracts(
            graph,
            contract_type=contract_type,
            status=status,
            node_id=node_id,
        )
        if not contracts:
            return (
                "No contracts found. Use `codegiraffe_add_contract` to register "
                "a contract between components."
            )
        lines = ["## Contracts", ""]
        lines.append(f"**{len(contracts)} contract(s) found**")
        lines.append("")
        for c in contracts:
            lines.append(f"### {c['label']}")
            lines.append(f"- **Type:** {c['contract_type']}")
            lines.append(f"- **Status:** {c['status']}")
            if c.get("version"):
                lines.append(f"- **Version:** {c['version']}")
            prod = c["producer"]
            lines.append(
                f"- **Producer:** {prod['label']}"
                + (f" ({prod.get('type', '')})" if prod.get("type") else "")
            )
            if c["consumers"]:
                lines.append("- **Consumers:**")
                for consumer in c["consumers"]:
                    lines.append(
                        f"  - {consumer['label']}"
                        + (f" ({consumer.get('type', '')})" if consumer.get("type") else "")
                    )
            else:
                lines.append("- **Consumers:** none")
            lines.append("")
        return "\n".join(lines)
    except Exception as exc:
        return f"Error listing contracts: {exc}"


@mcp.tool()
def codegiraffe_validate_contracts(project_path: str) -> str:
    """Validate all contracts in the architecture graph.

    Checks whether producer and consumer nodes referenced by each contract
    still exist in the graph. Reports valid, broken, orphaned, and
    deprecated-with-active-consumers contracts.
    """
    try:
        graph = _ensure_graph(project_path)
        result = validate_contracts(graph)
        total = result["total_contracts"]
        if total == 0:
            return (
                "No contracts found to validate. Use `codegiraffe_add_contract` "
                "to register contracts first."
            )
        lines = ["## Contract Validation Report", ""]
        lines.append(f"**Total contracts:** {total}")
        lines.append("")

        if result["valid"]:
            lines.append(f"### Valid ({len(result['valid'])})")
            lines.append("")
            for c in result["valid"]:
                lines.append(f"- **{c['label']}** ({c['contract_type']})")
            lines.append("")

        if result["broken"]:
            lines.append(f"### Broken -- Producer Missing ({len(result['broken'])})")
            lines.append("")
            for c in result["broken"]:
                lines.append(
                    f"- **{c['label']}** -- producer `{c['producer']}` not in graph"
                )
            lines.append("")

        if result["orphaned"]:
            lines.append(f"### Orphaned -- All Consumers Missing ({len(result['orphaned'])})")
            lines.append("")
            for c in result["orphaned"]:
                lines.append(
                    f"- **{c['label']}** -- consumers {c['consumers']} not in graph"
                )
            lines.append("")

        if result["deprecated_with_consumers"]:
            lines.append(
                f"### Deprecated With Active Consumers "
                f"({len(result['deprecated_with_consumers'])})"
            )
            lines.append("")
            for c in result["deprecated_with_consumers"]:
                lines.append(
                    f"- **{c['label']}** -- deprecated but still consumed by "
                    f"{c['consumers_existing']}"
                )
            lines.append("")

        return "\n".join(lines)
    except Exception as exc:
        return f"Error validating contracts: {exc}"


@mcp.tool()
def codegiraffe_add_contract(
    project_path: str,
    name: str,
    contract_type: str,
    producer: str,
    consumers: str,
    version: str = "",
    metadata: str = "{}",
) -> str:
    """Add a contract to the architecture graph.

    A contract represents an agreement between a producer and one or more
    consumers (e.g. an API contract, event schema, data format, config).

    *consumers* is a comma-separated string of node IDs.
    *contract_type* must be one of: api, event, data, config.
    *metadata* is a JSON string of extra key/value pairs.
    """
    try:
        if contract_type not in VALID_CONTRACT_TYPES:
            return (
                f"Error: invalid contract_type '{contract_type}'. "
                f"Must be one of: {', '.join(sorted(VALID_CONTRACT_TYPES))}"
            )

        graph = _ensure_graph(project_path)

        # Parse metadata JSON
        try:
            extra_meta = json.loads(metadata)
        except json.JSONDecodeError:
            return "Error: metadata is not valid JSON"

        consumer_list = [c.strip() for c in consumers.split(",") if c.strip()]

        contract_id = f"contract:{name}"

        # Build contract metadata
        contract_meta: dict = {
            "contract_type": contract_type,
            "producer": producer,
            "consumers": consumer_list,
            "version": version,
            "status": "active",
            **extra_meta,
        }

        # Create contract node
        graph.add_node(
            Node(
                id=contract_id,
                type="contract",
                label=name,
                metadata=contract_meta,
                manual=True,
            )
        )

        # Collect warnings for missing nodes
        warnings: list[str] = []

        # Create produces edge: producer -> contract
        if producer not in graph.graph:
            warnings.append(f"Warning: producer '{producer}' not found in graph")
        graph.add_edge(
            Edge(
                source=producer,
                target=contract_id,
                type="produces",
                manual=True,
            )
        )

        # Create consumes_contract edges: consumer -> contract
        for cid in consumer_list:
            if cid not in graph.graph:
                warnings.append(f"Warning: consumer '{cid}' not found in graph")
            graph.add_edge(
                Edge(
                    source=cid,
                    target=contract_id,
                    type="consumes_contract",
                    manual=True,
                )
            )

        # Persist
        _storage.save(project_path, graph.to_data())

        result_lines = [
            f"Added contract '{name}' ({contract_type}): "
            f"{producer} --[produces]--> {contract_id}"
        ]
        for cid in consumer_list:
            result_lines.append(
                f"  {cid} --[consumes_contract]--> {contract_id}"
            )
        if warnings:
            result_lines.append("")
            result_lines.extend(warnings)

        return "\n".join(result_lines)
    except Exception as exc:
        return f"Error adding contract: {exc}"


# ---------------------------------------------------------------------------
# Change impact validation tools (v0.10.0)
# ---------------------------------------------------------------------------


@mcp.tool()
def codegiraffe_validate_changes(
    project_path: str,
    diff: str | None = None,
    auto: bool = True,
) -> str:
    """Analyze uncommitted (or arbitrary) changes against the architecture graph to detect incomplete modifications.

    Parses a diff, maps changed files to graph nodes, computes blast radius,
    and reports potentially missing changes and contract violations.

    When auto=True and diff is not provided, reads uncommitted changes from git.
    """
    try:
        graph = _ensure_graph(project_path)
    except Exception as exc:
        return f"Error: {exc}"

    # Obtain the diff text
    raw_diff: str | None = diff
    if raw_diff is None:
        if not auto:
            return "Error: no diff provided and auto=False. Pass a diff string or set auto=True."
        try:
            raw_diff = get_uncommitted_diff(project_path)
        except NotAGitRepoError:
            return f"Error: '{project_path}' is not a git repository."

    if not raw_diff or not raw_diff.strip():
        return "No uncommitted changes found."

    diff_files = parse_diff(raw_diff)
    if not diff_files:
        return "No uncommitted changes found."

    report = validate_changes(graph, diff_files)
    return _format_validation_report(report)


@mcp.tool()
def codegiraffe_suggest_tests(
    project_path: str,
    diff: str | None = None,
    auto: bool = True,
    max_suggestions: int = 20,
) -> str:
    """Suggest test files to run based on uncommitted (or arbitrary) changes.

    Uses graph relationships, naming conventions, and blast radius analysis
    to identify the most relevant tests for a given change set.

    When auto=True and diff is not provided, reads uncommitted changes from git.
    """
    try:
        graph = _ensure_graph(project_path)
    except Exception as exc:
        return f"Error: {exc}"

    # Obtain the diff text
    raw_diff: str | None = diff
    if raw_diff is None:
        if not auto:
            return "Error: no diff provided and auto=False. Pass a diff string or set auto=True."
        try:
            raw_diff = get_uncommitted_diff(project_path)
        except NotAGitRepoError:
            return f"Error: '{project_path}' is not a git repository."

    if not raw_diff or not raw_diff.strip():
        return "No uncommitted changes found."

    diff_files = parse_diff(raw_diff)
    if not diff_files:
        return "No uncommitted changes found."

    suggestions = suggest_tests(graph, diff_files, max_suggestions=max_suggestions)
    return _format_test_suggestions(suggestions)


@mcp.tool()
def codegiraffe_file_coupling(
    project_path: str,
    file_path: str | None = None,
    depth: int = 100,
    min_commits: int = 3,
    min_coupling: float = 0.1,
) -> str:
    """Analyze file coupling from git co-change history.

    Mines recent commit history to find files that frequently change
    together, then cross-references with the architecture graph to detect
    implicit coupling not yet captured in the graph.
    """
    try:
        graph = _ensure_graph(project_path)
    except Exception as exc:
        return f"Error: {exc}"

    if not is_git_repo(project_path):
        return f"Error: '{project_path}' is not a git repository."

    pairs = file_coupling(
        graph,
        project_path,
        file_path=file_path,
        depth=depth,
        min_commits=min_commits,
        min_coupling=min_coupling,
    )
    return _format_coupling_report(pairs, file_path)


# ---------------------------------------------------------------------------
# Change impact report helpers (private, not MCP tools)
# ---------------------------------------------------------------------------


def _format_validation_report(report) -> str:
    """Format a ChangeReport as a markdown report."""
    lines = ["## Change Impact Validation", ""]

    # Changes Detected
    lines.append("### Changes Detected")
    if report.changed_files:
        for df in report.changed_files:
            lines.append(f"- `{df.path}` ({df.status})")
    else:
        lines.append("- No files changed")
    lines.append("")

    # Impact Analysis
    lines.append("### Impact Analysis")
    lines.append(f"- **Total blast radius:** {report.total_blast_radius} node(s)")
    lines.append("")

    # Covered Impact
    if report.covered_nodes:
        lines.append(f"### Covered Impact ({len(report.covered_nodes)})")
        for nid in report.covered_nodes:
            lines.append(f"- `{nid}` (covered in diff)")
        lines.append("")

    # Potentially Missing Changes
    if report.uncovered_nodes:
        lines.append(f"### Potentially Missing Changes ({len(report.uncovered_nodes)})")
        for nid in report.uncovered_nodes:
            lines.append(f"- `{nid}`")
        lines.append("")

    # Contract Violations
    if report.contract_violations:
        lines.append(f"### Contract Violations ({len(report.contract_violations)})")
        for violation in report.contract_violations:
            lines.append(f"- {violation}")
        lines.append("")

    # Recommendations
    if report.recommendations:
        lines.append(f"### Recommendations ({len(report.recommendations)})")
        for rec in report.recommendations:
            lines.append(f"- {rec}")
        lines.append("")

    return "\n".join(lines)


def _format_test_suggestions(suggestions) -> str:
    """Format a list of TestSuggestion as a markdown report."""
    if not suggestions:
        return "## Test Suggestions\n\nNo test suggestions found for the given changes."

    lines = ["## Test Suggestions", ""]
    lines.append(f"**{len(suggestions)} test(s) suggested**")
    lines.append("")

    # Group by score range
    high = [s for s in suggestions if s.score >= 0.7]
    medium = [s for s in suggestions if 0.3 <= s.score < 0.7]
    low = [s for s in suggestions if s.score < 0.3]

    if high:
        lines.append("### High Relevance")
        for s in high:
            lines.append(
                f"- **{s.file_path}** (score: {s.score:.1f}) — {s.reason} [{s.strategy}]"
            )
        lines.append("")

    if medium:
        lines.append("### Medium Relevance")
        for s in medium:
            lines.append(
                f"- **{s.file_path}** (score: {s.score:.1f}) — {s.reason} [{s.strategy}]"
            )
        lines.append("")

    if low:
        lines.append("### Low Relevance")
        for s in low:
            lines.append(
                f"- **{s.file_path}** (score: {s.score:.1f}) — {s.reason} [{s.strategy}]"
            )
        lines.append("")

    return "\n".join(lines)


def _format_coupling_report(pairs, file_path: str | None = None) -> str:
    """Format a list of CouplingPair as a markdown report."""
    lines = ["## File Coupling Analysis", ""]

    if file_path:
        lines.append(f"**Focus file:** `{file_path}`")
        lines.append("")

    if not pairs:
        lines.append("No file coupling pairs found above the threshold.")
        return "\n".join(lines)

    lines.append(f"**{len(pairs)} coupled pair(s) found**")
    lines.append("")

    # Markdown table
    lines.append("| Coupled File | Co-Changes | Coupling | In Graph? |")
    lines.append("|---|---|---|---|")
    for p in pairs:
        # Show the "other" file when a focus file is given
        if file_path:
            other = p.file_b if p.file_a == file_path else p.file_a
        else:
            other = f"{p.file_a} <-> {p.file_b}"
        in_graph = "Yes" if p.in_graph else "No"
        lines.append(
            f"| `{other}` | {p.co_change_count} | {p.coupling:.2f} | {in_graph} |"
        )
    lines.append("")

    # Implicit coupling section
    implicit = [p for p in pairs if not p.in_graph and p.coupling >= 0.5]
    if implicit:
        lines.append(f"### Implicit Coupling ({len(implicit)} pair(s) not in graph)")
        lines.append("")
        for p in implicit:
            lines.append(
                f"- `{p.file_a}` <-> `{p.file_b}` (coupling: {p.coupling:.2f}, "
                f"co-changes: {p.co_change_count}) — consider adding a graph edge"
            )
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Risk report helpers (private, not MCP tools)
# ---------------------------------------------------------------------------


def _format_risk_report(scored: list[dict], total_nodes: int) -> str:
    """Format a list of risk-scored nodes as a markdown report."""
    lines = ["## Risk Assessment Report", ""]
    lines.append(f"**Graph size:** {total_nodes} nodes")
    lines.append(f"**Nodes assessed:** {len(scored)}")
    lines.append("")
    for i, item in enumerate(scored, 1):
        lines.append(f"### {i}. {item['label']} (`{item['node_id']}`)")
        lines.append(f"- **Risk score:** {item['risk_score']}")
        lines.append(f"- **Type:** {item['type']}")
        lines.append(f"- **Degree centrality:** {item['degree_centrality']}")
        lines.append(f"- **Betweenness centrality:** {item['betweenness_centrality']}")
        lines.append(f"- **Blast radius:** {item['blast_radius_count']} downstream nodes")
        if item.get("file_path"):
            lines.append(f"- **File:** {item['file_path']}")
        why = _risk_explanation(item)
        lines.append(f"- **Why this matters:** {why}")
        lines.append("")
    return "\n".join(lines)


def _risk_explanation(item: dict) -> str:
    """Produce a brief human-readable explanation of a node's risk score."""
    reasons: list[str] = []
    if item["degree_centrality"] > 0.3:
        reasons.append("highly connected hub")
    if item["betweenness_centrality"] > 0.2:
        reasons.append("critical bottleneck on many paths")
    if item["blast_radius_count"] > 5:
        reasons.append(
            f"changes propagate to {item['blast_radius_count']} downstream nodes"
        )
    if not reasons:
        reasons.append("moderate connectivity")
    return "; ".join(reasons)


@mcp.tool()
def codegiraffe_sync(project_path: str, include_tests: bool = False) -> str:
    """Re-scan the project and synchronize the architecture graph.

    Performs a fresh scan, replaces all auto-discovered nodes and edges,
    while preserving any manually added annotations. Returns a summary
    of what changed.
    """
    global _graph  # noqa: PLW0603

    try:
        graph = _ensure_graph(project_path)
        old_data = graph.to_data()
        old_node_count = len(old_data.nodes)
        old_edge_count = len(old_data.edges)

        # Re-scan
        result = scan_project(project_path, include_tests=include_tests)

        # Build new graph from scan results
        nodes: dict[str, Node] = {node.id: node for node in result.nodes}
        edges = result.edges

        new_data = GraphData(
            nodes=nodes,
            edges=edges,
            project_path=project_path,
            last_scan=datetime.now(timezone.utc).isoformat(),
        )

        new_graph = ArchGraph(new_data)

        # Merge back manual annotations from the old graph
        new_graph.merge_manual_annotations(old_data)

        # Persist and cache
        _storage.save(project_path, new_graph.to_data())
        _graph = new_graph

        # Auto-version after sync
        _version_store.add_version(
            project_path, old_data, new_graph.to_data(), "Sync",
        )

        final_data = new_graph.to_data()
        new_node_count = len(final_data.nodes)
        new_edge_count = len(final_data.edges)

        return (
            f"Sync complete. "
            f"Nodes: {old_node_count} -> {new_node_count} "
            f"(delta {new_node_count - old_node_count:+d}). "
            f"Edges: {old_edge_count} -> {new_edge_count} "
            f"(delta {new_edge_count - old_edge_count:+d})."
        )
    except Exception as exc:
        return f"Error syncing graph: {exc}"


@mcp.tool()
def codegiraffe_export(
    project_path: str,
    format: str = "mermaid",
    direction: str = "TD",
    subgraph_by_type: bool = True,
    node_id: str | None = None,
    depth: int = 2,
) -> str:
    """Export the architecture graph as a visualization.

    Supported formats:
    - "mermaid": Mermaid flowchart diagram
    - "d3": D3.js-compatible JSON for force-directed graphs

    Optionally scope the export to a subgraph around a specific node.
    """
    try:
        graph = _ensure_graph(project_path)

        if node_id:
            data = graph.get_subgraph(node_id, depth=depth)
        else:
            data = graph.to_data()

        from codegiraffe.export import to_d3_json, to_mermaid

        if format.lower() == "mermaid":
            return to_mermaid(
                data, direction=direction, subgraph_by_type=subgraph_by_type
            )
        elif format.lower() == "d3":
            return to_d3_json(data)
        else:
            return f"Unsupported format: {format}. Use 'mermaid' or 'd3'."
    except Exception as exc:
        return f"Error exporting graph: {exc}"


# ---------------------------------------------------------------------------
# Multi-agent coordination tools
# ---------------------------------------------------------------------------


@mcp.tool()
def codegiraffe_claim(
    project_path: str,
    agent_id: str,
    node_ids: list[str],
    task: str,
    ttl: int = 1800,
) -> str:
    """Claim graph nodes for an agent to prevent conflicts during concurrent development.

    Before modifying nodes, agents should claim them. If another agent has already
    claimed overlapping nodes, the claim fails with conflict details.

    Claims automatically expire after `ttl` seconds (default 30 minutes).
    """
    try:
        result = _coordinator.claim(project_path, agent_id, node_ids, task, ttl)
        return json.dumps(result, indent=2)
    except Exception as exc:
        return f"Error claiming nodes: {exc}"


@mcp.tool()
def codegiraffe_status(
    project_path: str,
    agent_id: str,
    status: str,
    task: str | None = None,
) -> str:
    """Update an agent's status. Status can be 'active', 'done', or 'blocked'.

    Also refreshes the claim's TTL so it doesn't expire while the agent is
    actively working.
    """
    try:
        result = _coordinator.update_status(project_path, agent_id, status, task)
        return json.dumps(result, indent=2)
    except Exception as exc:
        return f"Error updating status: {exc}"


@mcp.tool()
def codegiraffe_agents(project_path: str) -> str:
    """List all active agents and their claimed nodes/status.

    Shows which agents are working on which parts of the architecture graph,
    enabling coordination and conflict avoidance.
    """
    try:
        agents = _coordinator.list_agents(project_path)
        if not agents:
            return "No active agents."
        return json.dumps(agents, indent=2)
    except Exception as exc:
        return f"Error listing agents: {exc}"


# ---------------------------------------------------------------------------
# Versioning tools
# ---------------------------------------------------------------------------


@mcp.tool()
def codegiraffe_history(project_path: str, limit: int = 20) -> str:
    """List version history for a project's architecture graph.

    Returns timestamped version entries with diff summaries showing what
    changed in each version (nodes/edges added/removed).
    """
    try:
        history = _version_store.get_history(project_path)
        return json.dumps(history[:limit], indent=2)
    except Exception as exc:
        return f"Error getting history: {exc}"


@mcp.tool()
def codegiraffe_diff(project_path: str, version_a: int, version_b: int | None = None) -> str:
    """Compare two versions of the architecture graph.

    If only *version_a* is given, returns the diff stored with that version
    (i.e. changes introduced by that version). When both *version_a* and
    *version_b* are given, computes a fresh diff between those two versions'
    graph snapshots using the stored diffs.

    Returns a detailed diff showing nodes/edges added, removed, and
    attributes changed.
    """
    try:
        if version_b is not None:
            va = _version_store.get_version(project_path, version_a)
            vb = _version_store.get_version(project_path, version_b)
            if va is None or vb is None:
                return "Error: version not found"
            # Return the diff from the later version
            later = vb if version_b > version_a else va
            return json.dumps(
                {"version_a": version_a, "version_b": version_b, "diff": later.diff.to_dict()},
                indent=2,
            )
        else:
            version = _version_store.get_version(project_path, version_a)
            if version is None:
                return "Error: version not found"
            return json.dumps(version.diff.to_dict(), indent=2)
    except Exception as exc:
        return f"Error computing diff: {exc}"


@mcp.tool()
def codegiraffe_snapshot(project_path: str, message: str = "Manual snapshot") -> str:
    """Create a named snapshot of the current architecture graph state.

    Use this to bookmark the graph state before making significant changes.
    The snapshot is stored in the version history with the given message.
    The diff recorded is empty since the snapshot captures the current state
    without any changes.
    """
    try:
        graph = _ensure_graph(project_path)
        current_data = graph.to_data()
        # Snapshot: diff against itself produces an empty diff
        version = _version_store.add_version(
            project_path, current_data, current_data, message,
        )
        return json.dumps(
            {"version_id": version.version_id, "message": message, "timestamp": version.timestamp},
            indent=2,
        )
    except Exception as exc:
        return f"Error creating snapshot: {exc}"


@mcp.tool()
def codegiraffe_restore(project_path: str, version_id: int) -> str:
    """Restore the architecture graph to a specific version.

    Warning: This operation is currently limited because only diffs (not
    full snapshots) are stored. A pre-restore backup snapshot is created
    automatically before attempting the restore.
    """
    try:
        # Snapshot current state before restore attempt
        graph = _ensure_graph(project_path)
        current_data = graph.to_data()
        _version_store.add_version(
            project_path, current_data, current_data,
            f"Pre-restore backup (before restoring to v{version_id})",
        )

        version = _version_store.get_version(project_path, version_id)
        if version is None:
            return f"Error: version {version_id} not found"

        return (
            "Error: restore requires full snapshot storage (not yet supported "
            "— only diffs are stored). A backup snapshot of the current state "
            "has been saved."
        )
    except Exception as exc:
        return f"Error restoring version: {exc}"


# ---------------------------------------------------------------------------
# Federation tools
# ---------------------------------------------------------------------------


@mcp.tool()
def codegiraffe_federate(project_paths: list[str]) -> str:
    """Register multiple repositories and build a unified federated graph.

    Each repository must have been initialized with ``codegiraffe_init``
    first. Returns a summary of the federated graph with namespace-isolated
    node IDs (prefixed with ``repo:{name}::``).
    """
    try:
        registered: list[str] = []
        errors: list[str] = []

        for path in project_paths:
            try:
                name = _federation.register_repo(path)
                registered.append(name)
            except FileNotFoundError as exc:
                errors.append(str(exc))

        if not registered:
            return json.dumps({"error": "No repos registered", "details": errors}, indent=2)

        unified = _federation.get_unified_graph()
        _federation.save_federation()

        result = {
            "registered_repos": registered,
            "total_nodes": len(unified.nodes),
            "total_edges": len(unified.edges),
        }
        if errors:
            result["errors"] = errors

        return json.dumps(result, indent=2)
    except Exception as exc:
        return f"Error federating graphs: {exc}"


@mcp.tool()
def codegiraffe_cross_query(node_id: str, depth: int = 2) -> str:
    """Query across all federated graphs for a specific node.

    The *node_id* must be a namespaced ID in the format
    ``repo:{name}::{node_id}``. Extracts a subgraph up to *depth* hops
    around that node, spanning across repository boundaries.
    """
    try:
        subgraph = _federation.query_federated(node_id, depth)
        return subgraph.model_dump_json(indent=2)
    except Exception as exc:
        return f"Error querying federated graph: {exc}"


@mcp.tool()
def codegiraffe_cross_edges() -> str:
    """List all edges that cross repository boundaries in the federation.

    An edge is considered cross-repo if its source and target belong to
    different repository namespaces. Useful for understanding inter-service
    dependencies.
    """
    try:
        cross_edges = _federation.get_cross_repo_edges()
        result = [
            {
                "source": edge.source,
                "target": edge.target,
                "type": edge.type,
                "metadata": edge.metadata,
            }
            for edge in cross_edges
        ]
        return json.dumps(result, indent=2)
    except Exception as exc:
        return f"Error getting cross-repo edges: {exc}"


# ---------------------------------------------------------------------------
# Neo4j tools
# ---------------------------------------------------------------------------


@mcp.tool()
def codegiraffe_cypher(project_path: str, query: str) -> str:
    """Run a read-only Cypher query against the Neo4j-stored architecture graph.

    Requires Neo4j storage backend and the ``neo4j`` Python driver.
    Connection is configured via environment variables ``NEO4J_URI``,
    ``NEO4J_USER``, and ``NEO4J_PASSWORD``.

    Returns query results as a JSON array of row objects.
    """
    try:
        from codegiraffe.neo4j_storage import Neo4jStorage

        if isinstance(_storage, Neo4jStorage):
            storage = _storage
        else:
            storage = Neo4jStorage()
        results = storage.run_cypher(query, project_path=project_path)
        return json.dumps(results, indent=2, default=str)
    except ImportError:
        return "Error: Neo4j driver not installed. Install with: pip install codegiraffe[neo4j]"
    except Exception as exc:
        return f"Error running Cypher query: {exc}"


# ---------------------------------------------------------------------------
# Web dashboard
# ---------------------------------------------------------------------------

from codegiraffe.dashboard import register_dashboard_routes

register_dashboard_routes(mcp, _ensure_graph, _storage)

# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    transport = "stdio"
    port = 8000
    for arg in sys.argv[1:]:
        if arg.startswith("--transport="):
            transport = arg.split("=", 1)[1]
        elif arg.startswith("--port="):
            port = int(arg.split("=", 1)[1])
        elif arg in ("--transport", "--port"):
            idx = sys.argv.index(arg)
            if idx + 1 < len(sys.argv):
                val = sys.argv[idx + 1]
                if arg == "--transport":
                    transport = val
                else:
                    port = int(val)

    if transport in ("sse", "streamable-http"):
        mcp.settings.port = port
    mcp.run(transport=transport)

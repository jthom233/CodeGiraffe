"""Web dashboard for Code Giraffe architecture graphs.

Serves a single-page Sigma.js v3-based visualization of the architecture
knowledge graph.  All HTML, CSS, and JavaScript are embedded in this module
--- no external files are needed.

Usage::

    from codegiraffe.dashboard import register_dashboard_routes
    register_dashboard_routes(mcp, _ensure_graph, _storage)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from codegiraffe.export import to_d3_json
from codegiraffe.graph import ArchGraph, GraphData

# ---------------------------------------------------------------------------
# Logo helpers
# ---------------------------------------------------------------------------

_logo_cache: bytes | None = None
_logo_cache_loaded: bool = False


def _load_logo_bytes() -> bytes | None:
    global _logo_cache, _logo_cache_loaded
    if _logo_cache_loaded:
        return _logo_cache
    logo_path = Path(__file__).parent / "assets" / "logo.png"
    if logo_path.exists():
        _logo_cache = logo_path.read_bytes()
    _logo_cache_loaded = True
    return _logo_cache


# ---------------------------------------------------------------------------
# Pure data-fetching functions (testable without HTTP)
# ---------------------------------------------------------------------------


def get_graph_json(
    ensure_graph_fn: Callable[[str], ArchGraph],
    project_path: str,
    max_nodes: int = 500,
    path_prefix: str = "",
    node_types: list[str] | None = None,
) -> dict:
    """Return graph data as a D3-style JSON dict.

    Parameters
    ----------
    ensure_graph_fn:
        Callable that loads/returns an ``ArchGraph`` for the given project path.
    project_path:
        Filesystem path to the project root.
    max_nodes:
        Maximum number of nodes to include in the response. When the filtered
        graph exceeds this limit the top nodes by degree centrality (hotspots)
        are kept. Pass ``0`` to disable truncation entirely.
    path_prefix:
        When non-empty, only nodes whose ``file_path`` starts with this string
        are included. Nodes with no ``file_path`` are excluded when a prefix is
        specified.
    node_types:
        When non-None and non-empty, only nodes whose ``type`` is in this list
        are included. ``None`` or ``[]`` means no type filtering.

    Raises ``RuntimeError`` when the project has not been initialized.
    """
    graph = ensure_graph_fn(project_path)
    data = graph.to_data()
    total_nodes = len(data.nodes)
    total_edges = len(data.edges)
    truncated = False

    # --- Step 1: Apply server-side filters ---
    filtered = False
    filtered_nodes = dict(data.nodes)

    if path_prefix:
        filtered_nodes = {
            nid: node
            for nid, node in filtered_nodes.items()
            if node.file_path and node.file_path.startswith(path_prefix)
        }
        filtered = True

    if node_types:
        type_set = set(node_types)
        filtered_nodes = {
            nid: node
            for nid, node in filtered_nodes.items()
            if node.type in type_set
        }
        filtered = True

    if filtered:
        kept_ids: set[str] = set(filtered_nodes)
        filtered_edges = [
            e for e in data.edges
            if e.source in kept_ids and e.target in kept_ids
        ]
        data = GraphData(
            nodes=filtered_nodes,
            edges=filtered_edges,
            project_path=data.project_path,
            last_scan=data.last_scan,
            schema_version=data.schema_version,
        )

    # --- Step 2: Apply max_nodes truncation on the (already-filtered) data ---
    if max_nodes > 0 and len(data.nodes) > max_nodes:
        temp_graph = ArchGraph(data)
        hotspots = temp_graph.get_hotspots(top_n=max_nodes)
        kept_ids = {node.id for node, _score in hotspots}
        trunc_nodes = {nid: node for nid, node in data.nodes.items() if nid in kept_ids}
        trunc_edges = [e for e in data.edges if e.source in kept_ids and e.target in kept_ids]
        data = GraphData(
            nodes=trunc_nodes,
            edges=trunc_edges,
            project_path=data.project_path,
            last_scan=data.last_scan,
            schema_version=data.schema_version,
        )
        truncated = True

    result = json.loads(to_d3_json(data))
    result["truncated"] = truncated
    if truncated:
        result["total_nodes"] = total_nodes
        result["total_edges"] = total_edges
    result["unfiltered_total_nodes"] = total_nodes
    result["unfiltered_total_edges"] = total_edges

    return result


def get_node_detail(
    ensure_graph_fn: Callable[[str], ArchGraph],
    project_path: str,
    node_id: str,
) -> dict:
    """Return detailed information about a single node and its connected edges."""
    graph = ensure_graph_fn(project_path)
    data = graph.to_data()

    node = data.nodes.get(node_id)
    if node is None:
        return {"error": f"Node '{node_id}' not found"}

    incoming = []
    outgoing = []
    for edge in data.edges:
        if edge.target == node_id:
            incoming.append({
                "source": edge.source,
                "target": edge.target,
                "type": edge.type,
                "metadata": edge.metadata,
            })
        if edge.source == node_id:
            outgoing.append({
                "source": edge.source,
                "target": edge.target,
                "type": edge.type,
                "metadata": edge.metadata,
            })

    return {
        "id": node.id,
        "type": node.type,
        "label": node.label,
        "file_path": node.file_path,
        "manual": node.manual,
        "metadata": node.metadata,
        "incoming_edges": incoming,
        "outgoing_edges": outgoing,
    }


def get_subgraph_json(
    ensure_graph_fn: Callable[[str], ArchGraph],
    project_path: str,
    node_id: str,
    depth: int = 2,
) -> dict:
    """Return subgraph data centered on *node_id* up to *depth* hops."""
    graph = ensure_graph_fn(project_path)
    subgraph_data = graph.get_subgraph(node_id, depth=depth)
    return json.loads(to_d3_json(subgraph_data))


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

DASHBOARD_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Code Giraffe - Architecture Dashboard</title>
<link rel="icon" type="image/png" href="/api/logo">
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, sans-serif;
  background: #1a1a2e; color: #e0e0e0; overflow: hidden; height: 100vh;
}

/* ---- Layout ---- */
#app { display: flex; height: 100vh; width: 100vw; }
#sidebar {
  width: 280px; min-width: 280px; background: #16213e; border-right: 1px solid #0f3460;
  display: flex; flex-direction: column; transition: margin-left 0.25s ease;
  overflow-y: auto; z-index: 10;
}
#sidebar.collapsed { margin-left: -280px; }
#toggle-sidebar {
  position: fixed; top: 12px; left: 12px; z-index: 20; background: #0f3460;
  color: #e0e0e0; border: none; border-radius: 4px; padding: 6px 10px;
  cursor: pointer; font-size: 14px;
}
#toggle-sidebar:hover { background: #1a4a7a; }
#cy-container { flex: 1; position: relative; }
#cy { width: 100%; height: 100%; background: #12122a; }

/* ---- Sidebar sections ---- */
.sidebar-section { padding: 14px 16px; border-bottom: 1px solid #0f3460; }
.sidebar-section h3 {
  font-size: 11px; text-transform: uppercase; letter-spacing: 1px;
  color: #7f8c9b; margin-bottom: 8px;
}
.sidebar-section input[type="text"] {
  width: 100%; padding: 7px 10px; background: #0d1b36; border: 1px solid #0f3460;
  border-radius: 4px; color: #e0e0e0; font-size: 13px; outline: none;
}
.sidebar-section input[type="text"]:focus { border-color: #4A90D9; }
.sidebar-section input[type="text"]::placeholder { color: #556; }
#load-btn {
  margin-top: 6px; width: 100%; padding: 7px; background: #4A90D9; color: #fff;
  border: none; border-radius: 4px; cursor: pointer; font-size: 13px;
}
#load-btn:hover { background: #5ba0e9; }
#load-btn:disabled { opacity: 0.5; cursor: not-allowed; }
#filters { display: flex; flex-direction: column; gap: 4px; }
#filters label {
  display: flex; align-items: center; gap: 6px; font-size: 13px; cursor: pointer;
}
#filters input[type="checkbox"] { accent-color: #4A90D9; }
.stat-row { display: flex; justify-content: space-between; font-size: 13px; padding: 2px 0; }
.stat-val { color: #4A90D9; font-weight: 600; }
#error-msg { color: #E74C3C; font-size: 12px; margin-top: 6px; display: none; }

/* ---- Toolbar ---- */
#toolbar {
  position: absolute; bottom: 16px; left: 50%; transform: translateX(-50%);
  display: flex; gap: 6px; z-index: 5;
}
#toolbar button {
  background: #16213e; color: #e0e0e0; border: 1px solid #0f3460; border-radius: 4px;
  padding: 6px 14px; cursor: pointer; font-size: 12px;
}
#toolbar button:hover { background: #0f3460; }

/* ---- Detail panel ---- */
#detail-panel {
  position: fixed; top: 0; right: -380px; width: 380px; height: 100vh;
  background: #16213e; border-left: 1px solid #0f3460; z-index: 15;
  transition: right 0.25s ease; overflow-y: auto; padding: 0;
}
#detail-panel.open { right: 0; }
#detail-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 14px 16px; border-bottom: 1px solid #0f3460; position: sticky;
  top: 0; background: #16213e;
}
#detail-header h2 { font-size: 15px; font-weight: 600; }
#close-detail {
  background: none; border: none; color: #7f8c9b; font-size: 20px;
  cursor: pointer; line-height: 1;
}
#close-detail:hover { color: #e0e0e0; }
#detail-body { padding: 14px 16px; }
.detail-field { margin-bottom: 10px; }
.detail-field .label {
  font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px;
  color: #7f8c9b; margin-bottom: 2px;
}
.detail-field .value { font-size: 13px; word-break: break-all; }
.edge-list { list-style: none; }
.edge-list li {
  padding: 4px 0; font-size: 12px; border-bottom: 1px solid #0f346033;
}
.edge-type { color: #4A90D9; font-weight: 500; }

/* ---- Loading overlay ---- */
#loading {
  position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
  color: #7f8c9b; font-size: 14px; display: none;
}

/* ---- Legend ---- */
#legend .legend-item { display: flex; align-items: center; gap: 6px; font-size: 12px; padding: 2px 0; }
#legend .legend-swatch { width: 12px; height: 12px; border-radius: 3px; flex-shrink: 0; }
#legend .legend-line { width: 20px; height: 0; border-top: 2px solid; flex-shrink: 0; }
#legend .legend-line.dashed { border-top-style: dashed; }
#legend .legend-line.dotted { border-top-style: dotted; }
#legend .legend-divider { border-top: 1px solid #0f3460; margin: 6px 0; }

/* ---- Type distribution ---- */
#type-distribution { margin-top: 8px; }
.dist-row { display: flex; align-items: center; gap: 6px; font-size: 11px; padding: 2px 0; }
.dist-bar { height: 8px; border-radius: 2px; min-width: 2px; }
.dist-label { width: 90px; text-align: right; color: #7f8c9b; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dist-count { color: #7f8c9b; min-width: 20px; }

/* ---- Server filter controls ---- */
.filter-row { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
.filter-row label { font-size: 12px; color: #7f8c9b; white-space: nowrap; min-width: 70px; }
.filter-row input[type="number"] {
  flex: 1; padding: 7px 10px; background: #0d1b36; border: 1px solid #0f3460;
  border-radius: 4px; color: #e0e0e0; font-size: 13px; outline: none;
}
.filter-row input[type="number"]:focus { border-color: #4A90D9; }
#apply-server-filters {
  width: 100%; padding: 7px; background: #0f3460; color: #e0e0e0;
  border: none; border-radius: 4px; cursor: pointer; font-size: 13px;
}
#apply-server-filters:hover { background: #1a4a7a; }
#truncation-banner { font-size: 11px; color: #F39C12; margin-top: 6px; display: none; }

/* ---- Highlighted edge style ---- */
.highlighted-edge { stroke: #F1C40F !important; stroke-width: 3px !important; }

/* ---- Logo ---- */
#sidebar-logo { border-radius: 4px; opacity: 0.95; }
#sidebar-logo:hover { opacity: 1; }
</style>
</head>
<body>
<div id="app">
  <button id="toggle-sidebar" title="Toggle sidebar">&#9776;</button>
  <div id="sidebar">
    <div class="sidebar-section" style="text-align:center; padding:16px 16px 8px;">
      <img src="/api/logo" alt="Code Giraffe" style="max-width:160px; height:auto;" id="sidebar-logo" />
    </div>
    <div class="sidebar-section">
      <h3>Project</h3>
      <input type="text" id="project-path" placeholder="/path/to/project" />
      <button id="load-btn">Load Graph</button>
      <div id="error-msg"></div>
    </div>
    <div class="sidebar-section">
      <h3>Filters</h3>
      <div class="filter-row">
        <label for="path-prefix-input">Path prefix</label>
        <input type="text" id="path-prefix-input" placeholder="src/auth/" style="flex:1;padding:7px 10px;background:#0d1b36;border:1px solid #0f3460;border-radius:4px;color:#e0e0e0;font-size:13px;outline:none;" />
      </div>
      <div class="filter-row">
        <label for="max-nodes-input">Max nodes</label>
        <input type="number" id="max-nodes-input" value="500" min="0" step="100" title="0 = no limit (may be slow)" />
      </div>
      <button id="apply-server-filters">Apply &amp; Reload</button>
      <div id="truncation-banner"></div>
    </div>
    <div class="sidebar-section">
      <h3>Search</h3>
      <input type="text" id="search-box" placeholder="Filter nodes..." disabled />
    </div>
    <div class="sidebar-section">
      <h3>Node Types</h3>
      <div id="filters"></div>
    </div>
    <div class="sidebar-section">
      <h3>Stats</h3>
      <div class="stat-row"><span>Nodes</span><span class="stat-val" id="stat-nodes">0</span></div>
      <div class="stat-row"><span>Edges</span><span class="stat-val" id="stat-edges">0</span></div>
      <div class="stat-row"><span>Visible</span><span class="stat-val" id="stat-visible">0</span></div>
      <div class="stat-row"><span>Avg Degree</span><span class="stat-val" id="stat-avg-degree">0</span></div>
      <div class="stat-row"><span>Components</span><span class="stat-val" id="stat-components">0</span></div>
      <div id="type-distribution"></div>
    </div>
    <div class="sidebar-section" id="legend-section">
      <h3>Legend</h3>
      <div id="legend"></div>
    </div>
  </div>
  <div id="cy-container">
    <div id="cy"></div>
    <div id="edge-tooltip" style="display:none;position:absolute;z-index:10;background:#16213e;border:1px solid #0f3460;border-radius:4px;padding:6px 10px;font-size:12px;color:#e0e0e0;pointer-events:none;white-space:nowrap;"></div>
    <div id="loading">Loading graph...</div>
    <div id="toolbar">
      <button id="btn-fit" title="Fit all nodes">Fit</button>
      <button id="btn-layout" title="Cycle layout">Layout</button>
      <button id="btn-export" title="Export as PNG">PNG</button>
    </div>
  </div>
</div>

<div id="detail-panel">
  <div id="detail-header">
    <h2 id="detail-title">Node Detail</h2>
    <button id="close-detail">&times;</button>
  </div>
  <div id="detail-body"></div>
</div>

<script src="https://cdn.jsdelivr.net/npm/graphology@0.26.0/dist/graphology.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/sigma@3.0.2/dist/sigma.min.js"></script>
<script>
(function() {
  'use strict';

  // ---- State ----
  let sigmaInstance = null;
  let graphologyGraph = null;
  let allNodeData = new Map();
  let currentProjectPath = '';
  let hasPrecomputedLayout = false;
  let activeTypes = new Set();
  let currentLayoutIdx = 0;

  // ---- Layout names (kept for UI cycling) ----
  const LAYOUTS = ['original', 'force', 'circular', 'grid', 'concentric', 'breadthfirst', 'random'];

  // ---- Color palettes ----
  const TYPE_COLORS = {
    service: '#4A90D9', endpoint: '#7B68EE', database_table: '#2ECC71',
    queue: '#E67E22', env_var: '#F39C12', config: '#D4AC0D',
    worker: '#E74C3C', frontend_component: '#9B59B6', event: '#1ABC9C',
    external_api: '#95A5A6', module: '#D35400', contract: '#8E44AD',
    decision: '#2196F3', domain: '#f0f0f0', default: '#4A90D9'
  };

  const EDGE_COLORS = {
    calls: '#3498DB', imports: '#E67E22', contains: '#2ECC71',
    implements: '#9B59B6', produces: '#8E44AD', consumes_contract: '#9B59B6',
    validates: '#27AE60', violates: '#E74C3C', depends_on: '#7af74e',
    uses: '#4ef7f7', belongs_to: '#f76a4e', constrains: '#2196F3',
    supersedes: '#9E9E9E', reads: '#5DADE2', writes: '#E74C3C',
    publishes: '#F39C12', consumes: '#1ABC9C', configures: '#D4AC0D',
    owns: '#BDC3C7', triggers: '#E91E63',
    cross_repo_depends_on: '#FF6B6B', cross_repo_calls: '#FF9F43',
    cross_repo_publishes: '#FECA57', cross_repo_consumes: '#54A0FF',
    motivated_by: '#A29BFE', tested_by: '#00D2D3',
    default: '#2a3a5e'
  };

  const DEFAULT_COLOR = '#4A90D9';

  // ---- DOM refs ----
  const $path = document.getElementById('project-path');
  const $loadBtn = document.getElementById('load-btn');
  const $search = document.getElementById('search-box');
  const $filters = document.getElementById('filters');
  const $errorMsg = document.getElementById('error-msg');
  const $loading = document.getElementById('loading');
  const $pathPrefix = document.getElementById('path-prefix-input');
  const $maxNodes = document.getElementById('max-nodes-input');
  const $truncationBanner = document.getElementById('truncation-banner');
  const $detailPanel = document.getElementById('detail-panel');
  const $detailTitle = document.getElementById('detail-title');
  const $detailBody = document.getElementById('detail-body');

  // ---- Helpers ----
  function escapeHtml(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function truncateStr(s, n) { return s && s.length > n ? s.slice(0, n) + '...' : s; }

  function showError(msg) {
    $errorMsg.textContent = msg; $errorMsg.style.display = 'block';
    setTimeout(function() { $errorMsg.style.display = 'none'; }, 5000);
  }

  // ---- Node/edge reducers for Sigma ----
  const nodeReducer = function(node, data) {
    var res = Object.assign({}, data);
    res.color = TYPE_COLORS[data.nodeType] || TYPE_COLORS.default;
    if (data.hidden) { res.hidden = true; }
    return res;
  };

  const edgeReducer = function(edge, data) {
    var res = Object.assign({}, data);
    res.color = EDGE_COLORS[data.edgeType] || EDGE_COLORS.default;
    res.size = 1.5;
    if (data.highlighted) { res.color = '#F1C40F'; res.size = 3; }
    if (data.hidden) { res.hidden = true; }
    return res;
  };

  // ---- Convert D3/API response to graphology graph ----
  function d3ToGraphology(apiResponse) {
    var g = new graphology.Graph({ multi: false, allowSelfLoops: true, type: 'directed' });
    hasPrecomputedLayout = (apiResponse.nodes || []).some(function(n) { return n.x !== undefined; });
    allNodeData = new Map();

    (apiResponse.nodes || []).forEach(function(node) {
      var attrs = {
        label: node.label || node.id,
        nodeType: node.type,
        group: node.group,
        file_path: node.file_path,
        manual: node.manual,
        metadata: node.metadata,
        x: node.x !== undefined ? node.x : (Math.random() * 2 - 1),
        y: node.y !== undefined ? node.y : (Math.random() * 2 - 1),
        size: 5,
        hidden: false
      };
      g.addNode(node.id, attrs);
      allNodeData.set(node.id, Object.assign({ id: node.id }, attrs));
    });

    (apiResponse.links || []).forEach(function(link) {
      if (!g.hasNode(link.source) || !g.hasNode(link.target)) { return; }
      try {
        g.addEdge(link.source, link.target, {
          edgeType: link.type,
          manual: link.manual,
          confidence: link.confidence !== undefined ? link.confidence : 1.0,
          metadata: link.metadata,
          hidden: false,
          highlighted: false
        });
      } catch(e) { /* skip duplicate edges */ }
    });

    return g;
  }

  // ---- Sigma init ----
  function initSigma(graph) {
    if (sigmaInstance) {
      sigmaInstance.kill();
      sigmaInstance = null;
    }
    graphologyGraph = graph;

    // Size nodes by degree
    graph.nodes().forEach(function(id) {
      graph.setNodeAttribute(id, 'size', Math.min(12, Math.max(3, 3 + graph.degree(id) * 0.5)));
    });

    sigmaInstance = new Sigma(graph, document.getElementById('cy'), {
      nodeReducer: nodeReducer,
      edgeReducer: edgeReducer,
      renderEdgeLabels: false,
      labelFont: 'monospace',
      labelSize: 12,
      labelColor: { color: '#d0d0d0' },
      labelRenderedSizeThreshold: 8,
      defaultDrawNodeHover: function(context, data, settings) {
        var size = data.size || 5;
        var label = data.label || '';
        var x = data.x;
        var y = data.y;
        // Draw hover ring
        context.beginPath();
        context.arc(x, y, size + 3, 0, Math.PI * 2);
        context.closePath();
        context.lineWidth = 2;
        context.strokeStyle = '#F1C40F';
        context.stroke();
        // Draw label background
        if (label) {
          context.font = (settings.labelFont || 'monospace') + ' ' + (settings.labelSize || 12) + 'px ' + (settings.labelFont || 'monospace');
          context.font = '12px monospace';
          var textWidth = context.measureText(label).width;
          var bgX = x + size + 4;
          var bgY = y - 8;
          var padding = 4;
          context.fillStyle = 'rgba(30, 30, 46, 0.9)';
          context.beginPath();
          context.roundRect(bgX - padding, bgY - padding, textWidth + padding * 2, 18 + padding, 4);
          context.fill();
          // Draw label text
          context.fillStyle = '#e0e0e0';
          context.fillText(label, bgX, bgY + 12);
        }
      }
    });

    // ---- Event: clickNode ----
    sigmaInstance.on('clickNode', function(event) {
      var node = event.node;
      var attrs = graphologyGraph.getNodeAttributes(node);
      showDetailPanel(node, attrs);

      // Highlight connected edges
      graphologyGraph.edges().forEach(function(edge) {
        var src = graphologyGraph.source(edge);
        var tgt = graphologyGraph.target(edge);
        graphologyGraph.setEdgeAttribute(edge, 'highlighted', src === node || tgt === node);
      });
      sigmaInstance.refresh();
    });

    // ---- Event: clickStage (deselect) ----
    sigmaInstance.on('clickStage', function() {
      closeDetail();
      graphologyGraph.edges().forEach(function(edge) {
        graphologyGraph.setEdgeAttribute(edge, 'highlighted', false);
      });
      sigmaInstance.refresh();
    });

    // ---- Event: enterEdge ----
    sigmaInstance.on('enterEdge', function(event) {
      var edge = event.edge;
      var attrs = graphologyGraph.getEdgeAttributes(edge);
      showEdgeTooltip(edge, attrs);
    });

    // ---- Event: leaveEdge ----
    sigmaInstance.on('leaveEdge', function() {
      hideEdgeTooltip();
    });

    updateStats();
  }

  // ---- Detail panel ----
  function showDetailPanel(nodeId, attrs) {
    $detailTitle.textContent = attrs.label || nodeId;
    var html = '';
    var fields = [
      ['ID', nodeId],
      ['Type', attrs.nodeType || 'unknown'],
      ['Label', attrs.label || nodeId],
      ['File Path', attrs.file_path || '\\u2014'],
      ['Manual', attrs.manual ? 'Yes' : 'No']
    ];
    fields.forEach(function(pair) {
      html += '<div class="detail-field"><div class="label">' + pair[0] + '</div><div class="value">' + escapeHtml(String(pair[1])) + '</div></div>';
    });
    if (attrs.metadata && Object.keys(attrs.metadata).length > 0) {
      html += '<div class="detail-field"><div class="label">Metadata</div><div class="value"><pre style="font-size:11px;white-space:pre-wrap;color:#9ab;">' + escapeHtml(JSON.stringify(attrs.metadata, null, 2)) + '</pre></div></div>';
    }

    if (graphologyGraph) {
      var inEdges = graphologyGraph.inEdges(nodeId);
      var outEdges = graphologyGraph.outEdges(nodeId);
      if (inEdges.length > 0) {
        html += '<div class="detail-field"><div class="label">Incoming Edges (' + inEdges.length + ')</div><ul class="edge-list">';
        inEdges.forEach(function(edge) {
          var eAttrs = graphologyGraph.getEdgeAttributes(edge);
          var src = graphologyGraph.source(edge);
          html += '<li><span class="edge-type">' + escapeHtml(eAttrs.edgeType || '') + '</span> from ' + escapeHtml(src) + '</li>';
        });
        html += '</ul></div>';
      }
      if (outEdges.length > 0) {
        html += '<div class="detail-field"><div class="label">Outgoing Edges (' + outEdges.length + ')</div><ul class="edge-list">';
        outEdges.forEach(function(edge) {
          var eAttrs = graphologyGraph.getEdgeAttributes(edge);
          var tgt = graphologyGraph.target(edge);
          html += '<li><span class="edge-type">' + escapeHtml(eAttrs.edgeType || '') + '</span> to ' + escapeHtml(tgt) + '</li>';
        });
        html += '</ul></div>';
      }
    }

    $detailBody.innerHTML = html;
    $detailPanel.classList.add('open');
  }

  function closeDetail() { $detailPanel.classList.remove('open'); }

  // ---- Edge tooltip ----
  function showEdgeTooltip(edgeId, attrs) {
    var tip = document.getElementById('edge-tooltip');
    var src = graphologyGraph ? graphologyGraph.source(edgeId) : '';
    var tgt = graphologyGraph ? graphologyGraph.target(edgeId) : '';
    var conf = attrs.confidence !== undefined ? (' (conf: ' + attrs.confidence.toFixed(2) + ')') : '';
    tip.textContent = (attrs.edgeType || 'edge') + ': ' + src + ' \\u2192 ' + tgt + conf;
    tip.style.display = 'block';
    // mouseover position is not directly available; position near center of container
    var cont = document.getElementById('cy-container');
    var rect = cont ? cont.getBoundingClientRect() : { width: 400, height: 300 };
    tip.style.left = '20px';
    tip.style.top = '20px';
  }

  function hideEdgeTooltip() {
    document.getElementById('edge-tooltip').style.display = 'none';
  }

  // ---- Search ----
  var searchTimer = null;
  $search.addEventListener('input', function() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(function() { applyClientFilters(); }, 300);
  });

  function applyClientFilters() {
    if (!graphologyGraph || !sigmaInstance) { return; }
    var query = $search.value.trim().toLowerCase();
    activeTypes.clear();
    document.querySelectorAll('#filters input[type=checkbox]').forEach(function(cb) {
      if (cb.checked) { activeTypes.add(cb.value); }
    });

    graphologyGraph.nodes().forEach(function(id) {
      var attrs = graphologyGraph.getNodeAttributes(id);
      var typeOk = activeTypes.size === 0 || activeTypes.has(attrs.nodeType || 'unknown');
      var searchOk = !query || (attrs.label || id).toLowerCase().indexOf(query) !== -1 || id.toLowerCase().indexOf(query) !== -1;
      graphologyGraph.setNodeAttribute(id, 'hidden', !(typeOk && searchOk));
    });

    // Hide edges where either endpoint is hidden
    graphologyGraph.edges().forEach(function(edge) {
      var src = graphologyGraph.source(edge);
      var tgt = graphologyGraph.target(edge);
      var srcHidden = graphologyGraph.getNodeAttribute(src, 'hidden');
      var tgtHidden = graphologyGraph.getNodeAttribute(tgt, 'hidden');
      graphologyGraph.setEdgeAttribute(edge, 'hidden', srcHidden || tgtHidden);
    });

    sigmaInstance.refresh();
    updateStats();
  }

  // ---- Stats ----
  function updateStats() {
    if (!graphologyGraph) { return; }
    var totalNodes = graphologyGraph.order;
    var totalEdges = graphologyGraph.size;
    var visNodes = 0;
    graphologyGraph.nodes().forEach(function(id) {
      if (!graphologyGraph.getNodeAttribute(id, 'hidden')) { visNodes++; }
    });
    document.getElementById('stat-nodes').textContent = totalNodes;
    document.getElementById('stat-edges').textContent = totalEdges;
    document.getElementById('stat-visible').textContent = visNodes;

    var avgDeg = totalNodes > 0 ? (2 * totalEdges / totalNodes).toFixed(1) : '0';
    document.getElementById('stat-avg-degree').textContent = avgDeg;

    // Connected components (simple BFS ignoring hidden)
    var visited = new Set();
    var components = 0;
    graphologyGraph.nodes().forEach(function(startId) {
      if (visited.has(startId)) { return; }
      components++;
      var queue = [startId];
      while (queue.length > 0) {
        var cur = queue.shift();
        if (visited.has(cur)) { continue; }
        visited.add(cur);
        graphologyGraph.neighbors(cur).forEach(function(nb) {
          if (!visited.has(nb)) { queue.push(nb); }
        });
      }
    });
    document.getElementById('stat-components').textContent = components;

    // Type distribution
    var typeCounts = {};
    graphologyGraph.nodes().forEach(function(id) {
      var t = graphologyGraph.getNodeAttribute(id, 'nodeType') || 'unknown';
      typeCounts[t] = (typeCounts[t] || 0) + 1;
    });
    var maxCount = Math.max.apply(null, Object.values(typeCounts).concat([1]));
    var $dist = document.getElementById('type-distribution');
    if ($dist) {
      var html = '';
      Object.keys(typeCounts).sort().forEach(function(t) {
        var pct = (typeCounts[t] / maxCount) * 100;
        var color = TYPE_COLORS[t] || DEFAULT_COLOR;
        html += '<div class="dist-row"><span class="dist-label">' + t + '</span><span class="dist-bar" style="width:' + pct + '%;background:' + color + '"></span><span class="dist-count">' + typeCounts[t] + '</span></div>';
      });
      $dist.innerHTML = html;
    }
  }

  // ---- Legend ----
  function buildLegend() {
    var $legend = document.getElementById('legend');
    if (!$legend) { return; }
    var html = '';
    Object.keys(TYPE_COLORS).sort().forEach(function(t) {
      html += '<div class="legend-item"><span class="legend-swatch" style="background:' + TYPE_COLORS[t] + '"></span>' + t + '</div>';
    });
    html += '<div class="legend-divider"></div>';
    var edgeStyles = {
      imports: { color: '#E67E22', style: 'dashed' },
      implements: { color: '#9B59B6', style: '' },
      calls: { color: '#3498DB', style: '' },
      contains: { color: '#2ECC71', style: 'dotted' },
      produces: { color: '#8E44AD', style: '' },
      consumes_contract: { color: '#9B59B6', style: 'dashed' },
      validates: { color: '#27AE60', style: 'dotted' },
      violates: { color: '#E74C3C', style: '' },
      depends_on: { color: '#7af74e', style: '' },
      uses: { color: '#4ef7f7', style: '' },
      belongs_to: { color: '#f76a4e', style: 'dotted' },
      constrains: { color: '#2196F3', style: 'dotted' },
      supersedes: { color: '#9E9E9E', style: 'dashed' },
      reads: { color: '#5DADE2', style: '' },
      writes: { color: '#E74C3C', style: '' },
      publishes: { color: '#F39C12', style: 'dashed' },
      consumes: { color: '#1ABC9C', style: 'dashed' },
      configures: { color: '#D4AC0D', style: 'dotted' },
      owns: { color: '#BDC3C7', style: 'dotted' },
      triggers: { color: '#E91E63', style: '' },
      cross_repo_depends_on: { color: '#FF6B6B', style: 'dashed' },
      cross_repo_calls: { color: '#FF9F43', style: 'dashed' },
      cross_repo_publishes: { color: '#FECA57', style: 'dashed' },
      cross_repo_consumes: { color: '#54A0FF', style: 'dashed' },
      motivated_by: { color: '#A29BFE', style: 'dotted' },
      tested_by: { color: '#00D2D3', style: 'dotted' },
      default: { color: '#2a3a5e', style: '' }
    };
    Object.keys(edgeStyles).forEach(function(t) {
      var s = edgeStyles[t];
      html += '<div class="legend-item"><span class="legend-line ' + s.style + '" style="border-color:' + s.color + '"></span>' + t + '</div>';
    });
    $legend.innerHTML = html;
  }

  // ---- Node type client filters ----
  function buildFilters(nodes) {
    var types = new Set((nodes || []).map(function(n) { return n.type || 'unknown'; }));
    activeTypes = new Set(types);
    $filters.innerHTML = '';
    Array.from(types).sort().forEach(function(t) {
      var lbl = document.createElement('label');
      var cb = document.createElement('input');
      cb.type = 'checkbox'; cb.checked = true; cb.value = t;
      cb.addEventListener('change', applyClientFilters);
      var colorDot = document.createElement('span');
      colorDot.style.cssText = 'display:inline-block;width:10px;height:10px;border-radius:50%;background:' + (TYPE_COLORS[t] || DEFAULT_COLOR);
      lbl.appendChild(cb); lbl.appendChild(colorDot);
      lbl.appendChild(document.createTextNode(' ' + t));
      $filters.appendChild(lbl);
    });
  }

  // ---- Load graph ----
  async function loadGraph() {
    var path = $path.value.trim();
    if (!path) { showError('Enter a project path'); return; }
    currentProjectPath = path;
    $loadBtn.disabled = true;
    $loading.style.display = 'block';
    $loading.textContent = 'Loading graph...';
    $errorMsg.style.display = 'none';

    var maxNodes = parseInt($maxNodes.value, 10);
    if (!isNaN(maxNodes) && maxNodes > 2000) {
      if (!confirm('Loading ' + maxNodes + ' nodes may be slow. Continue?')) {
        $loadBtn.disabled = false;
        return;
      }
    }
    var pathPrefix = $pathPrefix.value.trim();

    var apiUrl = '/api/graph?project_path=' + encodeURIComponent(path);
    apiUrl += '&max_nodes=' + (isNaN(maxNodes) ? 500 : maxNodes);
    if (pathPrefix) { apiUrl += '&path_prefix=' + encodeURIComponent(pathPrefix); }

    try {
      var resp = await fetch(apiUrl);
      if (resp.status === 404) {
        $loading.textContent = 'Scanning project...';
        var initResp = await fetch('/api/init', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({project_path: path})
        });
        if (!initResp.ok) {
          var initErr = await initResp.json().catch(function() { return {}; });
          throw new Error(initErr.error || 'Failed to initialize project');
        }
        $loading.textContent = 'Loading...';
        resp = await fetch(apiUrl);
      }
      if (!resp.ok) {
        var errData = await resp.json().catch(function() { return {}; });
        throw new Error(errData.error || resp.statusText);
      }
      var d3Data = await resp.json();

      // Show truncation/filter banner
      var shownNodes = (d3Data.nodes || []).length;
      var totalNodes = d3Data.unfiltered_total_nodes || shownNodes;
      if (d3Data.truncated) {
        $truncationBanner.textContent = 'Top ' + shownNodes + ' hotspot nodes of ' + d3Data.total_nodes +
          (d3Data.total_nodes !== totalNodes ? ' filtered (' + totalNodes + ' total)' : ' total');
        $truncationBanner.style.display = 'block';
      } else if (shownNodes < totalNodes) {
        $truncationBanner.textContent = 'Showing ' + shownNodes + ' of ' + totalNodes + ' total nodes (filtered)';
        $truncationBanner.style.display = 'block';
      } else {
        $truncationBanner.style.display = 'none';
      }

      var graph = d3ToGraphology(d3Data);
      buildFilters(d3Data.nodes || []);
      $search.disabled = false;
      $search.value = '';
      initSigma(graph);
      buildLegend();
    } catch(e) {
      showError(e.message);
    } finally {
      $loadBtn.disabled = false;
      $loading.style.display = 'none';
      $loading.textContent = 'Loading graph...';
    }
  }

  // ---- Layout functions ----
  function applyLayoutAndReset(fn) {
    fn();
    sigmaInstance.refresh();
    setTimeout(function() { sigmaInstance.getCamera().animatedReset(); }, 50);
  }

  function applyForceLayout() {
    // Component-aware spring layout — O(n + edges), instant for any graph size
    var nodeIds = graphologyGraph.nodes();
    var n = nodeIds.length;
    if (n === 0) return;

    // 1. Find connected components via BFS
    var visited = new Set();
    var components = [];
    nodeIds.forEach(function(startId) {
      if (visited.has(startId)) return;
      var comp = [];
      var queue = [startId];
      visited.add(startId);
      while (queue.length > 0) {
        var id = queue.shift();
        comp.push(id);
        graphologyGraph.neighbors(id).forEach(function(nb) {
          if (!visited.has(nb)) { visited.add(nb); queue.push(nb); }
        });
      }
      components.push(comp);
    });

    // 2. Sort components largest-first
    components.sort(function(a, b) { return b.length - a.length; });

    // 3. Lay out each component in a circle, then place components in a grid
    var pos = {};
    var compCols = Math.ceil(Math.sqrt(components.length));
    var spacing = Math.sqrt(n) * 3;

    components.forEach(function(comp, ci) {
      var cx = (ci % compCols) * spacing;
      var cy = Math.floor(ci / compCols) * spacing;
      var compN = comp.length;

      if (compN === 1) {
        pos[comp[0]] = { x: cx, y: cy };
        return;
      }

      // Lay out within component: BFS layers from highest-degree node
      var root = comp[0];
      var bestDeg = -1;
      comp.forEach(function(id) {
        var deg = graphologyGraph.degree(id);
        if (deg > bestDeg) { bestDeg = deg; root = id; }
      });

      var layerVisited = new Set();
      var layers = [];
      var q = [root];
      layerVisited.add(root);
      while (q.length > 0) {
        layers.push(q.slice());
        var next = [];
        q.forEach(function(id) {
          graphologyGraph.neighbors(id).forEach(function(nb) {
            if (!layerVisited.has(nb) && comp.indexOf(nb) !== -1) {
              layerVisited.add(nb); next.push(nb);
            }
          });
        });
        q = next;
      }
      // Place unvisited in final layer
      comp.forEach(function(id) { if (!layerVisited.has(id)) layers.push([id]); });

      // Position: concentric rings from root outward
      var ringSpacing = Math.min(spacing * 0.4, 15 + compN * 0.5);
      layers.forEach(function(layer, depth) {
        if (depth === 0) {
          pos[layer[0]] = { x: cx, y: cy };
          return;
        }
        var radius = depth * ringSpacing;
        layer.forEach(function(id, i) {
          var angle = (2 * Math.PI * i) / layer.length;
          pos[id] = { x: cx + Math.cos(angle) * radius, y: cy + Math.sin(angle) * radius };
        });
      });
    });

    // 4. Write positions to graphology
    nodeIds.forEach(function(id) {
      if (pos[id]) {
        graphologyGraph.setNodeAttribute(id, 'x', pos[id].x);
        graphologyGraph.setNodeAttribute(id, 'y', pos[id].y);
      }
    });
    sigmaInstance.refresh();
    setTimeout(function() { sigmaInstance.getCamera().animatedReset(); }, 50);
  }

  function applyCircularLayout() {
    applyLayoutAndReset(function() {
      var nodes = graphologyGraph.nodes();
      var n = nodes.length;
      nodes.forEach(function(id, i) {
        var angle = (2 * Math.PI * i) / n;
        graphologyGraph.setNodeAttribute(id, 'x', Math.cos(angle) * 100);
        graphologyGraph.setNodeAttribute(id, 'y', Math.sin(angle) * 100);
      });
    });
  }

  function applyGridLayout() {
    applyLayoutAndReset(function() {
      var nodes = graphologyGraph.nodes();
      var cols = Math.ceil(Math.sqrt(nodes.length));
      nodes.forEach(function(id, i) {
        graphologyGraph.setNodeAttribute(id, 'x', (i % cols) * 10);
        graphologyGraph.setNodeAttribute(id, 'y', Math.floor(i / cols) * 10);
      });
    });
  }

  function applyRandomLayout() {
    applyLayoutAndReset(function() {
      graphologyGraph.nodes().forEach(function(id) {
        graphologyGraph.setNodeAttribute(id, 'x', (Math.random() - 0.5) * 200);
        graphologyGraph.setNodeAttribute(id, 'y', (Math.random() - 0.5) * 200);
      });
    });
  }

  function applyConcentricLayout() {
    applyLayoutAndReset(function() {
      var nodes = graphologyGraph.nodes();
      // Sort nodes by degree descending — highest-degree nodes in the center
      var sorted = nodes.slice().sort(function(a, b) {
        return graphologyGraph.degree(b) - graphologyGraph.degree(a);
      });
      // Assign to concentric rings: ring 0 = top degree, ring 1 = next batch, etc.
      var ringSize = Math.max(1, Math.ceil(sorted.length / 8));
      sorted.forEach(function(id, i) {
        var ring = Math.floor(i / ringSize);
        var posInRing = i % ringSize;
        var nodesInThisRing = Math.min(ringSize, sorted.length - ring * ringSize);
        var radius = (ring + 1) * 30;
        var angle = (2 * Math.PI * posInRing) / nodesInThisRing;
        graphologyGraph.setNodeAttribute(id, 'x', Math.cos(angle) * radius);
        graphologyGraph.setNodeAttribute(id, 'y', Math.sin(angle) * radius);
      });
    });
  }

  function applyBreadthfirstLayout() {
    applyLayoutAndReset(function() {
      var nodes = graphologyGraph.nodes();
      // Find root: node with highest in-degree difference (most "parent-like")
      var root = nodes[0];
      var bestScore = -Infinity;
      nodes.forEach(function(id) {
        var score = graphologyGraph.outDegree(id) - graphologyGraph.inDegree(id);
        if (score > bestScore) { bestScore = score; root = id; }
      });
      // BFS layering
      var visited = new Set();
      var layers = [];
      var queue = [root];
      visited.add(root);
      while (queue.length > 0) {
        layers.push(queue.slice());
        var next = [];
        queue.forEach(function(id) {
          graphologyGraph.outNeighbors(id).forEach(function(nb) {
            if (!visited.has(nb)) { visited.add(nb); next.push(nb); }
          });
        });
        queue = next;
      }
      // Place unvisited nodes in a final layer
      var remaining = nodes.filter(function(id) { return !visited.has(id); });
      if (remaining.length > 0) layers.push(remaining);
      // Position: layers top-to-bottom, nodes spread horizontally
      var ySpacing = 20;
      layers.forEach(function(layer, depth) {
        var xSpacing = Math.max(10, 200 / (layer.length + 1));
        layer.forEach(function(id, i) {
          graphologyGraph.setNodeAttribute(id, 'x', (i - layer.length / 2) * xSpacing);
          graphologyGraph.setNodeAttribute(id, 'y', depth * ySpacing);
        });
      });
    });
  }

  function applyOriginalLayout() {
    applyLayoutAndReset(function() {
      graphologyGraph.nodes().forEach(function(id) {
        var orig = allNodeData.get(id);
        if (orig && orig.x !== undefined) {
          graphologyGraph.setNodeAttribute(id, 'x', orig.x);
          graphologyGraph.setNodeAttribute(id, 'y', orig.y);
        }
      });
    });
  }

  // ---- Toolbar ----
  document.getElementById('btn-fit').addEventListener('click', function() {
    if (sigmaInstance) { sigmaInstance.getCamera().animatedReset(); }
  });

  document.getElementById('btn-layout').addEventListener('click', function() {
    currentLayoutIdx = (currentLayoutIdx + 1) % LAYOUTS.length;
    var layoutName = LAYOUTS[currentLayoutIdx];
    this.textContent = layoutName.charAt(0).toUpperCase() + layoutName.slice(1);
    if (!graphologyGraph || !sigmaInstance) return;
    if (layoutName === 'force') applyForceLayout();
    else if (layoutName === 'circular') applyCircularLayout();
    else if (layoutName === 'grid') applyGridLayout();
    else if (layoutName === 'concentric') applyConcentricLayout();
    else if (layoutName === 'breadthfirst') applyBreadthfirstLayout();
    else if (layoutName === 'random') applyRandomLayout();
    else if (layoutName === 'original') applyOriginalLayout();
  });

  document.getElementById('btn-export').addEventListener('click', function() {
    if (!sigmaInstance) { return; }
    var canvas = sigmaInstance.getCanvas();
    var url = canvas.toDataURL('image/png');
    var a = document.createElement('a');
    a.href = url; a.download = 'codegiraffe-graph.png'; a.click();
  });

  // ---- Sidebar toggle ----
  document.getElementById('toggle-sidebar').addEventListener('click', function() {
    document.getElementById('sidebar').classList.toggle('collapsed');
  });

  // ---- Close detail ----
  document.getElementById('close-detail').addEventListener('click', closeDetail);

  // ---- Keyboard shortcuts ----
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') { closeDetail(); }
  });

  // ---- Load button ----
  $loadBtn.addEventListener('click', loadGraph);
  $path.addEventListener('keydown', function(e) {
    if (e.key === 'Enter') { loadGraph(); }
  });
  document.getElementById('apply-server-filters').addEventListener('click', loadGraph);

  // ---- Edge tooltip mouseover (for DOM-level fallback) ----
  document.getElementById('cy-container').addEventListener('mouseover', function(e) {
    // Sigma handles enterEdge events; this is a fallback to keep edge-tooltip logic accessible
  });

  // ---- Auto-load from URL query parameters on page load ----
  (function() {
    var params = new URLSearchParams(window.location.search);
    var pp = params.get('project_path');
    if (pp) {
      document.getElementById('project-path').value = pp;
      currentProjectPath = pp;
      loadGraph();
    }
  })();

})();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_dashboard_routes(
    mcp: Any,
    ensure_graph_fn: Callable[[str], ArchGraph],
    storage: Any,
) -> None:
    """Register the web dashboard HTTP routes on the FastMCP server.

    Parameters
    ----------
    mcp:
        The FastMCP server instance.
    ensure_graph_fn:
        Callable that loads/returns an ``ArchGraph`` for a given project path.
    storage:
        The active ``StorageBackend`` instance (used to check project existence).
    """

    @mcp.custom_route("/dashboard", methods=["GET"])
    async def dashboard_page(request: Request) -> HTMLResponse:
        """Serve the main dashboard HTML page."""
        return HTMLResponse(DASHBOARD_HTML)

    @mcp.custom_route("/api/logo", methods=["GET"])
    async def logo_image(request: Request) -> Response:
        """Serve the Code Giraffe logo PNG, or 404 if the file is absent."""
        data = _load_logo_bytes()
        if data is None:
            return Response(content=b"Not Found", status_code=404)
        return Response(
            content=data,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @mcp.custom_route("/api/init", methods=["POST"])
    async def init_graph(request: Request) -> JSONResponse:
        """Initialize/scan a project so the dashboard can display it."""
        from codegiraffe.scanner import scan_project
        from codegiraffe.graph import ArchGraph, GraphData, Node
        from datetime import datetime, timezone
        import codegiraffe.server as srv

        body = await request.json()
        project_path = body.get("project_path", "")
        if not project_path:
            return JSONResponse({"error": "project_path required"}, status_code=400)
        try:
            result = scan_project(project_path)
            nodes = {node.id: node for node in result.nodes}
            data = GraphData(
                nodes=nodes,
                edges=result.edges,
                project_path=project_path,
                last_scan=datetime.now(timezone.utc).isoformat(),
            )
            graph = ArchGraph(data)
            # Atomically replace _graph and _storage under the server's lock
            # so the MCP-tool thread never sees a torn state.
            with srv._graph_lock:
                storage.save(project_path, graph.to_data())
                srv._graph = graph
                srv._storage = storage
            final = graph.to_data()
            return JSONResponse({
                "status": "ok",
                "nodes": len(final.nodes),
                "edges": len(final.edges),
            })
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)

    @mcp.custom_route("/api/graph", methods=["GET"])
    async def graph_data(request: Request) -> JSONResponse:
        """Return graph data as D3-style JSON for the given project."""
        project_path = request.query_params.get("project_path", "")
        if not project_path:
            return JSONResponse({"error": "project_path query parameter required"}, status_code=400)
        try:
            max_nodes = int(request.query_params.get("max_nodes", "500"))
        except ValueError:
            max_nodes = 500

        path_prefix = request.query_params.get("path_prefix", "")
        node_types_raw = request.query_params.get("node_types", "")
        node_types = [t.strip() for t in node_types_raw.split(",") if t.strip()] if node_types_raw else None

        try:
            result = get_graph_json(
                ensure_graph_fn,
                project_path,
                max_nodes=max_nodes,
                path_prefix=path_prefix,
                node_types=node_types,
            )
            return JSONResponse(result)
        except RuntimeError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)

    @mcp.custom_route("/api/node", methods=["GET"])
    async def node_detail(request: Request) -> JSONResponse:
        """Return detailed information about a single node."""
        project_path = request.query_params.get("project_path", "")
        node_id = request.query_params.get("node_id", "")
        if not project_path or not node_id:
            return JSONResponse({"error": "project_path and node_id query parameters required"}, status_code=400)
        try:
            result = get_node_detail(ensure_graph_fn, project_path, node_id)
            if "error" in result:
                return JSONResponse(result, status_code=404)
            return JSONResponse(result)
        except RuntimeError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)

    @mcp.custom_route("/api/subgraph", methods=["GET"])
    async def subgraph_data(request: Request) -> JSONResponse:
        """Return a subgraph centered on *node_id*."""
        project_path = request.query_params.get("project_path", "")
        node_id = request.query_params.get("node_id", "")
        if not project_path or not node_id:
            return JSONResponse({"error": "project_path and node_id query parameters required"}, status_code=400)
        depth_str = request.query_params.get("depth", "2")
        try:
            depth = int(depth_str)
        except ValueError:
            depth = 2
        try:
            result = get_subgraph_json(ensure_graph_fn, project_path, node_id, depth)
            return JSONResponse(result)
        except RuntimeError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)

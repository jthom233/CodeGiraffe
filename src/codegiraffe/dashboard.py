"""Web dashboard for Code Giraffe architecture graphs.

Serves a single-page Cytoscape.js-based visualization of the architecture
knowledge graph.  All HTML, CSS, and JavaScript are embedded in this module
--- no external files are needed.

Usage::

    from codegiraffe.dashboard import register_dashboard_routes
    register_dashboard_routes(mcp, _ensure_graph, _storage)
"""

from __future__ import annotations

import json
from typing import Any, Callable

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

from codegiraffe.export import to_d3_json
from codegiraffe.graph import ArchGraph, GraphData

# ---------------------------------------------------------------------------
# Pure data-fetching functions (testable without HTTP)
# ---------------------------------------------------------------------------


def get_graph_json(ensure_graph_fn: Callable[[str], ArchGraph], project_path: str) -> dict:
    """Return graph data as a D3-style JSON dict.

    Raises ``RuntimeError`` when the project has not been initialized.
    """
    graph = ensure_graph_fn(project_path)
    data = graph.to_data()
    return json.loads(to_d3_json(data))


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
#cy { width: 100%; height: 100%; }

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
</style>
</head>
<body>
<div id="app">
  <button id="toggle-sidebar" title="Toggle sidebar">&#9776;</button>
  <div id="sidebar">
    <div class="sidebar-section">
      <h3>Project</h3>
      <input type="text" id="project-path" placeholder="/path/to/project" />
      <button id="load-btn">Load Graph</button>
      <div id="error-msg"></div>
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
      <button id="btn-layout" title="Toggle layout">Layout</button>
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

<script src="https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.30.4/cytoscape.min.js"></script>
<script>
(function() {
  "use strict";

  // ---- Color / shape palettes ----
  const TYPE_COLORS = {
    service: '#4A90D9', endpoint: '#7B68EE', database_table: '#2ECC71',
    queue: '#E67E22', env_var: '#F39C12', config: '#D4AC0D',
    worker: '#E74C3C', frontend_component: '#9B59B6', event: '#1ABC9C',
    external_api: '#95A5A6', module: '#D35400', contract: '#8E44AD'
  };
  const TYPE_SHAPES = {
    endpoint: 'diamond', database_table: 'barrel', worker: 'hexagon',
    queue: 'rectangle', event: 'ellipse', module: 'round-rectangle',
    contract: 'hexagon'
  };
  const DEFAULT_COLOR = '#4A90D9';
  const DEFAULT_SHAPE = 'round-rectangle';

  // ---- State ----
  let cy = null;
  let currentLayout = 'cose';
  let allElements = [];
  let activeTypes = new Set();

  // ---- DOM refs ----
  const $path = document.getElementById('project-path');
  const $loadBtn = document.getElementById('load-btn');
  const $search = document.getElementById('search-box');
  const $filters = document.getElementById('filters');
  const $statNodes = document.getElementById('stat-nodes');
  const $statEdges = document.getElementById('stat-edges');
  const $statVisible = document.getElementById('stat-visible');
  const $errorMsg = document.getElementById('error-msg');
  const $loading = document.getElementById('loading');
  const $detailPanel = document.getElementById('detail-panel');
  const $detailTitle = document.getElementById('detail-title');
  const $detailBody = document.getElementById('detail-body');

  // ---- Helpers ----
  function truncate(s, n) { return s && s.length > n ? s.slice(0, n) + '...' : s; }

  function showError(msg) {
    $errorMsg.textContent = msg; $errorMsg.style.display = 'block';
    setTimeout(() => { $errorMsg.style.display = 'none'; }, 5000);
  }

  function d3ToCytoscape(d3Data) {
    const elements = [];
    (d3Data.nodes || []).forEach(n => {
      elements.push({
        group: 'nodes',
        data: {
          id: n.id, label: n.label || n.id, type: n.type || 'unknown',
          file_path: n.file_path || '', manual: n.manual || false,
          metadata: n.metadata || {}
        }
      });
    });
    (d3Data.links || []).forEach(e => {
      elements.push({
        group: 'edges',
        data: {
          id: e.source + '-' + e.target + '-' + e.type,
          source: e.source, target: e.target, type: e.type || ''
        }
      });
    });
    return elements;
  }

  // ---- Cytoscape init ----
  function initCy(elements) {
    if (cy) cy.destroy();
    cy = cytoscape({
      container: document.getElementById('cy'),
      elements: elements,
      minZoom: 0.2,
      maxZoom: 3,
      style: [
        {
          selector: 'node',
          style: {
            'label': function(ele) { return truncate(ele.data('label'), 25); },
            'text-valign': 'bottom',
            'text-halign': 'center',
            'font-size': '10px',
            'color': '#c0c0c0',
            'text-margin-y': 4,
            'width': 32,
            'height': 32,
            'border-width': 2,
            'border-color': '#0f3460',
            'background-color': function(ele) {
              return TYPE_COLORS[ele.data('type')] || DEFAULT_COLOR;
            },
            'shape': function(ele) {
              return TYPE_SHAPES[ele.data('type')] || DEFAULT_SHAPE;
            }
          }
        },
        {
          selector: 'node:selected',
          style: {
            'border-color': '#fff',
            'border-width': 3
          }
        },
        {
          selector: 'edge',
          style: {
            'width': 1.5,
            'line-color': '#2a3a5e',
            'target-arrow-color': '#4A90D9',
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
            'label': function(ele) { return ele.data('type') || ''; },
            'font-size': '8px',
            'color': '#556',
            'text-rotation': 'autorotate',
            'text-margin-y': -8
          }
        },
        {
          selector: 'edge:selected',
          style: {
            'line-color': '#4A90D9',
            'width': 2.5
          }
        },
        {
          selector: 'edge.highlighted',
          style: {
            'line-color': '#F1C40F',
            'target-arrow-color': '#F1C40F',
            'width': 2.5,
            'z-index': 10
          }
        },
        {
          selector: 'edge[type="imports"]',
          style: {
            'line-color': '#E67E22',
            'target-arrow-color': '#E67E22',
            'line-style': 'dashed'
          }
        },
        {
          selector: 'edge[type="implements"]',
          style: {
            'line-color': '#9B59B6',
            'target-arrow-color': '#9B59B6',
            'line-style': 'solid'
          }
        },
        {
          selector: 'edge[type="contains"]',
          style: {
            'line-color': '#2ECC71',
            'target-arrow-color': '#2ECC71',
            'line-style': 'dotted'
          }
        },
        {
          selector: 'edge[type="produces"]',
          style: {
            'line-style': 'solid',
            'width': 3,
            'line-color': '#8E44AD',
            'target-arrow-color': '#8E44AD'
          }
        },
        {
          selector: 'edge[type="consumes_contract"]',
          style: {
            'line-style': 'dashed',
            'width': 2,
            'line-color': '#9B59B6',
            'target-arrow-color': '#9B59B6'
          }
        },
        {
          selector: 'edge[type="validates"]',
          style: {
            'line-style': 'dotted',
            'width': 2,
            'line-color': '#27AE60',
            'target-arrow-color': '#27AE60'
          }
        },
        {
          selector: 'edge[type="violates"]',
          style: {
            'line-style': 'solid',
            'width': 3,
            'line-color': '#E74C3C',
            'target-arrow-color': '#E74C3C'
          }
        }
      ],
      layout: { name: 'cose', animate: false, nodeDimensionsIncludeLabels: true }
    });

    cy.on('tap', 'node', function(evt) { showNodeDetail(evt.target.data()); });
    cy.on('dbltap', 'node', function(evt) { zoomToSubgraph(evt.target.id()); });
    cy.on('tap', function(evt) {
      if (evt.target === cy) closeDetail();
    });

    const EDGE_LABELS = {
        produces: 'Produces',
        consumes_contract: 'Consumes Contract',
        validates: 'Validates',
        violates: 'Violates'
    };

    cy.on('mouseover', 'edge', function(evt) {
        const edge = evt.target;
        const tip = document.getElementById('edge-tooltip');
        const edgeType = edge.data('type');
        const displayLabel = EDGE_LABELS[edgeType] || edgeType;
        tip.textContent = displayLabel + ': ' + edge.data('source') + ' → ' + edge.data('target');
        tip.style.display = 'block';
        const pos = evt.renderedPosition || evt.position;
        const container = document.getElementById('cy-container');
        const rect = container.getBoundingClientRect();
        tip.style.left = (pos.x + 10) + 'px';
        tip.style.top = (pos.y - 20) + 'px';
    });

    cy.on('mouseout', 'edge', function() {
        document.getElementById('edge-tooltip').style.display = 'none';
    });

    cy.on('tap', 'node', function(evt) {
        cy.edges().removeClass('highlighted');
        evt.target.connectedEdges().addClass('highlighted');
    });

    updateStats();
  }

  const LAYOUTS = ['cose', 'circle', 'grid', 'concentric', 'breadthfirst'];

  function runLayout(name) {
    if (!cy) return;
    const layoutConfigs = {
        cose: { name: 'cose', animate: true, animationDuration: 500, nodeDimensionsIncludeLabels: true },
        circle: { name: 'circle', animate: true, animationDuration: 500 },
        grid: { name: 'grid', animate: true, animationDuration: 500 },
        concentric: { name: 'concentric', animate: true, animationDuration: 500,
            concentric: function(node) { return node.degree(); },
            levelWidth: function() { return 2; }
        },
        breadthfirst: { name: 'breadthfirst', animate: true, animationDuration: 500, directed: true }
    };
    cy.layout(layoutConfigs[name] || layoutConfigs.cose).run();
  }

  // ---- Load graph ----
  async function loadGraph() {
    const path = $path.value.trim();
    if (!path) { showError('Enter a project path'); return; }
    $loadBtn.disabled = true;
    $loading.style.display = 'block';
    $errorMsg.style.display = 'none';

    try {
      let resp = await fetch('/api/graph?project_path=' + encodeURIComponent(path));
      if (resp.status === 404) {
        // Auto-init: scan the project first
        $loading.textContent = 'Scanning project...';
        const initResp = await fetch('/api/init', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({project_path: path})
        });
        if (!initResp.ok) {
          const err = await initResp.json().catch(() => ({}));
          throw new Error(err.error || 'Failed to initialize project');
        }
        $loading.textContent = 'Loading...';
        resp = await fetch('/api/graph?project_path=' + encodeURIComponent(path));
      }
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.error || resp.statusText);
      }
      const d3Data = await resp.json();
      allElements = d3ToCytoscape(d3Data);
      buildFilters(d3Data.nodes || []);
      $search.disabled = false;
      $search.value = '';
      initCy(allElements);
      buildLegend();
    } catch (e) {
      showError(e.message);
    } finally {
      $loadBtn.disabled = false;
      $loading.style.display = 'none';
    }
  }

  // ---- Filters ----
  function buildFilters(nodes) {
    const types = new Set(nodes.map(n => n.type || 'unknown'));
    activeTypes = new Set(types);
    $filters.innerHTML = '';
    [...types].sort().forEach(t => {
      const lbl = document.createElement('label');
      const cb = document.createElement('input');
      cb.type = 'checkbox'; cb.checked = true; cb.value = t;
      cb.addEventListener('change', applyFilters);
      const colorDot = document.createElement('span');
      colorDot.style.cssText = 'display:inline-block;width:10px;height:10px;border-radius:50%;background:' + (TYPE_COLORS[t] || DEFAULT_COLOR);
      lbl.appendChild(cb); lbl.appendChild(colorDot);
      lbl.appendChild(document.createTextNode(' ' + t));
      $filters.appendChild(lbl);
    });
  }

  function applyFilters() {
    if (!cy) return;
    activeTypes.clear();
    $filters.querySelectorAll('input[type=checkbox]').forEach(cb => {
      if (cb.checked) activeTypes.add(cb.value);
    });
    const query = $search.value.trim().toLowerCase();
    cy.nodes().forEach(n => {
      const typeOk = activeTypes.has(n.data('type'));
      const searchOk = !query || n.data('label').toLowerCase().includes(query) || n.data('id').toLowerCase().includes(query);
      if (typeOk && searchOk) n.removeClass('hidden').style('display', 'element');
      else n.addClass('hidden').style('display', 'none');
    });
    cy.edges().forEach(e => {
      const srcVis = e.source().style('display') !== 'none';
      const tgtVis = e.target().style('display') !== 'none';
      if (srcVis && tgtVis) e.style('display', 'element');
      else e.style('display', 'none');
    });
    updateStats();
  }

  // ---- Search ----
  let searchTimer = null;
  $search.addEventListener('input', function() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(applyFilters, 300);
  });

  // ---- Stats ----
  function updateStats() {
    if (!cy) return;
    const visNodes = cy.nodes().filter(n => n.style('display') !== 'none');
    const totalNodes = cy.nodes().length;
    const totalEdges = cy.edges().length;
    document.getElementById('stat-nodes').textContent = totalNodes;
    document.getElementById('stat-edges').textContent = totalEdges;
    document.getElementById('stat-visible').textContent = visNodes.length;

    // Avg degree
    const avgDeg = totalNodes > 0 ? (2 * totalEdges / totalNodes).toFixed(1) : '0';
    document.getElementById('stat-avg-degree').textContent = avgDeg;

    // Connected components (simple BFS)
    const visited = new Set();
    let components = 0;
    cy.nodes().forEach(n => {
        if (!visited.has(n.id())) {
            components++;
            const queue = [n];
            while (queue.length > 0) {
                const cur = queue.shift();
                if (visited.has(cur.id())) continue;
                visited.add(cur.id());
                cur.neighborhood('node').forEach(nb => {
                    if (!visited.has(nb.id())) queue.push(nb);
                });
            }
        }
    });
    document.getElementById('stat-components').textContent = components;

    // Type distribution bar chart
    const typeCounts = {};
    cy.nodes().forEach(n => {
        const t = n.data('type') || 'unknown';
        typeCounts[t] = (typeCounts[t] || 0) + 1;
    });
    const maxCount = Math.max(...Object.values(typeCounts), 1);
    const $dist = document.getElementById('type-distribution');
    if ($dist) {
        let html = '';
        Object.keys(typeCounts).sort().forEach(t => {
            const pct = (typeCounts[t] / maxCount) * 100;
            const color = TYPE_COLORS[t] || DEFAULT_COLOR;
            html += '<div class="dist-row"><span class="dist-label">' + t + '</span><span class="dist-bar" style="width:' + pct + '%;background:' + color + '"></span><span class="dist-count">' + typeCounts[t] + '</span></div>';
        });
        $dist.innerHTML = html;
    }
  }

  // ---- Legend ----
  function buildLegend() {
    const $legend = document.getElementById('legend');
    if (!$legend) return;
    let html = '';
    // Node types
    Object.keys(TYPE_COLORS).sort().forEach(t => {
        html += '<div class="legend-item"><span class="legend-swatch" style="background:' + TYPE_COLORS[t] + '"></span>' + t + '</div>';
    });
    html += '<div class="legend-divider"></div>';
    // Edge types
    const edgeStyles = {
        imports: { color: '#E67E22', style: 'dashed' },
        implements: { color: '#9B59B6', style: '' },
        contains: { color: '#2ECC71', style: 'dotted' },
        produces: { color: '#8E44AD', style: '' },
        consumes_contract: { color: '#9B59B6', style: 'dashed' },
        validates: { color: '#27AE60', style: 'dotted' },
        violates: { color: '#E74C3C', style: '' },
        default: { color: '#2a3a5e', style: '' }
    };
    Object.keys(edgeStyles).forEach(t => {
        const s = edgeStyles[t];
        html += '<div class="legend-item"><span class="legend-line ' + s.style + '" style="border-color:' + s.color + '"></span>' + t + '</div>';
    });
    $legend.innerHTML = html;
  }

  // ---- Detail panel ----
  function showNodeDetail(data) {
    $detailTitle.textContent = data.label || data.id;
    let html = '';
    const fields = [
      ['ID', data.id], ['Type', data.type], ['Label', data.label],
      ['File Path', data.file_path || 'N/A'], ['Manual', data.manual ? 'Yes' : 'No']
    ];
    fields.forEach(([label, val]) => {
      html += '<div class="detail-field"><div class="label">' + label + '</div><div class="value">' + escapeHtml(String(val)) + '</div></div>';
    });
    if (data.metadata && Object.keys(data.metadata).length > 0) {
      html += '<div class="detail-field"><div class="label">Metadata</div><div class="value"><pre style="font-size:11px;white-space:pre-wrap;color:#9ab;">' + escapeHtml(JSON.stringify(data.metadata, null, 2)) + '</pre></div></div>';
    }

    // Connected edges
    if (cy) {
      const node = cy.getElementById(data.id);
      const incoming = node.incomers('edge');
      const outgoing = node.outgoers('edge');
      if (incoming.length > 0) {
        html += '<div class="detail-field"><div class="label">Incoming Edges (' + incoming.length + ')</div><ul class="edge-list">';
        incoming.forEach(e => {
          html += '<li><span class="edge-type">' + escapeHtml(e.data('type')) + '</span> from ' + escapeHtml(e.data('source')) + '</li>';
        });
        html += '</ul></div>';
      }
      if (outgoing.length > 0) {
        html += '<div class="detail-field"><div class="label">Outgoing Edges (' + outgoing.length + ')</div><ul class="edge-list">';
        outgoing.forEach(e => {
          html += '<li><span class="edge-type">' + escapeHtml(e.data('type')) + '</span> to ' + escapeHtml(e.data('target')) + '</li>';
        });
        html += '</ul></div>';
      }
    }
    $detailBody.innerHTML = html;
    $detailPanel.classList.add('open');
  }

  function closeDetail() { $detailPanel.classList.remove('open'); }

  function escapeHtml(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  // ---- Zoom to subgraph ----
  async function zoomToSubgraph(nodeId) {
    const path = $path.value.trim();
    if (!path || !cy) return;
    try {
      const resp = await fetch('/api/subgraph?project_path=' + encodeURIComponent(path) + '&node_id=' + encodeURIComponent(nodeId) + '&depth=2');
      if (!resp.ok) return;
      const d3Data = await resp.json();
      const subIds = new Set((d3Data.nodes || []).map(n => n.id));
      const subNodes = cy.nodes().filter(n => subIds.has(n.id()));
      if (subNodes.length > 0) cy.fit(subNodes, 40);
    } catch(e) { /* silently ignore */ }
  }

  // ---- Toolbar ----
  document.getElementById('btn-fit').addEventListener('click', function() {
    if (cy) cy.fit(cy.nodes().filter(n => n.style('display') !== 'none'), 30);
  });

  document.getElementById('btn-layout').addEventListener('click', function() {
    const idx = LAYOUTS.indexOf(currentLayout);
    currentLayout = LAYOUTS[(idx + 1) % LAYOUTS.length];
    this.textContent = currentLayout.charAt(0).toUpperCase() + currentLayout.slice(1);
    runLayout(currentLayout);
  });

  document.getElementById('btn-export').addEventListener('click', function() {
    if (!cy) return;
    const png = cy.png({ bg: '#1a1a2e', full: true });
    const a = document.createElement('a');
    a.href = png; a.download = 'codegiraffe-graph.png'; a.click();
  });

  // ---- Sidebar toggle ----
  document.getElementById('toggle-sidebar').addEventListener('click', function() {
    document.getElementById('sidebar').classList.toggle('collapsed');
  });

  // ---- Close detail ----
  document.getElementById('close-detail').addEventListener('click', closeDetail);

  // ---- Keyboard shortcuts ----
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') closeDetail();
  });

  // ---- Load button ----
  $loadBtn.addEventListener('click', loadGraph);
  $path.addEventListener('keydown', function(e) {
    if (e.key === 'Enter') loadGraph();
  });

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
            result = get_graph_json(ensure_graph_fn, project_path)
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

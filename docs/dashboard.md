[← Back to Documentation](README.md)

# Web Dashboard

Code Giraffe includes a built-in web dashboard for interactive graph exploration. No additional dependencies required — it uses Cytoscape.js loaded from CDN and is served via FastMCP's HTTP routes.

---

## Launching the Dashboard

Start the server with HTTP transport:

```bash
python src/codegiraffe/server.py --transport streamable-http --port 8000
```

Then open `http://localhost:8000/dashboard` in your browser.

---

## Features

- **Interactive graph visualization** — Pan, zoom, click nodes for details
- **Node type filtering** — Toggle visibility by type (endpoint, service, database_table, etc.)
- **Search** — Filter nodes by label or ID in real-time
- **Node detail panel** — Click any node to see its properties, metadata, and connected edges
- **Subgraph focus** — Double-click a node to zoom into its neighborhood
- **5 layout algorithms** — Force-directed (cose), circular, grid, concentric, and breadthfirst layouts
- **Legend & stats** — Visual legend of node types and real-time graph statistics
- **Edge tooltips** — Hover edges to see relationship type and metadata
- **Styled edge types** — Color-coded edges:
  - Orange dashed: `imports`
  - Purple solid: `implements`
  - Blue solid: `calls`
  - Green dotted: `contains`
  - Contract-specific styles: `produces`, `consumes_contract`, `validates`, `violates`
- **PNG export** — Download the current view as an image
- **Dark theme** — Developer-friendly dark interface with refined color palette

---

## API Endpoints

The dashboard also exposes JSON API endpoints for programmatic access:

| Endpoint | Description |
|---|---|
| `POST /api/init` | Initialize/scan a project (body: `{"project_path": "..."}`) |
| `GET /api/graph?project_path=...` | Full graph as D3.js-compatible JSON |
| `GET /api/node?project_path=...&node_id=...` | Node detail with connected edges |
| `GET /api/subgraph?project_path=...&node_id=...&depth=2` | Subgraph centered on a node |
| `GET /api/logo` | Code Giraffe logo as PNG (cached 24h) |

These endpoints return the same data as the MCP tools but as plain JSON over HTTP, making them suitable for integration with custom tooling or CI pipelines.

---

## See Also

- [Core Tools](tools/core.md) — `codegiraffe_export` for generating Mermaid and D3.js graph exports outside the dashboard

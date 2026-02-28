[← Back to Documentation](README.md)

# Web Dashboard

Code Giraffe includes a built-in web dashboard for interactive graph exploration. The core dashboard requires no extra dependencies — it uses Sigma.js v3 and Graphology loaded from CDN and is served via FastMCP's HTTP routes. For optimal layout, install the `fa2` package (`uv pip install -e ".[layout]"`) to enable server-side ForceAtlas2 layout computation. Without it, the dashboard falls back to grid layout.

---

## Launching the Dashboard

### Via the MCP tool (primary method)

Call the `codegiraffe_dashboard` MCP tool from any MCP client (Claude Code, Claude Desktop, etc.):

```
codegiraffe_dashboard(
  project_path="/home/user/my-project",
  port=8251
)
--> Dashboard running at http://localhost:8251/dashboard?project_path=...
    Opened browser to the dashboard.
```

This starts a standalone Starlette/uvicorn HTTP server on port 8251 (default) as a background daemon thread and opens your default browser. If port 8251 is occupied, the next free port up to 8255 is used automatically. The project must be initialized first (`codegiraffe_init`).

### Via HTTP transport (alternative)

If you are running the MCP server with HTTP transport, you can also access the dashboard directly:

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
- **7 layout algorithms** — `original` (precomputed ForceAtlas2), `force` (spring-based), `circular`, `grid`, `concentric`, `breadthfirst`, and `random` layouts
- **Legend & stats** — Visual legend of node types and real-time graph statistics
- **Edge tooltips** — Hover edges to see relationship type and metadata
- **Color-coded edges** — Edges are differentiated by color per relationship type:
  - Orange: `imports`
  - Purple: `implements`
  - Blue: `calls`
  - Green: `contains`
  - Contract-specific colors: `produces`, `consumes_contract`, `validates`, `violates`
- **Circular nodes with color coding** — All nodes render as circles; node type is indicated by color (e.g., contract nodes are purple circles)
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

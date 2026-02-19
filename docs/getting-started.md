[← Back to Documentation](README.md)

# Getting Started

Code Giraffe is an architecture knowledge graph MCP server. It captures the relationships that static code analysis can't see — runtime coupling, data flows, cross-system contracts, and operational context — and exposes them to AI agents as queryable graph data.

This guide walks you through installation, optional dependency setup, and configuring Code Giraffe in your MCP client.

---

## Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip
- An MCP-compatible client (Claude Code, Claude Desktop, Cursor, etc.)

---

## Installation

Clone the repository and install the core package:

```bash
git clone https://github.com/jthom233/CodeGiraffe.git
cd CodeGiraffe
uv venv .venv && source .venv/bin/activate
uv pip install -e ".[dev]"
```

### Optional Dependencies

Code Giraffe's core functionality works out of the box. The optional extras unlock additional capabilities:

**Embedding-based context scoring** (falls back to keyword matching if not installed):

```bash
uv pip install -e ".[dev,embeddings]"
```

**Neo4j storage backend** (for enterprise-scale graphs):

```bash
uv pip install -e ".[neo4j]"
```

**AST-aware scanning** (higher accuracy via tree-sitter):

```bash
uv pip install -e ".[ast]"
```

**Server-side layout computation** (ForceAtlas2 graph layout for the web dashboard):

```bash
uv pip install -e ".[layout]"
```

You can also combine extras or install them with pip:

```bash
pip install -e ".[embeddings]"   # Embedding-based scoring
pip install -e ".[neo4j]"        # Neo4j storage backend
pip install -e ".[ast]"          # AST-aware scanning
pip install -e ".[layout]"       # Server-side layout computation
```

---

## Add to Claude Code

Register Code Giraffe as an MCP server using the Claude Code CLI:

```bash
claude mcp add codegiraffe -- /path/to/CodeGiraffe/.venv/bin/python /path/to/CodeGiraffe/src/codegiraffe/server.py
```

Or add it manually to your `~/.claude.json`:

```json
{
  "mcpServers": {
    "codegiraffe": {
      "type": "stdio",
      "command": "/path/to/CodeGiraffe/.venv/bin/python",
      "args": ["/path/to/CodeGiraffe/src/codegiraffe/server.py"],
      "env": {}
    }
  }
}
```

---

## Add to Claude Desktop

Add the following to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "codegiraffe": {
      "command": "/path/to/CodeGiraffe/.venv/bin/python",
      "args": ["/path/to/CodeGiraffe/src/codegiraffe/server.py"]
    }
  }
}
```

---

## First Use

Once Code Giraffe is registered with your MCP client, initialize it against your project:

```
codegiraffe_init(project_path="/path/to/your-project")
--> "Initialized graph with 47 nodes and 63 edges"
```

The scanner automatically detects architectural patterns across 9 languages. From there, you can query the graph for context before making changes:

```
codegiraffe_context_for(
  project_path="/path/to/your-project",
  task="add rate limiting to the payments endpoint"
)
--> JSON subgraph with the payments endpoint, its DB tables, middleware, and env vars
```

---

## Next Steps

- [Architecture](architecture.md) — Understand the data model, module layout, and built-in node/edge types
- [Multi-Language Scanner](scanner.md) — See what each language recognizer detects and how to extend it
- [Tool Reference](tools/README.md) — Full reference for all 37 MCP tools

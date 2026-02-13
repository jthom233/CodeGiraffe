# Implementation Plan: Code Giraffe Core MCP Server

**Branch**: `001-core-mcp-server` | **Date**: 2026-02-12 | **Spec**: `specs/001-core-mcp-server/spec.md`

## Summary

Build an MCP server in Python that exposes an architecture knowledge graph via
MCP tools. The graph captures beyond-AST relationships (runtime coupling, data
flows, cross-system contracts, operational context) as a directed graph with
typed nodes and edges. Storage is JSON-file-based with NetworkX for in-memory
operations. All tools are exposed via FastMCP decorators over stdio transport.

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: mcp[cli] (FastMCP), NetworkX, pydantic
**Storage**: JSON files (`.codegiraffe/graph.json`)
**Testing**: pytest
**Target Platform**: Any OS with Python 3.11+ and an MCP-compatible client
**Project Type**: Single Python package
**Constraints**: < 2s for graph queries on 500-node graphs, < 5s for init scans

## Constitution Check

| Principle | Status | Notes |
|-----------|--------|-------|
| I. MCP-Native | PASS | All features exposed as @mcp.tool() |
| II. Graph-First | PASS | NetworkX DiGraph with typed nodes/edges |
| III. Beyond-AST | PASS | Core purpose of the tool |
| IV. Context Efficiency | PASS | Scoped queries, depth limits, hotspot ranking |
| V. Incremental | PASS | Sync + manual annotation preservation |
| VI. Test-First | PASS | Contract tests + integration tests planned |
| VII. Simplicity | PASS | JSON storage, Python, no external DBs |

## Project Structure

### Source Code

```text
src/
├── codegiraffe/
│   ├── __init__.py
│   ├── server.py          # FastMCP server + tool definitions
│   ├── graph.py            # Graph data model (Node, Edge, Graph classes)
│   ├── storage.py          # Storage abstraction + JSON backend
│   ├── scanner.py          # Codebase scanner (Python patterns)
│   ├── query.py            # Query engine (subgraph extraction, ranking)
│   └── types.py            # Node/edge type enums + custom type registry

tests/
├── conftest.py             # Shared fixtures (sample graphs, temp dirs)
├── test_graph.py           # Unit tests for graph data model
├── test_storage.py         # Unit tests for storage layer
├── test_scanner.py         # Unit tests for scanner
├── test_query.py           # Unit tests for query engine
├── test_tools.py           # Contract tests for MCP tool schemas
└── test_integration.py     # End-to-end tests (init → query → mutate → query)

pyproject.toml              # Package config, dependencies, entry points
```

### Key Design Decisions

1. **Pydantic models for Node/Edge/Graph**: Gives us validation, serialization,
   and automatic schema generation for MCP tool responses.

2. **Storage abstraction**: `StorageBackend` protocol with `JSONStorage`
   implementation. Future backends implement the same protocol.

3. **Scanner as a pluggable pipeline**: Scanner discovers nodes/edges from file
   patterns. Each pattern recognizer is a function that takes a file path and
   returns nodes/edges. Easy to add new language support.

4. **NetworkX for graph operations**: Mature library for subgraph extraction,
   path finding, centrality metrics (for hotspots), cycle detection.

5. **Graph stored with `manual` flag on each node/edge**: During rescan, only
   non-manual items are replaced. Manual annotations survive.

## MCP Tool Definitions

| Tool | Inputs | Output |
|------|--------|--------|
| `codegiraffe_init` | `project_path: str`, `rescan: bool = false` | Summary of discovered nodes/edges |
| `codegiraffe_query` | `node_id: str \| None`, `node_type: str \| None`, `depth: int = 2` | Subgraph JSON |
| `codegiraffe_add_relation` | `source: str`, `target: str`, `relation_type: str`, `metadata: dict = {}` | Confirmation + edge details |
| `codegiraffe_context_for` | `task: str`, `max_nodes: int = 20` | Ranked subgraph relevant to the task |
| `codegiraffe_detect_drift` | (none) | List of mismatches |
| `codegiraffe_hotspots` | `top_n: int = 10` | Ranked nodes by coupling score |
| `codegiraffe_sync` | (none) | Summary of additions/removals |

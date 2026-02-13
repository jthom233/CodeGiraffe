# Specification

## Requirements

Code Giraffe v0.2.0 - Architecture Knowledge Graph MCP Server

Code Giraffe is an MCP (Model Context Protocol) server that exposes an architecture knowledge graph for AI-assisted development. It captures beyond-AST relationships (runtime coupling, data flows, cross-system contracts, operational context) as a directed graph with typed nodes and edges.

## Core Features (v0.1.0 — implemented)

### 1. Graph Initialization (codegiraffe_init)
- Scan a project directory and bootstrap the architecture knowledge graph
- Auto-detect architectural entities from Python source code using regex pattern matching
- Detect: Flask/FastAPI endpoints, SQLAlchemy models, Celery tasks, env vars, HTTP clients, class definitions
- Store graph as JSON at {project_path}/.codegiraffe/graph.json
- Support rescan while preserving manual annotations (manual=True flag)
- NEW in v0.2.0: `backend` parameter allows choosing "json" or "sqlite" storage

### 2. Graph Querying (codegiraffe_query)
- Query by node_id for subgraph extraction with configurable depth
- Query by node_type for type-based filtering
- Returns scoped subgraph — NOT the full graph — to minimize token usage
- Fuzzy suggestions for non-existent node IDs

### 3. Manual Relation Annotation (codegiraffe_add_relation)
- Add relationships the scanner missed (runtime coupling, queue consumers, etc.)
- Auto-create nodes if source/target don't exist
- Manual annotations (manual=True) survive rescans
- Custom node and edge types supported (any string)

### 4. Context for Task (codegiraffe_context_for)
- Given a natural-language task description, return the minimal relevant subgraph
- Nodes ranked by relevance score
- NEW in v0.2.0: `use_embeddings` parameter for semantic scoring via sentence-transformers
- Falls back to keyword-based scoring when embeddings unavailable
- Configurable max_nodes limit

### 5. Drift Detection (codegiraffe_detect_drift)
- Compare graph against current codebase to find mismatches
- Report: nodes in graph but missing from code, nodes in code but missing from graph
- NEW in v0.2.0: Potential rename detection via string similarity
- NEW in v0.2.0: Edge drift analysis (edges referencing non-existent nodes)
- NEW in v0.2.0: Enhanced similarity scoring for rename candidates

### 6. Hotspot Analysis (codegiraffe_hotspots)
- Rank nodes by coupling density (degree centrality)
- Return top-N most connected architectural hotspots
- Include node metadata, type, and score

### 7. Incremental Sync (codegiraffe_sync)
- Re-scan project and update graph incrementally
- Preserve manual annotations
- Report before/after counts with deltas

## v0.2.0 Features (all implemented)

### 8. Plugin System for Custom Recognizers (registry.py)
- RecognizerRegistry class maps file extensions to PatternRecognizer implementations
- get_default_registry() lazily creates registry with all built-in recognizers
- register_recognizer() convenience function for adding custom recognizers
- scan_project() updated to use registry for language-agnostic scanning
- Each recognizer maps to specific file extensions (e.g., .py/.pyi for Python, .ts/.tsx/.mts/.cts for TypeScript)

### 9. Multi-Language Scanner Support (recognizers/)
Five language recognizers, each implementing the PatternRecognizer protocol:
- **Python** (.py, .pyi): Flask/FastAPI routes, SQLAlchemy models, Celery tasks, os.environ, requests.* calls
- **TypeScript** (.ts, .tsx, .mts, .cts): Express/Fastify/Koa routes, NestJS decorators, TypeORM entities, Prisma models, process.env, fetch/axios, event emitters, React/Vue components, Bull/BullMQ queues
- **Go** (.go): net/http handlers, Gin/Echo/Chi routes, GORM models, db.Table calls, os.Getenv, http.Get/Post
- **Rust** (.rs): Actix/Rocket attributes, Axum routes, Diesel table macros, Queryable structs, env::var, env!(), reqwest calls
- **Java** (.java): Spring @GetMapping/@PostMapping, @RequestMapping, JPA @Entity/@Table, System.getenv, @Value, RestTemplate/WebClient, @RabbitListener/@KafkaListener, @EventListener

All recognizers infer cross-file edges (e.g., endpoints → database tables in same file).

### 10. SQLite Storage Backend (sqlite_storage.py)
- SQLiteStorage class implementing the StorageBackend protocol
- Stored at {project_path}/.codegiraffe/graph.db
- WAL journal mode for concurrent reads
- Foreign keys enabled
- Proper indexing on nodes.type, nodes.file_path, edges.source, edges.target, edges.type
- Schema versioning via graph_meta table
- Each save replaces all data in a transaction

### 11. Graph Visualization Export (export.py + codegiraffe_export tool)
- **Mermaid**: Export as flowchart with typed node shapes (parallelogram for endpoints, cylinder for tables, hexagon for workers, etc.), optional subgraph grouping by type, configurable direction (TD/LR/BT/RL)
- **D3.js JSON**: Export as force-directed graph JSON with nodes, links, and metadata
- New MCP tool: codegiraffe_export(format="mermaid"|"d3", direction, subgraph_by_type, node_id, depth)
- Supports scoped export (export subgraph around a specific node)

### 12. Embedding-Based Context Scoring (embeddings.py)
- Optional dependency: sentence-transformers (all-MiniLM-L6-v2 model)
- is_available() check for graceful degradation
- embed_text/embed_texts for vector generation
- cosine_similarity using pure stdlib (no numpy required)
- node_to_text converts graph nodes to embeddable text representations
- score_nodes_by_embedding for semantic task matching
- EmbeddingCache with SHA256-keyed file-based persistence at .codegiraffe/embeddings.json
- Falls back to keyword scoring when sentence-transformers not installed

### 13. Multi-Agent Coordination (coordination.py + 3 new tools)
- AgentClaim dataclass: agent_id, node_ids, task, status (active/done/blocked), claimed_at, ttl, metadata
- CoordinationStore class with file-based persistence at .codegiraffe/agents.json
- Default TTL: 1800 seconds (30 minutes), automatic expiration
- Conflict detection: prevents claiming nodes already claimed by another active agent
- New MCP tools:
  - codegiraffe_claim(agent_id, node_ids, task, ttl) — claim nodes for an agent
  - codegiraffe_status(agent_id, status, task) — update agent status, refresh TTL
  - codegiraffe_agents() — list all active agents and their claims

## Data Model

### Node Types (built-in)
service, endpoint, database_table, queue, env_var, config, worker, frontend_component, event, external_api

### Edge Types (built-in)
calls, reads, writes, publishes, consumes, depends_on, configures, owns, triggers

Custom types are fully supported — any string works as a node or edge type.

### Storage Backends
- JSON (default): .codegiraffe/graph.json
- SQLite: .codegiraffe/graph.db (selected via backend="sqlite" on init)

## Technology Stack
- Python 3.11+
- FastMCP (mcp[cli]) for MCP server
- NetworkX for in-memory graph operations
- Pydantic v2 for data models
- pytest for testing (231 tests)
- uv for package management
- Optional: sentence-transformers for embedding-based scoring

## Non-Functional Requirements
- Graph queries must complete in less than 2 seconds on 500-node graphs
- Init scans must complete in less than 5 seconds
- All 11 MCP tools must have contract tests
- Manual annotations must survive rescans
- Embedding cache must persist across sessions
- Agent claims must auto-expire after TTL

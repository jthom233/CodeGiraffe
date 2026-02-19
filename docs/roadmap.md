[← Back to Documentation](README.md)

# Roadmap

Complete version history and future plans for Code Giraffe.

---

## v0.2.0 (completed)

- [x] Multi-language scanner support (TypeScript, Go, Rust, Java)
- [x] SQLite storage backend for larger graphs
- [x] Graph visualization export (Mermaid, D3.js)
- [x] Richer drift detection with rename tracking
- [x] Embedding-based context scoring (replace keyword matching)
- [x] Multi-agent status coordination tools
- [x] Plugin system for custom recognizers

## v0.2.1 (completed)

- [x] CI/CD pipeline (GitHub Actions — Python 3.11/3.12/3.13 matrix)
- [x] Enhanced Go recognizer (imports, interfaces, events, IPC, SQL)

## v0.3.0 (completed)

- [x] Neo4j storage backend (optional `neo4j` dependency)
- [x] AST-aware scanning via tree-sitter (optional `ast` dependency)
- [x] Cross-repo graph federation with namespace isolation
- [x] Schema evolution and versioning with auto-versioning on sync/init
- [x] 8 new MCP tools (19 total)

## v0.3.1 (completed)

- [x] Interactive web dashboard with Cytoscape.js graph visualization

## v0.4.0 (completed)

- [x] Scanner intelligence: test file exclusion (default), import detection, inheritance detection, module nodes
- [x] New node type: `module` with `contains` edges to file-level entities
- [x] New edge types: `imports` (inter-module), `implements` (inheritance), `contains` (module-to-entity)
- [x] `include_tests` parameter for `codegiraffe_init` and `codegiraffe_sync`
- [x] 505+ tests

## v0.5.0 (completed)

- [x] 4 new language recognizers: C#, C/C++, PHP, Ruby (now 9 languages)
- [x] 3 new dashboard layouts: grid, concentric, breadthfirst (now 5 total)
- [x] Dashboard improvements: legend, stats panel, edge tooltips, refined color palette
- [x] 566+ tests

## v0.6.0 (completed)

- [x] Language-agnostic scanner intelligence: universal module nodes, `contains` edges, import detection, and implementation/inheritance detection for all 9 languages
- [x] `ImportInfo` and `ImplementationInfo` data classes on `ScanResult` for structured recognizer output
- [x] Go `go.mod`-aware import path resolution and interface implementation detection
- [x] Test file exclusion extended to all 9 languages
- [x] 698+ tests

## v0.7.0 (completed)

- [x] 3 new MCP tools: `codegiraffe_blast_radius`, `codegiraffe_risk_assessment`, `codegiraffe_cycles` (22 tools total)
- [x] Blast radius analysis: downstream impact ranked by severity (direct, transitive, indirect)
- [x] Risk assessment: composite score from degree centrality, betweenness centrality, and descendant count
- [x] Cycle detection: find circular dependencies in the architecture graph
- [x] Enhanced `codegiraffe_context_for` with `include_impact` parameter for blast radius + risk on top nodes
- [x] Enhanced `codegiraffe_hotspots` with `metrics` parameter for multi-metric analysis
- [x] 754+ tests

## v0.8.0 (completed)

- [x] 3 new MCP tools: `codegiraffe_contracts`, `codegiraffe_validate_contracts`, `codegiraffe_add_contract` (25 tools total)
- [x] Cross-system contract modeling: `contract` node type with `produces`, `consumes_contract`, `validates`, `violates` edge types
- [x] Contract inference: automatic detection of API, event, config, and data contracts from scanned patterns
- [x] Contract-aware blast radius: contract consumers receive critical severity in impact analysis
- [x] Contract validation: integrity checks for producer/consumer relationships
- [x] Dashboard contract styling: hexagonal purple nodes for contract visualization
- [x] 791+ tests

## v0.9.0 — Scanner Depth (completed)

- [x] Call-graph edges: detect function/method calls across Go, Python, TypeScript (regex + AST)
- [x] Enhanced Go interface/implementation tracking (duck-type satisfaction detection)
- [x] Demand-driven method-level nodes for call-graph participants
- [x] Tree-sitter AST call detection support
- [x] Improved TypeScript multi-interface and generic `implements` handling
- [x] 874+ tests

## v0.10.0 — Change Impact Validation (completed)

- [x] `codegiraffe_validate_changes`: detect missing changes from a git diff
- [x] `codegiraffe_suggest_tests`: recommend test files to run for a given change
- [x] `codegiraffe_file_coupling`: mine git history for co-changed file pairs
- [x] Enhanced `codegiraffe_context_for` with `include_changes` parameter
- [x] New modules: `diff_parser.py`, `git_utils.py`
- [x] 979+ tests

## v0.11.0 — Intelligent Context (completed)

- [x] 1 new MCP tool: `codegiraffe_patterns` (29 tools total)
- [x] Token-aware context budgets: `token_budget` and `detail_level` parameters on `codegiraffe_context_for`
- [x] Intent-aware navigation: automatically classifies task intent (feature, bug fix, performance, refactoring, documentation)
- [x] Enhanced `codegiraffe_context_for` response fields: `_token_estimate`, `_retrieval_strategy`
- [x] Architectural decision record (ADR) detection: identifies and surfaces architectural decisions from patterns
- [x] Convention mining: `codegiraffe_patterns` analyzes naming conventions, structural patterns, and detects anti-patterns
- [x] 1087+ tests

## v0.12.0 — Graph Enrichment (completed)

- [x] 2 new MCP tools: `codegiraffe_annotate`, `codegiraffe_sync_files` (31 tools total)
- [x] Edge confidence scoring: all edges carry confidence value (0.0-1.0) based on detection method
- [x] Enhanced `codegiraffe_context_for` with `min_confidence` parameter to filter edges by confidence
- [x] Ownership and annotation layer: nodes annotated with owner, stability status (stable/experimental/deprecated/legacy), and notes
- [x] Incremental file sync: `codegiraffe_sync_files` for fast updates of changed files only
- [x] Enhanced `codegiraffe_blast_radius` with `cross_team_impact` detection for ownership-aware analysis
- [x] Confidence-weighted blast radius: impact calculations weighted by edge confidence
- [x] 1154+ tests

## v0.13.0 — Advanced Analysis (completed)

- [x] 6 new MCP tools: `codegiraffe_coverage`, `codegiraffe_pr_diff`, `codegiraffe_order_tasks`, `codegiraffe_domains`, `codegiraffe_migration_plan`, `codegiraffe_dashboard` (37 tools total)
- [x] One-click web dashboard launch via `codegiraffe_dashboard` tool (spawns HTTP server, opens browser)
- [x] Test coverage mapping: map coverage.py/Istanbul/LCOV data to graph nodes for risk assessment
- [x] Enhanced `codegiraffe_risk_assessment` with coverage data: uncovered nodes receive 1.5x risk multiplier
- [x] Enhanced `codegiraffe_suggest_tests` with `coverage_status` field (covered/uncovered/unknown)
- [x] PR diffing: compare architecture at two git refs to detect structural changes
- [x] Dependency-aware task ordering: topological sort with parallel groups and conflict zone detection
- [x] Domain model abstraction: infer or manage logical domain groupings from directory structure
- [x] CI/CD integration workflow: migration planning for large refactors with phased rollout
- [x] 1339+ tests

## v0.14.0 — Sigma.js v3 Dashboard (completed)

- [x] Sigma.js v3 + Graphology replacing Cytoscape.js as the dashboard renderer
- [x] WebGL renderer for interactive visualization of 33k+ node graphs
- [x] Server-side ForceAtlas2 layout computation via `layout.py` (fa2 optional dep)
- [x] Standalone Starlette/uvicorn background HTTP server via `dashboard_server.py`
- [x] 7 layout algorithms available (ForceAtlas2, circular, random, and more)
- [x] New files: `layout.py`, `dashboard_server.py`
- [x] New optional dependency: `fa2>=0.1` (layout extra)
- [x] 1452+ tests

---

## Future

- [ ] Publish to PyPI

# Research: Graph Intelligence

**Branch**: `011-graph-intelligence` | **Date**: 2026-02-16

## 1. Token Estimation Strategy

**Decision**: Use character count / 4 as token proxy
**Rationale**: Approximate 4 characters per token holds across Claude, GPT, Gemini families. Avoids adding `tiktoken` dependency. Estimation runs on the serialized JSON string of each node + its edges.
**Alternatives considered**: tiktoken (adds dependency, model-specific), word count / 0.75 (less accurate for code/IDs)

## 2. Intent Classification Approach

**Decision**: Keyword dictionary with priority-ordered matching
**Rationale**: Zero dependencies, <1ms latency. Keywords: create → ["create", "add", "new", "build", "implement"], debug → ["debug", "fix", "bug", "error", "broken", "issue", "troubleshoot"], refactor → ["refactor", "restructure", "reorganize", "move", "extract", "split"], delete → ["delete", "remove", "deprecate", "drop"], test → ["test", "spec", "verify", "coverage", "assert"]. First match wins. Unmatched → "modify" (current behavior).
**Alternatives considered**: LLM classification (adds latency + dependency), NLP embeddings (overkill for 6 categories)

## 3. Confidence Scoring Storage

**Decision**: Add `confidence: float = 1.0` field directly to `Edge` Pydantic model
**Rationale**: Metadata approach considered but rejected — confidence is a first-class property that affects query filtering and impact analysis. Default 1.0 ensures backward compatibility with existing stored graphs (Pydantic `model_validate` auto-fills defaults). Edge model is at `graph.py:27-34`.
**Alternatives considered**: Store in `edge.metadata["confidence"]` (works but less typed, harder to filter efficiently)

## 4. Confidence Values by Detection Method

**Decision**: Tiered confidence based on detection source

| Detection Method | Confidence | Rationale |
|-----------------|------------|-----------|
| AST-parsed import | 1.0 | Tree-sitter provides definitive proof |
| Manual annotation | 1.0 | Human-verified |
| Regex import detection | 0.9 | High reliability, occasional false positives |
| Cross-file inference | 0.8 | Content-based matching |
| Call-graph (direct symbol match) | 0.8 | Symbol registry lookup |
| Call-graph (fallback resolution) | 0.6 | File-path-based resolution |
| Inheritance (regex) | 0.8 | Pattern matching |
| Interface satisfaction (duck-type) | 0.7 | Method set superset matching |
| Contract inference | 0.5 | Pattern-based heuristic |

**Alternatives considered**: Binary (high/low) — too coarse. Per-language tuning — premature optimization.

## 5. ADR Detection Patterns

**Decision**: Regex patterns for comment markers across languages

| Pattern | Language Coverage | Example |
|---------|------------------|---------|
| `# DECISION:` | Python, Ruby, Bash | `# DECISION: Use event bus, not HTTP` |
| `// ADR-\d+:` | Go, JS/TS, Java, C#, C++, Rust, PHP | `// ADR-007: Services communicate via events` |
| `/* ADR-\d+:` | Multi-line block comments | `/* ADR-003: JWT over sessions */` |

Decision nodes: `decision:{file}:{line}` ID format. Metadata: `text` (full line), `adr_id` (if numbered), `file_path`, `line_number`.

**Constraint targeting**: `constrains` edges target specific governed nodes, not just the file module. Resolution order: (1) scan decision text for node ID references (e.g., "service:PaymentService"), (2) if no explicit match, target the nearest enclosing symbol node from the same file, (3) fallback to file module node. This ensures decisions are linked to the components they actually govern.

**Git commit mining**: Deferred to a future release. v0.11.0 ADR detection is limited to code comment markers (`# DECISION:`, `// ADR-`, `/* ADR-`).

**Alternatives considered**: Markdown ADR file parsing (out of scope — captures beyond-AST knowledge per Constitution III)

## 6. Convention Mining: Similarity Measurement

**Decision**: Structural metadata clustering via attribute frequency analysis
**Rationale**: For each node type cluster (3+ nodes), count frequency of metadata keys and values. Convention = attribute/pattern present in >66% of nodes. Anti-pattern = node missing >50% of conventions. Uses `_extract_naming_pattern()` to detect common prefixes/suffixes in node IDs and labels.
**Alternatives considered**: Code content diffing (too expensive), embedding similarity (overkill for structural patterns)

## 7. Incremental Sync: Edge Invalidation Strategy

**Decision**: Track edge provenance via `file_path` on source nodes
**Rationale**: When a file changes, find all nodes with `file_path == changed_file`, collect all edges where `source` or `target` is one of those nodes AND `edge.metadata.get("inferred") == True`, remove those edges, then rescan the file and re-run inference stages for just those files. Manual edges (`manual=True`) are never removed.
**Alternatives considered**: Full rescan (what we have now — too slow), edge-level provenance tracking (adds complexity)

## 8. PR Diff: Graph Construction at Arbitrary Refs

**Decision**: Use `git worktree` for temporary checkout at each ref
**Rationale**: Git worktrees create a separate working directory without disturbing the main checkout. Process: `git worktree add /tmp/cg-base-{hash} base_ref` → scan → build graph → `git worktree remove`. Temp directories auto-cleaned.
**Alternatives considered**: `git stash` + checkout (disturbs working directory), `git archive` (doesn't support full project scan), in-memory git objects (too complex)

## 9. Task Ordering: Dependency Graph Construction

**Decision**: Map tasks to file-level module nodes, use graph edges for dependency ordering
**Rationale**: Each task specifies target files. Files map to module nodes via `_file_to_module_path_universal()`. Module `imports` edges define dependencies. Topological sort via `nx.topological_sort()` on the task subgraph. Parallel groups = nodes at the same topological level with no shared edges.
**Alternatives considered**: Function-level ordering (too granular), manual dependency specification (doesn't leverage the graph)

## 10. Domain Inference: Clustering Signal

**Decision**: Primary signal = directory path segments; secondary = node ID prefixes
**Rationale**: Directory structure is the strongest organizational signal in most codebases. Extract top-level directory from each node's `file_path` (e.g., `payments/service.py` → domain "payments"). For flat structures, cluster by node ID prefix (e.g., `service:Payment*` → domain "payment"). Manual domains override inferred ones.
**Alternatives considered**: Community detection algorithms on graph (slow, unstable results), embedding clustering (overkill)

## 11. Dashboard: New Visual Elements

**Decision**: Incremental dashboard updates per release

| Release | New Element | Style |
|---------|------------|-------|
| v0.11.0 | `decision` node type | `#2196F3` (blue), `tag` shape |
| v0.11.0 | `constrains` edge | Blue dotted, width 1.5 |
| v0.11.0 | `supersedes` edge | Gray dashed, width 1 |
| v0.12.0 | Confidence opacity | Edge opacity = confidence (0.3 min, 1.0 max) |
| v0.12.0 | Ownership badge | Small dot overlay on nodes with `owner` metadata |
| v0.13.0 | Domain grouping | Compound nodes (Cytoscape.js parent-child) |

**Alternatives considered**: All at once (too much visual change), external dashboard (contradicts existing pattern)

## 12. Existing Code Touchpoints

| Feature | Files Modified | New Files |
|---------|---------------|-----------|
| Token budgets | `query.py`, `server.py` | — |
| Intent navigation | `query.py`, `server.py` | — |
| ADRs | `schema.py`, `scanner.py`, `query.py`, `server.py`, `dashboard.py` | — |
| Convention mining | `server.py` | `patterns.py` |
| Confidence scoring | `graph.py`, `scanner.py`, `query.py`, `server.py`, `dashboard.py` | — |
| Ownership | `scanner.py`, `server.py`, `query.py` | `ownership.py` |
| Incremental sync | `scanner.py`, `server.py`, `graph.py` | — |
| CI/CD | — | `.github/workflows/codegiraffe-pr.yml` |
| PR diff | `server.py` | `graph_diff.py` |
| Test coverage | `server.py`, `query.py` | `coverage_mapper.py` |
| Task ordering | `server.py`, `query.py` | — |
| Domains | `server.py`, `query.py` | `domains.py` |
| Migration planner | `server.py` | `migration.py` |

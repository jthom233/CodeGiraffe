# Quickstart: Graph Intelligence

**Branch**: `011-graph-intelligence` | **Date**: 2026-02-16

## Development Setup

```bash
# Activate existing dev environment
source .venv/bin/activate

# Run existing tests (should pass — baseline)
python -m pytest tests/ -v

# Work on the 011-graph-intelligence branch
git checkout 011-graph-intelligence
```

## Implementation Order (v0.11.0 — Intelligent Context)

### Step 1: Schema Setup

1. Add `DECISION` to `NodeType` enum in `schema.py`
2. Add `CONSTRAINS`, `MOTIVATED_BY`, `SUPERSEDES` to `EdgeType` enum in `schema.py`

### Step 2: Token-Aware Context Budgets

1. Add `_estimate_tokens(node, detail_level)` helper in `query.py`
2. Add `token_budget` and `detail_level` parameters to `context_for_task`
3. Implement greedy fill with token cap
4. Add `_token_estimate` to response
5. Update `codegiraffe_context_for` in `server.py`
6. Tests: `tests/test_token_budget.py`

### Step 3: Intent-Aware Navigation

1. Add `_classify_intent(task)` in `query.py`
2. Add per-intent retrieval strategies
3. Add `_retrieval_strategy` to response
4. Tests: `tests/test_intent_navigation.py`

### Step 4: ADR Detection

1. Add `_detect_decision_markers()` to scanner pipeline
2. Create `constrains` edges to governed nodes (matching node IDs in text or nearest enclosing symbol)
3. Add `_include_constraining_decisions()` to `context_for_task`
4. Verify `add_relation` works with `decision` node type and new edge types
5. Tests: `tests/test_decisions.py`

### Step 5: Convention Mining

1. Create `src/codegiraffe/patterns.py`
2. Add `codegiraffe_patterns` tool in `server.py`
3. Tests: `tests/test_patterns.py`

### Step 6: Dashboard Updates (v0.11.0)

1. Add `decision` to `TYPE_COLORS` and `TYPE_SHAPES` in `dashboard.py`
2. Add `constrains` and `supersedes` edge styles
3. Tests: `tests/test_dashboard.py` (extend existing)

## Implementation Order (v0.12.0 — Graph Enrichment)

### Step 7: Confidence Scoring on Edges

1. Add `confidence: float = 1.0` to `Edge` class in `graph.py`
2. Update scanner pipeline functions to set confidence values per detection method
3. Add `min_confidence` parameter to `context_for_task` in `query.py`
4. Weight blast radius by confidence in `query.py`
5. Add confidence-based edge opacity to `dashboard.py`
6. Tests: `tests/test_confidence.py`

### Step 8: Ownership Layer

1. Create `src/codegiraffe/ownership.py` (CODEOWNERS parsing, git blame inference)
2. Add `codegiraffe_annotate` tool in `server.py`
3. Update `blast_radius` for cross-team impact flagging (builds on Step 7's blast_radius changes)
4. Tests: `tests/test_ownership.py`

### Step 9: Incremental Sync

1. Implement `sync_files()` in `scanner.py`
2. Add `codegiraffe_sync_files` tool in `server.py`
3. Tests: `tests/test_incremental_sync.py`

## Running Tests

```bash
# Run all tests
python -m pytest tests/ -v

# Run specific feature tests (v0.11.0)
python -m pytest tests/test_token_budget.py -v
python -m pytest tests/test_intent_navigation.py -v
python -m pytest tests/test_decisions.py -v
python -m pytest tests/test_patterns.py -v

# Run specific feature tests (v0.12.0)
python -m pytest tests/test_confidence.py -v
python -m pytest tests/test_ownership.py -v
python -m pytest tests/test_incremental_sync.py -v
```

## Key Files to Modify

### v0.11.0

| File | Changes |
|------|---------|
| `src/codegiraffe/schema.py` | Add `DECISION` node type, `CONSTRAINS`/`MOTIVATED_BY`/`SUPERSEDES` edge types |
| `src/codegiraffe/query.py` | Token budgets, intent classification, decision inclusion |
| `src/codegiraffe/scanner.py` | ADR comment marker detection |
| `src/codegiraffe/server.py` | Updated `context_for`, new `patterns` tool |
| `src/codegiraffe/dashboard.py` | Decision node styling, new edge styles |
| `src/codegiraffe/patterns.py` | NEW — convention mining logic |

### v0.12.0

| File | Changes |
|------|---------|
| `src/codegiraffe/graph.py` | Add `confidence` field to `Edge` |
| `src/codegiraffe/scanner.py` | Confidence assignment per detection method |
| `src/codegiraffe/query.py` | Confidence filtering, confidence-weighted blast radius |
| `src/codegiraffe/server.py` | `codegiraffe_annotate`, `codegiraffe_sync_files` tools |
| `src/codegiraffe/dashboard.py` | Confidence-based edge opacity, ownership badge |
| `src/codegiraffe/ownership.py` | NEW — CODEOWNERS parsing, git blame inference |

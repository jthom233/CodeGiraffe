[← Back to Documentation](README.md)

# Embedding-Based Scoring

The `codegiraffe_context_for` tool supports two scoring modes for ranking node relevance to a task description. Both modes return the same subgraph structure — they differ only in how nodes are ranked.

---

## Keyword Scoring (default fallback)

Uses keyword overlap between the task description and node labels, IDs, and metadata. Always available, requires no extra dependencies.

This mode works well for queries that use the exact same terminology as your codebase (e.g., searching for "payments" in a project with `service:PaymentService`).

---

## Embedding-Based Scoring (optional)

When `sentence-transformers` is installed, scoring uses semantic embeddings to find relevant nodes even when exact keywords don't match. For example, a query about "authentication" will correctly surface nodes labeled "login", "JWT", and "session" even without keyword overlap.

**Install embedding support:**

```bash
uv pip install -e ".[embeddings]"
# or
pip install codegiraffe[embeddings]
```

Embedding scoring is enabled automatically when the dependency is available. No configuration required.

### Disabling Embeddings

To force keyword-only scoring even when `sentence-transformers` is installed, pass `use_embeddings=false`:

```
codegiraffe_context_for(
  project_path="/home/user/my-project",
  task="refactor the authentication flow",
  use_embeddings=false
)
```

---

## Example: Semantic Relevance

With embedding scoring enabled, semantically related nodes surface even without exact keyword matches:

```
codegiraffe_context_for(
  project_path="/home/user/my-project",
  task="add rate limiting to the payments endpoint",
  token_budget=2000,
  detail_level="detailed"
)
--> JSON subgraph with payments endpoint, its middleware, DB tables, env vars, ranked by relevance
    _token_estimate: 1856
    _retrieval_strategy: "refactor"
```

The `_retrieval_strategy` field in the response tells you which task intent was classified: `create`, `debug`, `refactor`, `delete`, `test`, or `modify`.

---

## Embedding Cache

Embeddings are computed once and cached on disk for performance. The cache is invalidated automatically when node content changes.

---

## See Also

- [Context and Analysis Tools](tools/context-and-analysis.md) — Full reference for `codegiraffe_context_for` including `min_confidence`, `include_impact`, `include_changes`, `token_budget`, and `detail_level` parameters

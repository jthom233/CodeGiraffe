[← Back to Documentation](README.md)

# Edge Confidence Scoring

All edges in the architecture graph carry a `confidence` value (0.0–1.0) that reflects the reliability of the detected relationship. Higher confidence means the edge is more likely to be accurate; lower confidence indicates the relationship was inferred with less certainty.

---

## Confidence Values by Detection Method

| Detection Method | Confidence |
|---|---|
| AST-parsed edges (tree-sitter) | 1.0 |
| `contains` edges (module → entity) | 1.0 |
| Regex imports with exact matches | 0.9 |
| Inheritance (extends/implements) | 0.8 |
| Call-graph edges (high certainty) | 0.8 |
| Call-graph edges (lower certainty) | 0.6 |
| Interface satisfaction (Go) | 0.7 |
| Contract inference | 0.5 |

Edges created manually via `codegiraffe_add_relation` or `codegiraffe_add_contract` carry a confidence value of `1.0` since they are explicitly asserted.

---

## Filtering by Confidence

Use the `min_confidence` parameter on `codegiraffe_context_for` to exclude lower-confidence edges from the returned subgraph:

```
codegiraffe_context_for(
  project_path="/home/user/my-project",
  task="add rate limiting to payments endpoint",
  min_confidence=0.7
)
--> Only edges with confidence >= 0.7 are included in the subgraph
```

This is useful when you want to focus on well-established relationships (imports, inheritance) and exclude speculative inferences (contract inference, lower-certainty call edges).

---

## Blast Radius Weighting

Confidence values are incorporated into blast radius analysis. High-confidence direct impacts are weighted more heavily than speculative transitive impacts. This means:

- A direct `reads` edge with confidence 0.9 contributes more to impact severity than an inferred `calls` edge with confidence 0.6
- The blast radius report reflects actual risk more accurately than a simple hop count

---

## See Also

- [Context and Analysis Tools](tools/context-and-analysis.md) — `codegiraffe_context_for` with `min_confidence` parameter, `codegiraffe_blast_radius` with confidence-weighted impact

[← Back to Documentation](README.md)

# Edge Confidence Scoring

All edges in the architecture graph carry a `confidence` value (0.0–1.0) that reflects the reliability of the detected relationship. Higher confidence means the edge is more likely to be accurate; lower confidence indicates the relationship was inferred with less certainty.

---

## Confidence Values by Detection Method

| Detection Method | Confidence |
|---|---|
| AST-parsed edges (tree-sitter) | 1.0 |
| `contains` edges (module → entity) | 1.0 |
| Regex imports with exact matches (Python direct + the universal `ImportInfo` → `imports` edge pipeline shared by every other language recognizer) | 0.9 |
| XML-parsed dependency edges (`.csproj` `PackageReference`/`ProjectReference`, `packages.config`) | 0.9 |
| SQL foreign key `depends_on` edges (`FOREIGN KEY ... REFERENCES`, including `ALTER TABLE ... ADD CONSTRAINT ... FOREIGN KEY`) | 0.9 |
| Inheritance (extends/implements) — regex, via the universal `ImplementationInfo` → `implements` edge pipeline | 0.8 |
| Call-graph edges (high certainty — callee resolves to a node in the same file as the call site) | 0.8 |
| Regex pattern-match edges emitted directly inside a recognizer (not via `ImportInfo`/`ImplementationInfo`/`CallInfo`) — e.g. `reads`/`writes`/`depends_on`/`configures`/`calls` inferred from endpoint↔table co-occurrence, Go internal package imports, Go unix-socket IPC, C#/SQL cross-language string references | 0.8 |
| Interface satisfaction (Go duck-typing, `_infer_interface_satisfaction`) | 0.7 |
| SQL inferred body edges (`reads`/`writes`/`calls` from `FROM`/`JOIN`/`INSERT`/`UPDATE`/`DELETE`/`MERGE`/`EXEC` pattern matches) and SQL migration `writes` edges (`migration:<file>` → pre-existing table) | 0.7 |
| Call-graph edges (lower certainty — callee resolves cross-file/cross-module via the global symbol registry) | 0.6 |
| Contract inference | 0.5 |

When neither side of a call edge has file-path information available, the scanner cannot determine same-file vs. cross-file certainty and defaults to the higher-certainty value (0.8) rather than penalizing missing data.

Edges created manually via `codegiraffe_add_relation` or `codegiraffe_add_contract` carry a confidence value of `1.0` since they are explicitly asserted.

In hybrid scan mode, regex recognizers run first and AST recognizers are merged in second (`ScanResult.merge`). When the same `(source, target, type)` edge is produced by both, the merge keeps whichever has higher confidence (the AST edge, typically 1.0) rather than silently discarding it in favor of whichever was inserted first.

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

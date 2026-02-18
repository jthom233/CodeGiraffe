# API Contract: GET /api/graph (extended)

**Version**: v0.14.0 (adds `x`, `y` to node objects)
**Backward compatible**: Yes — `x`/`y` are optional fields

## Request

```
GET /api/graph
  ?project_path=<url-encoded-path>   REQUIRED
  &max_nodes=<int>                   OPTIONAL, default 500, 0=no limit
  &path_prefix=<string>              OPTIONAL, default "" (no filter)
  &node_types=<csv>                  OPTIONAL, default "" (all types)
```

## Response 200

```json
{
  "nodes": [
    {
      "id": "string",
      "type": "string",
      "label": "string",
      "group": "string",
      "file_path": "string | null",
      "manual": "boolean",
      "metadata": "object",
      "x": "float (present when layout is stored)",
      "y": "float (present when layout is stored)"
    }
  ],
  "links": [
    {
      "source": "string",
      "target": "string",
      "type": "string",
      "manual": "boolean",
      "confidence": "float",
      "metadata": "object"
    }
  ],
  "metadata": {
    "project_path": "string",
    "last_scan": "string | null",
    "schema_version": "string",
    "node_count": "int",
    "edge_count": "int"
  },
  "truncated": "boolean",
  "total_nodes": "int (present when truncated=true)",
  "total_edges": "int (present when truncated=true)",
  "unfiltered_total_nodes": "int",
  "unfiltered_total_edges": "int"
}
```

## Response 400
```json
{ "error": "project_path query parameter required" }
```

## Response 404
```json
{ "error": "No architecture graph found for '...'. Run codegiraffe_init first." }
```

## Response 500
```json
{ "error": "string" }
```

## Change from v0.13.0
- Added `x: float` and `y: float` to each node object (optional, present only when layout has been computed)
- All other fields unchanged

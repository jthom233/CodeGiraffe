# Implementation Plan: API & DX Improvements

**Branch**: `035-api-improvements` | **Date**: 2026-02-25 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/035-api-improvements/spec.md`

## Summary

Replace the action-enum `codegiraffe_domains` tool with four focused tools, remove the permanently-failing `codegiraffe_restore` stub, expose the existing internal `CoordinationStore.release()` method as a new `codegiraffe_release` tool, and rename `codegiraffe_status` to an unambiguous agent-coordination name. All changes are surgical edits to `src/codegiraffe/server.py` with corresponding test updates in `tests/test_domains.py`, `tests/test_coordination.py`, and `tests/test_server_integration.py`. Net tool count change: +3 (1 domain tool → 4, +1 release tool, −1 restore tool).

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: FastMCP (mcp[cli] >= 1.2.0), NetworkX >= 3.0, Pydantic v2
**Storage**: JSON files (primary), SQLite (secondary), Neo4j (optional)
**Testing**: pytest >= 8.0, pytest-asyncio >= 0.23
**Target Platform**: Linux/macOS (MCP server process)
**Project Type**: Single project
**Performance Goals**: No runtime performance impact — changes are tool-surface only
**Constraints**: No backward-compatibility aliases; clean rename/removal per spec
**Scale/Scope**: 4 tool mutations in `server.py` (2555 lines); test suite 1600+ tests

## Constitution Check

- **MCP-Native**: All changes stay within `@mcp.tool()` surface. No new abstractions. Pass.
- **Graph-First**: No graph schema changes. Pass.
- **Beyond-AST**: Not applicable. Pass.
- **Context Efficiency**: Splitting one multi-action tool into four reduces LLM confusion without adding latency. Pass.
- **Incremental & Non-Destructive**: Removing a permanently-failing tool is non-destructive in practice. Pass.
- **Test-First (NON-NEGOTIABLE)**: New failing tests must be written before implementation for each user story.
- **Simplicity**: Each new tool has a single responsibility and minimal parameters. Pass.

## Project Structure

### Documentation (this feature)

```text
specs/035-api-improvements/
├── spec.md              # Requirements
├── plan.md              # This file
└── tasks.md             # Task list (produced by speckit.tasks)
```

### Source Code (repository root)

```text
src/codegiraffe/
├── server.py            # PRIMARY: all tool definitions live here
└── coordination.py      # READ-ONLY: release() method already implemented

tests/
├── test_domains.py      # Update: replace codegiraffe_domains contract tests
│                        #         with four new tool contract tests
├── test_coordination.py # Update: add codegiraffe_release and
│                        #         codegiraffe_update_agent_status tests
└── test_server_integration.py
                         # Update: remove codegiraffe_restore import + TestRestore class
```

**Structure Decision**: Single project. Only `server.py` changes at the implementation layer; `coordination.py` and `domains.py` are already correct — no changes needed there.

## Detailed Technical Findings

### US1 — Split `codegiraffe_domains` into 4 tools

**Current state** (`server.py` lines 1087–1189):
- Single `@mcp.tool()` function `codegiraffe_domains(project_path, action, name, node_ids)`
- Guards action against `_VALID_DOMAIN_ACTIONS = {"list", "infer", "add", "remove"}`
- Delegates to four private helpers already imported from `domains.py`:
  - `_list_domains(graph) -> list[dict]`
  - `_infer_domains(graph) -> list[dict]`
  - `_add_domain(graph, name, node_ids) -> None`
  - `_remove_domain(graph, name) -> None`
- All four helpers are idiomatic and complete; no changes needed in `domains.py`

**Target state** — four new tools, `_VALID_DOMAIN_ACTIONS` constant and old function deleted:

| New tool | Parameters | Body |
|---|---|---|
| `codegiraffe_list_domains(project_path)` | 1 | Extract `action == "list"` branch |
| `codegiraffe_infer_domains(project_path)` | 1 | Extract `action == "infer"` branch |
| `codegiraffe_add_domain(project_path, name, node_ids)` | 3 | Extract `action == "add"` branch; `node_ids: str` comma-separated |
| `codegiraffe_remove_domain(project_path, name)` | 2 | Extract `action == "remove"` branch |

**Lock pattern**: Each new tool wraps its body in `with _graph_lock:` matching existing pattern. `_ensure_graph` is called inside the lock just as in the original.

**Storage saves**: `infer_domains` and `add_domain` and `remove_domain` call `_storage.save(project_path, graph.to_data())` — this must be preserved in the extracted tools.

**Test impact**: `tests/test_domains.py` class `TestDomainContractTool` (lines 597–669) tests `codegiraffe_domains` by name and checks the `action` parameter. All 8 tests in that class must be replaced with equivalent tests for the four new tools. The behavioral tests in `TestDomainInferAction` (lines 672–747) test `action="add"` and `action="remove"` via `codegiraffe_domains` — these must be migrated to call the new focused tools.

### US2 — Remove `codegiraffe_restore` stub

**Current state** (`server.py` lines 2029–2056):
- `@mcp.tool()` `codegiraffe_restore(project_path, version_id)` — always returns the "not yet supported" error string after side-effectfully creating a backup snapshot
- `tests/test_server_integration.py` line 35 imports `codegiraffe_restore`; class `TestRestore` (lines 170–177) asserts "not yet supported" is in the result

**Target state**: Delete the tool definition entirely. In `test_server_integration.py`, remove the `codegiraffe_restore` import and delete the `TestRestore` class. Replace `TestRestore` with a test that verifies `codegiraffe_restore` is NOT present on the server module (negative contract test).

### US3 — Expose `codegiraffe_release` tool

**Current state**:
- `coordination.py` line 146: `CoordinationStore.release(project_path, agent_id) -> dict[str, Any]`
  - Returns `{"success": True, "released": <int>}` where `released` is the count removed
  - Removes ALL claims for `agent_id` (not node-specific)
  - Does NOT check claim ownership for nodes not claimed by this agent — it simply filters by `agent_id`, so it's inherently own-claims-only by design
- FR-005 (agents can only release their own claims) is already satisfied by the implementation: `claims = [c for c in claims if c.agent_id != agent_id]`
- No `codegiraffe_release` function exists yet in `server.py`

**Target state** — new tool inserted after `codegiraffe_claim` and before `codegiraffe_status` (current line ~1917):

```python
@mcp.tool()
def codegiraffe_release(project_path: str, agent_id: str) -> str:
    """Release all claims held by an agent, allowing other agents to claim those nodes.

    Call this when your work is complete (or if you need to abandon a task).
    Releases are immediate — other agents can claim the freed nodes right away.

    If this agent has no active claims, the call succeeds with a count of 0.
    """
    try:
        result = _coordinator.release(project_path, agent_id)
        return json.dumps(result, indent=2)
    except Exception as exc:
        return f"Error releasing claims: {exc}"
```

**Acceptance scenario 3** (release of unclaimed nodes): `CoordinationStore.release()` with an `agent_id` that has no claims returns `{"success": True, "released": 0}` — the tool must pass this through as a success, not an error.

**Test impact**: `tests/test_coordination.py` does not yet have a server-level test for `codegiraffe_release`. New tests must be added covering claim-then-release, release-then-reclaim-by-other-agent, and no-op release.

### US4 — Rename `codegiraffe_status` to `codegiraffe_update_agent_status`

**Current state** (`server.py` lines 1918–1934):
- `codegiraffe_status(project_path, agent_id, status, task=None)` — updates agent coordination status
- Name conflicts visually with "graph health check" semantics

**Target state**: Rename to `codegiraffe_update_agent_status`. Python function rename only; body unchanged.

**Consistency check** — coordination tool names after all changes:
- `codegiraffe_claim` (unchanged)
- `codegiraffe_release` (new, US3)
- `codegiraffe_update_agent_status` (renamed from `codegiraffe_status`)
- `codegiraffe_agents` (unchanged — lists active agents)

FR-007 (consistent naming convention) is satisfied: claim/release/update/list are all coordination verbs, and the new name `update_agent_status` clearly scopes it to agent coordination.

**Callsites**: `grep` finds no callers of `codegiraffe_status` in the codebase beyond its definition in `server.py`. The `_coordinator.update_status()` call in the body is to the `CoordinationStore` method and is unchanged. No callers need updating.

**Test impact**: Any test asserting `hasattr(server, "codegiraffe_status")` or calling `codegiraffe_status` directly must be updated to `codegiraffe_update_agent_status`. Existing `test_coordination.py` tests only exercise `CoordinationStore` directly — not the server wrapper. New contract tests will cover the renamed tool signature.

### Tool Count Audit (FR-008)

| Change | Delta |
|---|---|
| Remove `codegiraffe_domains` | −1 |
| Add `codegiraffe_list_domains` | +1 |
| Add `codegiraffe_infer_domains` | +1 |
| Add `codegiraffe_add_domain` | +1 |
| Add `codegiraffe_remove_domain` | +1 |
| Remove `codegiraffe_restore` | −1 |
| Add `codegiraffe_release` | +1 |
| Rename `codegiraffe_status` | 0 |
| **Net** | **+3** |

Previous tool count: 37 (per CLAUDE.md v0.15.0 reference). New count: 40.

## Complexity Tracking

No constitution violations. All changes are surgical edits to a single file with corresponding test updates. No new abstractions, no new modules, no new dependencies.

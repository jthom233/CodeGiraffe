---

description: "Task list for API & DX Improvements (035)"
---

# Tasks: API & DX Improvements

**Input**: Design documents from `/specs/035-api-improvements/`
**Prerequisites**: plan.md (complete), spec.md (complete)
**Branch**: `035-api-improvements`

**Organization**: Tasks are grouped by user story. US1 and US2 have no shared file conflicts and can be worked in parallel. US3 and US4 both touch the multi-agent coordination section of `server.py` and must be done sequentially (or carefully merged). All US tests must be written and confirmed failing before implementation.

---

## Phase 1: Foundational — No shared infrastructure needed

This feature requires no new modules, no new dependencies, and no schema changes. All work is surgical edits to `src/codegiraffe/server.py` and test file updates. There is no blocking foundational phase — user stories can begin immediately.

**Checkpoint**: Environment confirmed, test suite green before any changes.

- [ ] T001 Confirm existing test suite passes on branch `035-api-improvements`: run `python -m pytest tests/ -x -q` and verify zero failures before touching any code

---

## Phase 2: User Story 1 — Focused Domain Management Tools (Priority: P1)

**Goal**: Replace the single `codegiraffe_domains(action=...)` tool with four focused tools: `codegiraffe_list_domains`, `codegiraffe_infer_domains`, `codegiraffe_add_domain`, `codegiraffe_remove_domain`. The old combined tool and the `_VALID_DOMAIN_ACTIONS` constant are deleted.

**Independent Test**: Each new tool can be called with only its required parameters and returns a string. The old `codegiraffe_domains` function is no longer importable from `codegiraffe.server`.

### Tests for User Story 1 — write FIRST, confirm FAILING before implementation

- [ ] T002 [P] [US1] In `tests/test_domains.py`: replace the `TestDomainContractTool` class (which tests the old combined tool) with a new `TestDomainToolContracts` class containing:
  - `test_list_domains_function_exists` — `hasattr(server, "codegiraffe_list_domains")`
  - `test_list_domains_accepts_only_project_path` — signature has exactly `project_path`, no `action`/`name`/`node_ids`
  - `test_infer_domains_function_exists` — `hasattr(server, "codegiraffe_infer_domains")`
  - `test_infer_domains_accepts_only_project_path` — signature has exactly `project_path`
  - `test_add_domain_function_exists` — `hasattr(server, "codegiraffe_add_domain")`
  - `test_add_domain_accepts_project_path_name_node_ids` — signature has `project_path`, `name`, `node_ids`
  - `test_remove_domain_function_exists` — `hasattr(server, "codegiraffe_remove_domain")`
  - `test_remove_domain_accepts_project_path_and_name` — signature has `project_path`, `name`
  - `test_old_combined_tool_is_gone` — `assert not hasattr(server, "codegiraffe_domains")`

- [ ] T003 [P] [US1] In `tests/test_domains.py`: replace `TestDomainInferAction` behavioral tests (currently calling `codegiraffe_domains(action=...)`) with a new `TestDomainToolBehavior` class that calls the four new tools directly:
  - `test_list_domains_returns_string_on_uninitialised_project` — calls `codegiraffe_list_domains(str(tmp_path))`
  - `test_infer_domains_returns_string` — inits project, calls `codegiraffe_infer_domains`
  - `test_add_domain_creates_domain` — inits project, calls `codegiraffe_add_domain(path, "test-domain", node_id)`
  - `test_remove_domain_removes_domain` — adds then removes via new tools, verifies removal
  - `test_add_domain_missing_name_returns_error` — calls `codegiraffe_add_domain(path, "", node_id)`, expects error
  - `test_add_domain_missing_node_ids_returns_error` — calls `codegiraffe_add_domain(path, "d", "")`, expects error
  - `test_remove_domain_missing_name_returns_error` — calls `codegiraffe_remove_domain(path, "")`, expects error

### Implementation for User Story 1

- [ ] T004 [US1] In `src/codegiraffe/server.py`: delete the `_VALID_DOMAIN_ACTIONS` constant (line 1087) and the entire `codegiraffe_domains` function (lines 1090–1189). This makes T002/T003 tests pass their "old tool is gone" assertion and confirms existing contract tests fail on the new tool names.

- [ ] T005 [US1] In `src/codegiraffe/server.py`: add `codegiraffe_list_domains` tool in place of the deleted function. Body extracts the `action == "list"` branch verbatim. Signature: `(project_path: str) -> str`. Wraps body in `with _graph_lock:`. No `_storage.save` call needed (read-only).

- [ ] T006 [US1] In `src/codegiraffe/server.py`: add `codegiraffe_infer_domains` tool after `codegiraffe_list_domains`. Body extracts the `action == "infer"` branch verbatim, including the `_storage.save(project_path, graph.to_data())` call. Signature: `(project_path: str) -> str`.

- [ ] T007 [US1] In `src/codegiraffe/server.py`: add `codegiraffe_add_domain` tool after `codegiraffe_infer_domains`. Body extracts the `action == "add"` branch verbatim, including guard for empty `name`, comma-split of `node_ids`, warning loop, and `_storage.save`. Signature: `(project_path: str, name: str, node_ids: str) -> str`.

- [ ] T008 [US1] In `src/codegiraffe/server.py`: add `codegiraffe_remove_domain` tool after `codegiraffe_add_domain`. Body extracts the `action == "remove"` branch verbatim, including guard for empty `name` and `_storage.save`. Signature: `(project_path: str, name: str) -> str`.

**Checkpoint**: Run `python -m pytest tests/test_domains.py -v`. All US1 tests pass. Old contract tests are gone. Run full suite to confirm no regressions.

---

## Phase 3: User Story 2 — Remove Broken Restore Tool (Priority: P1)

**Goal**: Delete `codegiraffe_restore` from the MCP tool surface entirely. No aliases. No replacement.

**Independent Test**: `codegiraffe_restore` is not importable from `codegiraffe.server`. The old test asserting "not yet supported" is replaced with a test asserting the tool does not exist.

### Tests for User Story 2 — write FIRST, confirm FAILING before implementation

- [ ] T009 [P] [US2] In `tests/test_server_integration.py`: remove `codegiraffe_restore` from the import list at the top of the file (line 35). Add a new test class `TestRestoreRemoved`:
  - `test_restore_tool_is_not_on_server_module` — `assert not hasattr(server_module, "codegiraffe_restore")`
  - `test_restore_tool_not_importable` — `with pytest.raises(ImportError): from codegiraffe.server import codegiraffe_restore`
  Delete the existing `TestRestore` class (lines 170–177) which asserts "not yet supported" is returned.

### Implementation for User Story 2

- [ ] T010 [US2] In `src/codegiraffe/server.py`: delete the `codegiraffe_restore` function and its `@mcp.tool()` decorator (lines 2029–2056). No other changes required — `_version_store` is still used by `codegiraffe_history`, `codegiraffe_diff`, and `codegiraffe_snapshot`.

**Checkpoint**: Run `python -m pytest tests/test_server_integration.py -v`. `TestRestoreRemoved` tests pass. Run full suite to confirm no regressions.

---

## Phase 4: User Story 3 — Expose Agent Release Tool (Priority: P2)

**Goal**: Add `codegiraffe_release(project_path, agent_id)` as a new `@mcp.tool()` that delegates to the existing `CoordinationStore.release()`. Agents can release their own claims; the implementation is inherently own-claims-only because `release()` filters by `agent_id`.

**Independent Test**: Claim a node as agent-A, release it, then claim the same node as agent-B and verify agent-B succeeds immediately.

**Dependency**: US3 can be worked in parallel with US1 and US2. However, US3 edits the multi-agent coordination section of `server.py` (around line 1917), while US4 also edits the `codegiraffe_status` definition immediately after the claim/agents block. If done by the same developer, complete US3 before US4 to avoid conflicts.

### Tests for User Story 3 — write FIRST, confirm FAILING before implementation

- [ ] T011 [P] [US3] In `tests/test_coordination.py` (or a new `tests/test_server_coordination.py`): add a `TestCoordinationReleaseServerTool` class:
  - `test_release_tool_exists` — `assert hasattr(server_module, "codegiraffe_release")`
  - `test_release_tool_accepts_project_path_and_agent_id` — inspect signature, confirm `project_path` and `agent_id` present, no extra required params
  - `test_release_returns_json_string` — call `codegiraffe_release(str(tmp_path), "agent-x")` on uninitialized path, result is a `str` containing JSON with `"success"` key
  - `test_release_with_active_claim_succeeds` — init project, claim nodes as agent-1, release as agent-1, verify `released == 1`
  - `test_release_allows_other_agent_to_reclaim` — init project, claim nodes as agent-1, release as agent-1, claim same nodes as agent-2, verify agent-2 claim succeeds
  - `test_release_with_no_claims_returns_zero_not_error` — call release without any prior claim, verify `released == 0` and `success == True`

### Implementation for User Story 3

- [ ] T012 [US3] In `src/codegiraffe/server.py`: insert `codegiraffe_release` tool after `codegiraffe_claim` (line 1915) and before the current `codegiraffe_status` definition (line 1918). Body:
  ```python
  @mcp.tool()
  def codegiraffe_release(project_path: str, agent_id: str) -> str:
      """Release all claims held by an agent, allowing other agents to claim those nodes.

      Call this when your work is complete or if you need to abandon a task.
      Releases are immediate — other agents can claim the freed nodes right away.

      If this agent has no active claims, the call succeeds with a released count of 0.
      Agents can only release their own claims (identified by agent_id).
      """
      try:
          result = _coordinator.release(project_path, agent_id)
          return json.dumps(result, indent=2)
      except Exception as exc:
          return f"Error releasing claims: {exc}"
  ```

**Checkpoint**: Run `python -m pytest tests/test_coordination.py -v` (or `tests/test_server_coordination.py`). US3 tests pass. Run full suite to confirm no regressions.

---

## Phase 5: User Story 4 — Unambiguous Tool Name for Status Update (Priority: P3)

**Goal**: Rename `codegiraffe_status` to `codegiraffe_update_agent_status`. Clean rename — no alias, no backward compat shim.

**Independent Test**: `codegiraffe_status` does not exist on the server module. `codegiraffe_update_agent_status` exists, has the same signature (`project_path`, `agent_id`, `status`, `task=None`), and behaves identically.

**Dependency**: This edits the same coordination section of `server.py` as US3. Complete US3 (T011–T012) before starting US4 if done sequentially.

### Tests for User Story 4 — write FIRST, confirm FAILING before implementation

- [ ] T013 [P] [US4] In `tests/test_coordination.py` (or `tests/test_server_coordination.py`): add a `TestAgentStatusRenameContract` class:
  - `test_old_status_tool_is_gone` — `assert not hasattr(server_module, "codegiraffe_status")`
  - `test_update_agent_status_tool_exists` — `assert hasattr(server_module, "codegiraffe_update_agent_status")`
  - `test_update_agent_status_accepts_project_path_agent_id_status` — inspect signature, confirm `project_path`, `agent_id`, `status` are present
  - `test_update_agent_status_task_param_is_optional` — inspect signature, confirm `task` has a default of `None`
  - `test_update_agent_status_works_after_claim` — init project, claim nodes as agent-1, call `codegiraffe_update_agent_status(path, "agent-1", "done")`, verify JSON result has `success == True`

### Implementation for User Story 4

- [ ] T014 [US4] In `src/codegiraffe/server.py`: rename the Python function `codegiraffe_status` to `codegiraffe_update_agent_status` (line 1919 after US3 insertion shifts lines slightly). Update the function name only — body and all internal calls (`_coordinator.update_status(...)`) remain unchanged. The `@mcp.tool()` decorator automatically picks up the new Python function name as the tool name.

  Update the docstring to replace "Update an agent's status" with "Update an agent's coordination status (active, done, or blocked)." to make the coordination context explicit.

**Checkpoint**: Run `python -m pytest tests/test_coordination.py -v`. US4 tests pass. `codegiraffe_status` is absent, `codegiraffe_update_agent_status` present with correct behavior.

---

## Phase 6: Cross-Cutting Verification

**Purpose**: Confirm the full test suite passes, tool count is documented, and no regressions were introduced.

- [ ] T015 [P] Run full test suite: `python -m pytest tests/ -v` — must pass with 0 failures. Fix any test that still imports the removed/renamed tools.

- [ ] T016 [P] Verify tool count: confirm `server.py` exposes 40 `@mcp.tool()` decorated functions (was 37). Count via `grep -c "@mcp.tool()" src/codegiraffe/server.py` and assert result is 40.

- [ ] T017 [P] Update `CLAUDE.md` "Recent Changes" section: add a v0.16.0 entry documenting the 4 domain tools (replacing 1), removal of restore stub, new release tool, and status rename. Update the tool count reference from 37 to 40.

---

## Dependencies & Execution Order

### Phase Dependencies

- **T001 (baseline)**: No dependencies — run first
- **US1 (T002–T008)**: Depends on T001. Can proceed in parallel with US2 (different test lines, same `test_domains.py` class replacement is isolated)
- **US2 (T009–T010)**: Depends on T001. Can proceed in parallel with US1
- **US3 (T011–T012)**: Depends on T001. Edits coordination section of `server.py` — coordinate with US4 if parallel
- **US4 (T013–T014)**: Depends on T001. Must come AFTER US3 if editing `server.py` sequentially (same coordination section)
- **Phase 6 (T015–T017)**: Depends on US1, US2, US3, US4 all complete

### User Story Dependencies

- **US1 and US2**: Fully independent — different functions, different test files
- **US3 and US4**: Independent in scope, but both touch the 30-line coordination block in `server.py`. If done by the same developer, do US3 before US4 to avoid edit conflicts at line ~1917
- **US4** has a soft dependency on US3: once `codegiraffe_release` is inserted, line numbers shift; update line references in US4 accordingly (use function name search, not line numbers)

### Within Each User Story

1. Write tests (confirm FAIL)
2. Delete/rename/add the tool definition(s)
3. Confirm tests pass
4. Run full suite to catch regressions before moving to next story

### Parallel Opportunities

- T002 and T003 (US1 test writing) can run in parallel — they edit different class blocks in `test_domains.py`
- T009 (US2 test writing) can run in parallel with T002/T003 — different test file
- T011 and T013 (US3/US4 test writing) can run in parallel — they are new test classes with no file conflict
- T004 through T008 (US1 implementation) must run sequentially — each depends on the previous deletion/addition
- T005, T006, T007, T008 can be written in parallel since they each add a distinct function with no shared state, but they must be inserted into `server.py` in order (list → infer → add → remove) to match the logical grouping

---

## Implementation Strategy

### Single-Developer Sequential Order

1. T001 — confirm baseline green
2. T002, T003 — write US1 tests (fail)
3. T004 — delete old combined tool (US1 tests now partially fail as expected)
4. T005–T008 — add four new tools (US1 tests pass)
5. T009 — write US2 tests (fail: `codegiraffe_restore` still exists)
6. T010 — delete restore tool (US2 tests pass)
7. T011 — write US3 tests (fail: no release tool)
8. T012 — add release tool (US3 tests pass)
9. T013 — write US4 tests (fail: status tool still named old name)
10. T014 — rename status tool (US4 tests pass)
11. T015–T017 — full verification and doc update

### Parallel Strategy (2 developers)

**Developer A** handles US1 (T002–T008) and US2 (T009–T010) sequentially.
**Developer B** handles US3 (T011–T012) then US4 (T013–T014) sequentially.
Both work in `server.py` but in non-overlapping regions:
- Developer A: lines 1087–1189 (domains section) and lines 2029–2056 (restore section)
- Developer B: lines ~1896–1950 (coordination section)
Merge before Phase 6 (T015–T017).

---

## Notes

- [P] tasks = different files or non-overlapping regions, no dependencies
- TDD order is mandatory per Constitution VI (Test-First NON-NEGOTIABLE)
- The `@mcp.tool()` decorator uses the Python function name as the MCP tool name — no explicit name parameter needed
- `_coordinator.release()` already enforces own-agent-only semantics by filtering on `agent_id` — no extra guard needed in the server wrapper
- `domains.py` and `coordination.py` are read-only for this feature — all changes are in `server.py` and test files
- Do NOT add backward-compatibility aliases for removed or renamed tools (per spec edge cases section)
- Line numbers in `server.py` will shift as tools are added/deleted — use function-name search (`grep -n "def codegiraffe_"`) rather than line numbers when navigating during implementation

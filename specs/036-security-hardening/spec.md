# Feature Specification: Security Hardening

**Feature Branch**: `036-security-hardening`
**Created**: 2026-02-25
**Status**: Draft
**Input**: User description: "Phase 5: Security Hardening — Dashboard path validation, symlink protection in scanner, subprocess timeouts, XSS fixes in dashboard, depth parameter bounds, and test infrastructure consolidation."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Dashboard Cannot Be Used to Scan Arbitrary Paths (Priority: P1)

When the web dashboard accepts a project path for initialization or querying, it must only operate on projects that have already been initialized through the MCP tool interface. Today, the dashboard's HTTP API accepts arbitrary file system paths, allowing any local process to trigger a scan of sensitive directories (e.g., `/etc`, `/home`). After this change, the dashboard only serves graphs for projects that were explicitly initialized via MCP tools.

**Why this priority**: This is the highest-severity security issue in the dashboard. Although the server binds to localhost only, any local process (including a browser tab) can send requests. Preventing arbitrary path scanning eliminates the primary attack surface.

**Independent Test**: Can be tested by sending an HTTP request to the dashboard API with an arbitrary path (e.g., `/etc`) and verifying it is rejected with a clear error, while a previously-initialized project path succeeds.

**Acceptance Scenarios**:

1. **Given** a project initialized via MCP tools, **When** the dashboard receives a request for that project's graph, **Then** it serves the graph normally.
2. **Given** a path that was never initialized, **When** the dashboard receives a request to scan or query that path, **Then** the request is rejected with an error indicating the project must be initialized first.
3. **Given** a malicious path (e.g., `/etc/passwd`, `../../sensitive`), **When** sent to the dashboard API, **Then** the request is rejected before any file system access occurs.

---

### User Story 2 - Scanner Stays Within Project Boundaries (Priority: P1)

When the scanner walks a project directory to discover files, it must not follow symbolic links that lead outside the project root. Today, the scanner follows symlinks transparently, allowing a malicious repository to include symlinks pointing to sensitive directories. After this change, symlinks that resolve outside the project root are skipped.

**Why this priority**: Symlink traversal is a well-known attack vector. A cloned repository could contain a symlink pointing to `~/.ssh/` or `/etc/`, causing the scanner to read and index those files. While the data goes into a graph (not exfiltrated), it represents unauthorized file access.

**Independent Test**: Can be tested by creating a project with a symlink pointing outside the project root and verifying the scanner skips it with a warning.

**Acceptance Scenarios**:

1. **Given** a project with a symlink pointing to a directory outside the project, **When** scanned, **Then** the symlink target is not traversed and a warning is logged.
2. **Given** a project with a symlink pointing to a file outside the project, **When** scanned, **Then** the symlinked file is not read.
3. **Given** a project with a symlink pointing to a directory inside the project, **When** scanned, **Then** the symlink is followed normally (internal symlinks are fine).
4. **Given** a project with no symlinks, **When** scanned, **Then** behavior is identical to before (no regression).

---

### User Story 3 - External Commands Have Timeouts (Priority: P2)

When the system executes external commands (e.g., querying git history), the command must complete within a reasonable time or be terminated. Today, external commands have no timeout — a hung process blocks the server indefinitely. After this change, all external commands have configurable timeouts with clear error messages on expiration.

**Why this priority**: A hung external command (e.g., git on a corrupt repo or slow network filesystem) blocks the entire MCP server with no recovery path. Timeouts prevent indefinite hangs and provide actionable error messages.

**Independent Test**: Can be tested by mocking a slow-responding external command and verifying it is terminated after the timeout with a clear error returned to the caller.

**Acceptance Scenarios**:

1. **Given** an external command that completes quickly, **When** executed, **Then** it returns results normally with no timeout interference.
2. **Given** an external command that exceeds the timeout, **When** the timeout fires, **Then** the command is terminated and a clear error message is returned indicating the timeout.
3. **Given** a timeout error, **When** the error message is inspected, **Then** it indicates which command timed out and suggests possible causes.

---

### User Story 4 - Dashboard Is Safe Against Content Injection (Priority: P2)

When the dashboard displays component names, types, and metadata from the architecture graph, all content must be properly escaped to prevent content injection. Today, certain display areas in the dashboard insert graph-derived strings into the page without escaping, allowing crafted component names to inject content. After this change, all graph-derived content is escaped before display.

**Why this priority**: While the dashboard is localhost-only, it renders data from scanned repositories. A malicious repository could craft class or function names containing injection payloads that execute when a developer views the dashboard.

**Independent Test**: Can be tested by creating a graph with node names containing special characters (e.g., angle brackets, quotes, script tags) and verifying they are rendered as escaped text, not interpreted as markup.

**Acceptance Scenarios**:

1. **Given** a graph with a node labeled `<img src=x onerror=alert(1)>`, **When** the dashboard renders the type distribution panel, **Then** the label is displayed as escaped text, not executed.
2. **Given** a graph with nodes containing `&`, `<`, `>`, `"`, `'` in their names, **When** displayed in the dashboard, **Then** all characters are properly escaped.
3. **Given** a graph with normal node names (no special characters), **When** displayed, **Then** the dashboard looks and behaves identically to before (no regression).

---

### User Story 5 - Bounded Resource Consumption (Priority: P3)

When tools accept depth or scope parameters, those parameters must have reasonable upper bounds to prevent excessive resource consumption. Today, parameters like graph traversal depth and git history depth have no upper limits — an agent can request `depth=1000000`, causing the system to run for hours or exhaust memory.

**Why this priority**: Unbounded parameters are a denial-of-service vector. While typically caused by agent error rather than malice, the impact is the same — the server becomes unresponsive. Upper bounds are a simple safeguard.

**Independent Test**: Can be tested by calling tools with extremely large parameter values and verifying they are capped to the maximum rather than rejected.

**Acceptance Scenarios**:

1. **Given** a tool with a depth parameter, **When** called with a value exceeding the maximum, **Then** the value is silently capped to the maximum (not rejected).
2. **Given** a tool with a depth parameter, **When** called with a normal value within bounds, **Then** the value is used as-is.
3. **Given** parameters at their maximum values, **When** the operation runs, **Then** it completes in reasonable time (under 60 seconds for any single tool call).

---

### User Story 6 - Consolidated Test Infrastructure (Priority: P3)

When developers write tests for the project, shared test utilities must be centralized to prevent duplication and inconsistency. Today, the server state reset fixture is duplicated across 6 test files with slight variations, and git helper functions are duplicated across 3 test files. After this change, shared fixtures live in one place.

**Why this priority**: Test infrastructure duplication leads to subtle cross-test pollution when one copy is updated but others are not. Consolidation prevents this class of bugs and reduces boilerplate for new test files.

**Independent Test**: Can be tested by verifying that all test files use the centralized fixtures and that removing any local duplicates does not break tests.

**Acceptance Scenarios**:

1. **Given** the test suite, **When** searching for the server state reset fixture, **Then** it exists in exactly one place (the shared fixture file) and is used by all server test files.
2. **Given** the test suite, **When** searching for git helper functions, **Then** they exist in exactly one shared location and are imported by all git-related test files.
3. **Given** the consolidated fixtures, **When** the full test suite is run, **Then** all tests pass with no cross-test state pollution.

---

### Edge Cases

- What happens when a symlink forms a circular loop (A -> B -> A)? (Should be detected and skipped — no infinite traversal.)
- What happens when the timeout fires during a critical cleanup operation? (The timeout should only apply to the external command, not to post-command cleanup.)
- What happens when a graph contains Unicode characters in node names? (Should be escaped correctly — not corrupted or mojibake'd.)
- What happens when all external commands in a workflow time out? (Each timeout should be reported independently — no cascading failure.)
- What happens when the maximum depth cap changes in a future version? (The cap should be a named constant, not a magic number.)

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The dashboard API MUST reject project paths that have not been previously initialized via MCP tools.
- **FR-002**: The scanner MUST skip symlinks that resolve to locations outside the project root directory.
- **FR-003**: The scanner MUST follow symlinks that resolve to locations within the project root directory.
- **FR-004**: All external command executions MUST have a timeout (default: 30 seconds).
- **FR-005**: Timeout errors MUST include the command that timed out and the timeout duration in the error message.
- **FR-006**: All graph-derived content displayed in the dashboard MUST be escaped to prevent content injection.
- **FR-007**: Graph traversal depth parameters MUST be capped at a documented maximum value.
- **FR-008**: Git history depth parameters MUST be capped at a documented maximum value.
- **FR-009**: The server state reset test fixture MUST be defined in exactly one shared location and used by all test files that need it.
- **FR-010**: Git test helper functions MUST be defined in exactly one shared location and imported by all test files that need them.
- **FR-011**: Tests with known-failing status MUST be marked with the appropriate test framework annotation so they are tracked in test results.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Zero unauthorized file system access — the dashboard rejects 100% of non-initialized project paths.
- **SC-002**: Zero symlink escapes — the scanner skips 100% of symlinks pointing outside the project root.
- **SC-003**: Zero indefinite hangs — all external commands terminate within the configured timeout.
- **SC-004**: Zero unescaped graph content in the dashboard — all special characters are properly neutralized.
- **SC-005**: Zero duplicate test fixtures — the server reset fixture exists in exactly one file and is used by all consumers.
- **SC-006**: All existing tests pass with no regressions after consolidation.

## Assumptions

- The 30-second default timeout for external commands is sufficient for normal operations. Users with very large repositories or slow storage may need to increase this, but the default should cover 99% of cases.
- Depth parameter caps are generous (e.g., 1000 for graph traversal, 500 for git history) — they prevent abuse without limiting legitimate use.
- Dashboard path validation uses the set of initialized projects maintained in server memory. This means a server restart clears the allowed list until projects are re-initialized.
- Content escaping in the dashboard applies the same function already used in other parts of the dashboard, just extended to the currently-unescaped areas.

## Scope Boundaries

**In scope**:
- Dashboard path validation against initialized projects
- Symlink boundary checking in the scanner
- Subprocess timeouts for all git commands
- XSS escaping for unescaped dashboard areas
- Upper bounds on depth/scope parameters
- Consolidating duplicated test fixtures
- Marking known-failing tests appropriately

**Out of scope**:
- Dashboard authentication or authorization (localhost-only is the security model)
- CORS headers or CSP policies for the dashboard
- Dependency version pinning or supply chain security
- New security features beyond hardening existing surfaces

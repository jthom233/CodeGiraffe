# Feature Specification: API & Developer Experience Improvements

**Feature Branch**: `035-api-improvements`
**Created**: 2026-02-25
**Status**: Draft
**Input**: User description: "Phase 4: API & DX — Remove broken restore tool, split domains action-enum into 4 focused tools, expose the agent release tool, rename ambiguous status tool, and add consistent response formatting."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Focused Domain Management Tools (Priority: P1)

When an AI agent needs to manage architecture domains (groups of related components), each operation should be a distinct tool with only the parameters it needs. Today, a single tool handles four different actions (list, infer, add, remove) via an `action` parameter. Agents must know the action vocabulary and which parameters apply to which action — leading to frequent errors and confusion. After this change, each domain operation is a separate tool with clear, minimal parameters.

**Why this priority**: This is the most impactful DX issue. The action-enum anti-pattern forces agents to learn hidden parameter requirements, produces confusing validation errors at call time, and violates the principle that each tool should do one thing well. Splitting into focused tools directly improves agent success rate.

**Independent Test**: Can be tested by calling each new domain tool with only its required parameters and verifying it succeeds, then calling with missing required parameters and verifying it returns a clear error.

**Acceptance Scenarios**:

1. **Given** an initialized graph, **When** an agent calls the domain listing tool with no extra parameters, **Then** it returns all domains.
2. **Given** an initialized graph, **When** an agent calls the domain inference tool, **Then** it automatically groups related components and returns the inferred domains.
3. **Given** an initialized graph, **When** an agent calls the domain creation tool with a name and node IDs, **Then** a new domain is created containing those nodes.
4. **Given** an existing domain, **When** an agent calls the domain removal tool with the domain name, **Then** the domain is removed.
5. **Given** the old combined domain tool, **When** the tool surface is inspected, **Then** the old tool is no longer present — only the four new tools exist.

---

### User Story 2 - No Broken Tools in the Surface (Priority: P1)

When an AI agent discovers and calls tools, every tool in the surface must either work or not be present. Today, the graph restore tool is publicly exposed but always returns an error because the underlying feature is unimplemented. This wastes agent time and erodes trust in the entire tool surface. After this change, unimplemented tools are removed from the surface entirely.

**Why this priority**: A permanently-failing tool is worse than a missing tool. Agents will retry, attempt workarounds, and lose context trying to make it work. Removing it immediately improves reliability for every agent interaction.

**Independent Test**: Can be tested by listing all available tools and verifying none of them are stubs that always fail.

**Acceptance Scenarios**:

1. **Given** the tool surface, **When** an agent lists available tools, **Then** the restore tool is not present.
2. **Given** an agent that previously relied on restore, **When** it attempts to call it, **Then** it receives a "tool not found" error rather than a misleading "not yet supported" message from inside the tool.

---

### User Story 3 - Agents Can Release Claimed Resources (Priority: P2)

When an AI agent claims ownership of graph nodes for coordination (to prevent conflicting edits by other agents), it must be able to release those claims when done. Today, the internal release mechanism exists but is not exposed as a tool. Agents must wait for claims to expire via timeout, creating stale lock problems and blocking other agents unnecessarily.

**Why this priority**: Multi-agent coordination requires both claim and release. Without release, the coordination system degrades to timeout-based expiration, which either blocks too long (high TTL) or provides insufficient protection (low TTL). Exposing release completes the coordination lifecycle.

**Independent Test**: Can be tested by claiming a node, releasing it, and verifying another agent can immediately claim the same node.

**Acceptance Scenarios**:

1. **Given** an agent has claimed a set of nodes, **When** it calls the release tool with those node IDs, **Then** the claims are removed immediately.
2. **Given** agent A has claimed nodes and then released them, **When** agent B attempts to claim the same nodes, **Then** agent B's claim succeeds immediately without waiting for a timeout.
3. **Given** an agent calls release on nodes it has not claimed, **When** the call completes, **Then** a clear message indicates no claims were found to release (not an error).

---

### User Story 4 - Unambiguous Tool Names (Priority: P3)

When an AI agent browses the tool surface, tool names must clearly indicate their purpose. Today, the agent coordination status update tool has a generic name that could be confused with a graph health-check. After this change, coordination tools form a coherent group with descriptive names.

**Why this priority**: Naming ambiguity causes agents to call the wrong tool, wasting time and producing confusing results. Clear naming is a low-effort, high-impact improvement.

**Independent Test**: Can be tested by verifying that tool names are self-descriptive — an agent should be able to infer the correct tool from its name alone without reading the full description.

**Acceptance Scenarios**:

1. **Given** the tool surface, **When** an agent looks for coordination tools, **Then** all three (claim, update status, list agents) have names that clearly indicate they are agent coordination tools.
2. **Given** the renamed status tool, **When** called with the old name, **Then** it is not found (clean rename, no alias).

---

### Edge Cases

- What happens when an agent calls the old combined domains tool after the split? (Should receive "tool not found" — no backward compatibility shim.)
- What happens when an agent releases claims owned by a different agent? (Should be rejected — agents can only release their own claims.)
- What happens when the tool surface is queried by an LLM that cached old tool descriptions? (LLMs will re-discover tools on the next session — no stale cache issue at the MCP protocol level.)

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The combined domain management tool MUST be replaced with four separate tools: list domains, infer domains, add domain, and remove domain.
- **FR-002**: Each domain tool MUST accept only the parameters relevant to its specific operation.
- **FR-003**: The non-functional restore tool MUST be removed from the tool surface entirely.
- **FR-004**: An agent release tool MUST be added that exposes the existing internal release mechanism.
- **FR-005**: The release tool MUST only allow agents to release their own claims, not other agents' claims.
- **FR-006**: The agent status update tool MUST be renamed to clearly indicate it is an agent coordination tool, distinct from graph status queries.
- **FR-007**: All coordination tools (claim, release, update, list) MUST follow a consistent naming convention that groups them visually.
- **FR-008**: The total tool count change MUST be documented (net +3 from domain split, +1 from release, -1 from restore removal = net +3).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Agent success rate for domain operations improves — zero "missing required parameter" errors when agents follow tool descriptions.
- **SC-002**: Zero permanently-failing tools in the surface — every exposed tool either succeeds with valid input or returns a meaningful, actionable error.
- **SC-003**: Agent coordination lifecycle is complete — claim, work, release flow works without relying on timeout expiration.
- **SC-004**: All existing tests pass with tool name updates reflected.

## Assumptions

- Removing the restore tool is acceptable because it has never worked. Users who need restore functionality will get it in a future phase when snapshot-based versioning is implemented.
- The domain tool split increases the tool count by 3 (1 becomes 4), but the improved usability outweighs the surface size increase.
- Tool renaming is a breaking change for any agent that hardcoded the old name, but MCP tools are discovered dynamically, so most agents will adapt automatically on their next session.

## Scope Boundaries

**In scope**:
- Splitting the domains tool into 4 focused tools
- Removing the non-functional restore tool
- Adding the agent release tool
- Renaming the agent status tool for clarity

**Out of scope**:
- Response format standardization (JSON vs Markdown consistency — future improvement)
- Adding new tools beyond what's described
- Implementing actual restore/snapshot functionality
- Changes to tool parameter types or response structures beyond the tools listed

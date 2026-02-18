# Feature Specification: Large-Graph Dashboard Visualization

**Feature Branch**: `013-sigma-dashboard`
**Created**: 2026-02-18
**Status**: Draft

## User Scenarios & Testing *(mandatory)*

### User Story 1 - View Full Architecture Graph (Priority: P1)

A developer runs Code Giraffe against a large codebase (30,000+ nodes) and opens the dashboard. The graph loads and renders interactively within a few seconds — they can pan, zoom, and explore the full architecture without the browser freezing or timing out.

**Why this priority**: This is the core capability that is broken today. Everything else is secondary if the graph cannot render.

**Independent Test**: Initialize a 30k+ node project, open the dashboard, verify the graph renders within 5 seconds and pan/zoom remain responsive at 30fps.

**Acceptance Scenarios**:

1. **Given** a project with 33,000+ nodes has been initialized, **When** the dashboard loads, **Then** the graph renders within 5 seconds and is interactive (pan/zoom fluid, no browser hang)
2. **Given** the graph is rendered, **When** the user pans and zooms, **Then** the viewport updates without visible lag
3. **Given** a project with fewer than 1,500 nodes, **When** the dashboard loads, **Then** behavior is identical to today (no regression)

---

### User Story 2 - Layout Persists Across Sessions (Priority: P2)

A developer who has already opened the dashboard once finds that the graph layout is pre-computed and stored — subsequent loads are instant rather than requiring layout recalculation.

**Why this priority**: Without persistent layout, every dashboard open triggers expensive computation. Pre-computation makes the tool practical for daily use.

**Independent Test**: Initialize a project, open dashboard (layout computed), close and reopen — verify second load renders without re-running layout.

**Acceptance Scenarios**:

1. **Given** layout has been computed during project initialization, **When** the dashboard is opened, **Then** nodes appear in their pre-computed positions immediately
2. **Given** layout coordinates are stored, **When** the project is re-scanned (`sync`), **Then** layout is recomputed to reflect the new graph structure
3. **Given** the layout library is not installed, **When** initialization runs, **Then** the graph still loads using a fallback arrangement (no error, no crash)

---

### User Story 3 - Interactive Node Exploration (Priority: P3)

A developer clicks a node in the graph and sees a detail panel with the node's type, file path, metadata, and connected edges. They can filter by node type or path prefix to focus on a specific area of the codebase.

**Why this priority**: Visualization without interaction is a static image. Click-to-detail and filtering are what make the dashboard useful for architectural discovery.

**Independent Test**: Load any graph, click a node, verify detail panel opens with correct data; apply a path prefix filter, verify only matching nodes remain visible.

**Acceptance Scenarios**:

1. **Given** the graph is rendered, **When** a user clicks a node, **Then** a detail panel opens showing node ID, type, label, file path, and connected edges
2. **Given** the graph is rendered, **When** a user types a path prefix filter and applies it, **Then** only nodes matching that prefix are shown
3. **Given** the graph is rendered, **When** a user searches by node name, **Then** matching nodes are highlighted or isolated
4. **Given** the graph is rendered, **When** a user double-clicks a node, **Then** the view zooms into that node's immediate neighborhood

---

### User Story 4 - Export and Share (Priority: P4)

A developer exports the current graph view as a PNG image to share with teammates or include in documentation.

**Why this priority**: Sharing is a common workflow; PNG export is the minimum viable sharing mechanism.

**Independent Test**: Load a graph, click PNG export, verify an image file is downloaded.

**Acceptance Scenarios**:

1. **Given** a graph is rendered, **When** the user clicks Export PNG, **Then** a PNG image of the current viewport is downloaded

---

### Edge Cases

- What happens when a project has zero nodes (empty graph)?
- What happens when the layout library is not installed on first init?
- What happens when the browser does not support WebGL?
- What happens when the graph has nodes but no edges?
- What happens when a node's file path contains special characters or very long paths?
- What happens when max_nodes is set to 0 (no limit) on a 33k-node graph?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The dashboard MUST render graphs of 30,000+ nodes interactively (pan, zoom, click) within 5 seconds of page load
- **FR-002**: Layout coordinates MUST be computed once during project initialization and stored alongside the graph data
- **FR-003**: Layout computation MUST be an optional capability — if the layout library is absent, the dashboard MUST fall back to a fast positional arrangement without error
- **FR-004**: The dashboard MUST preserve all existing interactive features: node detail panel, edge tooltip on hover, search by name, filter by node type, filter by path prefix, configurable node limit, fit/layout/export toolbar
- **FR-005**: Clicking a node MUST open a detail panel showing: node ID, type, label, file path, manual flag, metadata, and lists of incoming and outgoing edges
- **FR-006**: The graph MUST display node type visually (distinct color per type for at least 15 types)
- **FR-007**: The graph MUST display edge type visually (distinct color per edge type for at least 12 types)
- **FR-008**: The dashboard MUST auto-load the graph when opened with a project path in the URL
- **FR-009**: A truncation banner MUST inform the user when the displayed graph is a subset of the full graph
- **FR-010**: The dashboard MUST be deliverable as a single self-contained HTML page served from the existing Python server — no external file dependencies, no build toolchain required
- **FR-011**: The graph renderer MUST gracefully fall back to a basic arrangement when pre-computed layout coordinates are unavailable
- **FR-012**: Project re-scan MUST trigger layout recomputation so stored coordinates stay current

### Key Entities

- **Layout Coordinates**: Per-node `x, y` position values computed from the graph topology and stored alongside existing graph data
- **Graph Renderer**: The client-side visualization engine loaded from a public CDN — must support WebGL rendering, event-driven node interaction, and per-node/edge appearance customization

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A 33,000-node graph renders and is interactive within 5 seconds of opening the dashboard on a modern laptop
- **SC-002**: Pan and zoom operations on a 33,000-node graph complete without visible lag (sub-100ms response)
- **SC-003**: All existing dashboard features (detail panel, search, filters, export, toolbar) work identically on graphs of any size
- **SC-004**: Layout computation runs once per initialization/sync and is not repeated on subsequent dashboard opens
- **SC-005**: The dashboard loads and displays a graph on any browser that supports WebGL (covers 95%+ of modern browsers)
- **SC-006**: No regression on graphs with fewer than 1,500 nodes — existing behavior is fully preserved
- **SC-007**: The fallback path (no layout library installed) produces a usable (if less organized) graph without errors

## Assumptions

- The target rendering library (Sigma.js v3) and its data companion (graphology) are both available as CDN-hosted UMD bundles and require no build toolchain
- Server-side layout computation using ForceAtlas2 with Barnes-Hut approximation is fast enough (under 5 minutes) for a 33k-node graph when run once during initialization
- WebGL support is assumed available in the user's browser; no Canvas 2D fallback is required
- Distinct node shapes (beyond circle/square) are out of scope for this feature — type differentiation via color is sufficient
- Dashed/dotted edge lines are out of scope — edge type differentiation via color is sufficient
- The existing `/api/graph`, `/api/node`, and `/api/subgraph` HTTP endpoints are unchanged in contract; only the `x`/`y` fields are added to the node response

## Out of Scope

- Animated graph transitions / physics simulation in the browser
- 3D graph rendering
- Collaborative / real-time graph updates
- Custom node shape authoring
- Dashed or dotted edge styles
- Server-side tile rendering

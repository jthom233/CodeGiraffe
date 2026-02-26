# Feature Specification: Data Integrity

**Feature Branch**: `033-data-integrity`
**Created**: 2026-02-25
**Status**: Draft
**Input**: User description: "Phase 2: Data Integrity — Fix confidence persistence across storage backends, atomic JSON writes, coverage tool persistence, and scanner correctness bugs."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Edge Confidence Survives Persistence (Priority: P1)

When an AI agent scans a codebase and the system assigns confidence scores to relationships (e.g., 0.9 for imports, 0.7 for duck-type interface satisfaction), those scores must survive when the graph is saved and reloaded. Today, confidence values are lost on round-trip through SQLite and Neo4j backends — all edges reload with a default confidence of 1.0, making confidence-based filtering and severity calculations meaningless.

**Why this priority**: Confidence scores are the foundation of trusted vs. exploratory analysis modes. Without persistence, any server restart resets all confidence to 1.0, making `min_confidence` filtering a no-op and inflating blast radius severity calculations. This silently degrades the quality of every query.

**Independent Test**: Can be tested by saving a graph with edges at various confidence levels (0.5, 0.7, 0.9) to each storage backend, reloading it, and verifying the confidence values match.

**Acceptance Scenarios**:

1. **Given** a graph with edges at confidence 0.5, 0.7, and 0.9, **When** saved to and reloaded from the SQLite backend, **Then** all confidence values are preserved exactly.
2. **Given** a graph with edges at various confidence levels, **When** saved to and reloaded from the Neo4j backend, **Then** all confidence values are preserved exactly.
3. **Given** a graph with default confidence (1.0) edges, **When** saved and reloaded, **Then** edges retain confidence 1.0 (backward compatibility with existing data).

---

### User Story 2 - Crash-Safe Graph Persistence (Priority: P2)

When the system saves the architecture graph to disk, the operation must be atomic — either the entire graph is written successfully, or the previous version is preserved. Today, a crash or power loss during a JSON save can leave a truncated, unrecoverable file, destroying the entire graph.

**Why this priority**: Data loss is catastrophic for a tool that builds an understanding of a codebase over time. A single bad save can destroy hours of accumulated annotations, manual edges, domain assignments, and scan history. Users should never lose their graph data due to a process interruption.

**Independent Test**: Can be tested by simulating a crash during a save operation (e.g., killing the process mid-write) and verifying the previous graph file remains intact and loadable.

**Acceptance Scenarios**:

1. **Given** a valid saved graph on disk, **When** a save operation is interrupted mid-write, **Then** the original graph file is still intact and loadable.
2. **Given** a save operation in progress, **When** it completes normally, **Then** the new graph replaces the old one atomically — there is no window where the file is partially written.
3. **Given** a fresh project with no existing graph file, **When** the first save is interrupted, **Then** no corrupt file is left behind (clean failure).

---

### User Story 3 - Coverage Annotations Persist (Priority: P3)

When an AI agent maps test coverage data to the architecture graph, the coverage annotations must be saved to storage so they survive across server restarts. Today, coverage annotations are applied to the in-memory graph but never written to disk, so they are lost on the next reload.

**Why this priority**: Coverage data enriches risk assessment and test suggestion tools. Without persistence, agents must re-run coverage mapping after every restart, which is wasteful and breaks workflows that span multiple sessions.

**Independent Test**: Can be tested by mapping coverage data to a graph, restarting the server, and verifying the coverage annotations are present on reload.

**Acceptance Scenarios**:

1. **Given** a graph with coverage data mapped from a coverage report, **When** the graph is reloaded from storage, **Then** all coverage annotations are present on the correct nodes.
2. **Given** a graph with existing coverage data, **When** new coverage data is mapped, **Then** the updated coverage replaces the old values and the new values persist across restarts.

---

### User Story 4 - Accurate Database Model Detection (Priority: P2)

When the scanner detects database model classes (e.g., ORM models with explicit table names), each model must be associated with its own table name. Today, a bug causes all models in a file to receive the table name of the first model, producing incorrect architecture data.

**Why this priority**: Incorrect table names cascade into wrong endpoint-to-table relationship edges, misleading blast radius analysis, and inaccurate migration plans. This is a silent correctness bug that affects any project using ORM models.

**Independent Test**: Can be tested by scanning a file containing multiple model classes with different table names and verifying each model node has the correct table name.

**Acceptance Scenarios**:

1. **Given** a file with two model classes (`User` with table `users` and `Order` with table `orders`), **When** the file is scanned, **Then** the `User` node references `users` and the `Order` node references `orders`.
2. **Given** a file with one model that has an explicit table name and another that uses the default, **When** scanned, **Then** each model gets its own correct table name.

---

### User Story 5 - No Duplicate Edges from Repeated Scans (Priority: P3)

When the scanner infers relationship edges, the deduplication mechanism must correctly identify and skip edges that already exist. Today, a type mismatch in the deduplication key causes certain edge types to accumulate duplicates on every scan, inflating the graph.

**Why this priority**: Duplicate edges inflate edge counts, skew centrality metrics, and waste storage. The bug is silent — the graph appears to work but analysis results are subtly wrong.

**Independent Test**: Can be tested by scanning a project twice and verifying the edge count is identical both times.

**Acceptance Scenarios**:

1. **Given** a project that has been scanned once, **When** it is scanned again with no file changes, **Then** the edge count remains exactly the same.
2. **Given** edges inferred by the scanner, **When** the same inference runs again, **Then** no new duplicate edges are created.

---

### Edge Cases

- What happens when a graph file saved by an older version has no confidence field on edges? (Should default to 1.0 — backward compatible.)
- What happens when disk space runs out during an atomic save? (The temporary file write should fail cleanly; the original file should remain untouched.)
- What happens when a coverage report references files that don't exist in the graph? (Should be silently skipped — no phantom nodes created.)
- What happens when a model class has no explicit table name and no default naming convention applies? (Should use the class name lowercased as a reasonable fallback.)

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The SQLite storage backend MUST persist the confidence value of every edge.
- **FR-002**: The Neo4j storage backend MUST persist the confidence value of every edge.
- **FR-003**: Edges loaded from storage files that predate the confidence field MUST default to confidence 1.0.
- **FR-004**: The JSON storage backend MUST write graph data atomically — either the full new version is written or the previous version is preserved.
- **FR-005**: The coverage mapping tool MUST save the graph to storage after applying coverage annotations.
- **FR-006**: The scanner MUST associate each detected model class with its own table name, not the table name of the first model in the file.
- **FR-007**: Edge deduplication keys MUST use consistent types — no mismatches between enum objects and string values.
- **FR-008**: Repeated scans of an unchanged project MUST produce an identical graph (idempotent scanning).

### Key Entities

- **Edge.confidence**: A float (0.0–1.0) indicating the system's confidence in the relationship. Must survive all storage round-trips.
- **Graph File**: The persisted representation of the architecture graph. Must never be left in a corrupt state due to interrupted writes.
- **Coverage Annotation**: Node-level metadata mapping source lines to test coverage data. Applied by the coverage tool and persisted with the graph.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Confidence values round-trip through all three storage backends with zero data loss — before-save and after-load values match exactly for 100% of edges.
- **SC-002**: Simulated crash during JSON save results in zero data loss — the previous graph file remains valid and loadable.
- **SC-003**: Coverage annotations persist across server restarts — 100% of mapped coverage data is present on reload.
- **SC-004**: Multi-model files produce correct per-model table names — verified against known test fixtures.
- **SC-005**: Scanning a project twice produces identical edge counts — zero duplicates introduced by repeated scans.
- **SC-006**: All existing tests continue to pass with no regressions.

## Assumptions

- Atomic writes use a write-to-temporary-file then rename pattern, which is atomic on POSIX systems. On Windows, this is best-effort but still safer than direct overwrite.
- The table name detection fix is scoped to the scanner's model detection logic, not to how table names propagate into edges.
- Edge deduplication fix is a targeted correction of the type mismatch, not a redesign of the deduplication system.

## Scope Boundaries

**In scope**:
- Adding confidence column to SQLite schema and Neo4j edge properties
- Implementing atomic writes for JSON storage
- Adding `_storage.save()` call to the coverage tool
- Fixing table name detection scope in the scanner
- Fixing edge type deduplication key mismatch

**Out of scope**:
- Multi-edge graph migration (Phase 1)
- Performance optimizations for storage (Phase 3)
- Scanner pipeline refactoring or parallelization (Phase 3)
- New storage backends or backend selection persistence

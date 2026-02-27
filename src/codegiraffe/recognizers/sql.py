"""SQL pattern recognizer for Code Giraffe.

Detects architectural patterns in .sql files including:
    - CREATE/ALTER TABLE                   -> database_table nodes
    - CREATE PROCEDURE / CREATE FUNCTION   -> service nodes (kind=stored_procedure/function)
    - CREATE VIEW                          -> module nodes (kind=view)
    - FOREIGN KEY ... REFERENCES           -> depends_on edges between tables
    - FROM/JOIN/INTO/UPDATE within bodies  -> reads/writes edges (proc/view -> table)
    - EXEC/EXECUTE proc_name within bodies -> calls edges (proc -> proc)
    - MERGE INTO table_name within bodies  -> writes edges (proc/view -> table)
    - Migration file ALTER TABLE           -> writes edges (file module -> table)

Supports both T-SQL bracket notation ([dbo].[tbName]) and bare identifiers.
All SQL keyword matching is case-insensitive.
"""

from __future__ import annotations

import re
from pathlib import Path

from codegiraffe.graph import Edge, Node
from codegiraffe.scanner import ScanResult
from codegiraffe.schema import EdgeType, NodeType

# ---------------------------------------------------------------------------
# Helper: strip schema prefix and brackets from an identifier
# ---------------------------------------------------------------------------

_SCHEMA_STRIP_RE = re.compile(
    r"""(?:\[?[a-zA-Z_]\w*\]?\.)?\[?(\w+)\]?""",
)


def _strip_name(raw: str) -> str:
    """Remove schema prefix and brackets from a SQL identifier.

    Examples:
        ``[dbo].[tbSecret]``  -> ``tbSecret``
        ``dbo.tbSecret``      -> ``tbSecret``
        ``[tbSecret]``        -> ``tbSecret``
        ``tbSecret``          -> ``tbSecret``
    """
    raw = raw.strip()
    m = _SCHEMA_STRIP_RE.fullmatch(raw)
    if m:
        return m.group(1)
    # Fallback: strip brackets only
    return raw.strip("[]")


# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------

# CREATE TABLE [[schema].]name — optional IF NOT EXISTS
_SQL_CREATE_TABLE_RE = re.compile(
    r"""\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"""
    r"""((?:\[?[a-zA-Z_]\w*\]?\.)?(?:\[?\w+\]?))""",
    re.IGNORECASE,
)

# ALTER TABLE [[schema].]name
_SQL_ALTER_TABLE_RE = re.compile(
    r"""\bALTER\s+TABLE\s+((?:\[?[a-zA-Z_]\w*\]?\.)?(?:\[?\w+\]?))""",
    re.IGNORECASE,
)

# CREATE [OR ALTER] PROCEDURE / PROC [[schema].]name
_SQL_CREATE_PROC_RE = re.compile(
    r"""\bCREATE\s+(?:OR\s+ALTER\s+)?(?:PROCEDURE|PROC)\s+"""
    r"""((?:\[?[a-zA-Z_]\w*\]?\.)?(?:\[?\w+\]?))""",
    re.IGNORECASE,
)

# ALTER PROCEDURE / PROC [[schema].]name
_SQL_ALTER_PROC_RE = re.compile(
    r"""\bALTER\s+(?:PROCEDURE|PROC)\s+"""
    r"""((?:\[?[a-zA-Z_]\w*\]?\.)?(?:\[?\w+\]?))""",
    re.IGNORECASE,
)

# CREATE [OR ALTER] FUNCTION [[schema].]name
_SQL_CREATE_FUNC_RE = re.compile(
    r"""\bCREATE\s+(?:OR\s+ALTER\s+)?FUNCTION\s+"""
    r"""((?:\[?[a-zA-Z_]\w*\]?\.)?(?:\[?\w+\]?))""",
    re.IGNORECASE,
)

# CREATE [OR ALTER] VIEW [[schema].]name
_SQL_CREATE_VIEW_RE = re.compile(
    r"""\bCREATE\s+(?:OR\s+ALTER\s+)?VIEW\s+"""
    r"""((?:\[?[a-zA-Z_]\w*\]?\.)?(?:\[?\w+\]?))""",
    re.IGNORECASE,
)

# FOREIGN KEY (...) REFERENCES [[schema].]tableName
_SQL_FK_RE = re.compile(
    r"""\bFOREIGN\s+KEY\s*\([^)]*\)\s*REFERENCES\s+"""
    r"""((?:\[?[a-zA-Z_]\w*\]?\.)?(?:\[?\w+\]?))""",
    re.IGNORECASE,
)

# ALTER TABLE tA ADD CONSTRAINT fk_name FOREIGN KEY (...) REFERENCES tB
# (The ALTER TABLE part is already captured by _SQL_ALTER_TABLE_RE; the REFERENCES
#  part is captured by _SQL_FK_RE — both fire independently from the full file text.)

# CREATE INDEX ... ON [[schema].]tableName
_SQL_CREATE_INDEX_RE = re.compile(
    r"""\bCREATE\s+(?:UNIQUE\s+)?(?:CLUSTERED\s+|NONCLUSTERED\s+)?INDEX\s+\S+\s+ON\s+"""
    r"""((?:\[?[a-zA-Z_]\w*\]?\.)?(?:\[?\w+\]?))""",
    re.IGNORECASE,
)

# Matches the start of a procedure/function/view body (AS keyword or BEGIN)
# Used as a marker to find the start of a body block.
_SQL_BODY_START_RE = re.compile(r"""\bAS\b""", re.IGNORECASE)

# GO batch separator
_SQL_GO_RE = re.compile(r"""^\s*GO\s*$""", re.IGNORECASE | re.MULTILINE)

# Table references in DML inside a body.
# We detect:   FROM tbl, JOIN tbl, INTO tbl, UPDATE tbl, DELETE FROM tbl
# Group 1: keyword (FROM|JOIN|INTO|UPDATE), Group 2: table name
_SQL_READ_REF_RE = re.compile(
    r"""\b(?:FROM|(?:INNER|LEFT|RIGHT|FULL|CROSS)?\s*JOIN)\s+"""
    r"""((?:\[?[a-zA-Z_]\w*\]?\.)?(?:\[?\w+\]?))""",
    re.IGNORECASE,
)

_SQL_WRITE_REF_RE = re.compile(
    r"""\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+"""
    r"""((?:\[?[a-zA-Z_]\w*\]?\.)?(?:\[?\w+\]?))""",
    re.IGNORECASE,
)

# EXEC / EXECUTE [[schema].]proc_name
# Skips dynamic execution: EXEC(@var) and EXEC sp_executesql
# Group 1: raw proc name (may include schema prefix and brackets)
_SQL_EXEC_RE = re.compile(
    r"""\bEXEC(?:UTE)?\s+((?:\[?[a-zA-Z_]\w*\]?\.)?(?:\[?\w+\]?))""",
    re.IGNORECASE,
)

# MERGE INTO [[schema].]table_name
_SQL_MERGE_RE = re.compile(
    r"""\bMERGE\s+(?:INTO\s+)?((?:\[?[a-zA-Z_]\w*\]?\.)?(?:\[?\w+\]?))""",
    re.IGNORECASE,
)

# Parameters for a stored procedure/function definition.
# Matches @paramName datatype patterns after the object name up to AS/BEGIN.
_SQL_PARAM_RE = re.compile(r"""(@\w+)\s+([\w\[\]]+(?:\s*\(\s*\d+(?:\s*,\s*\d+)?\s*\))?)""", re.IGNORECASE)

# Column count: lines inside CREATE TABLE body that look like "colName type"
# We count lines with a word followed by a SQL type keyword.
_SQL_COLUMN_LINE_RE = re.compile(
    r"""^\s+\[?\w+\]?\s+(?:INT|BIGINT|SMALLINT|TINYINT|BIT|DECIMAL|NUMERIC|FLOAT|REAL|MONEY|"""
    r"""SMALLMONEY|CHAR|VARCHAR|NCHAR|NVARCHAR|TEXT|NTEXT|BINARY|VARBINARY|IMAGE|"""
    r"""DATETIME|DATETIME2|DATE|TIME|SMALLDATETIME|UNIQUEIDENTIFIER|XML|SQL_VARIANT)""",
    re.IGNORECASE | re.MULTILINE,
)

# PRIMARY KEY detection inside a CREATE TABLE body
_SQL_PK_RE = re.compile(r"""\bPRIMARY\s+KEY\b""", re.IGNORECASE)

# Version from path: .../SqlServer/10.5/delta.sql  -> 10.5
_SQL_VERSION_PATH_RE = re.compile(r"""(?:[/\\]|^)SqlServer[/\\]([\d.]+)[/\\]""", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Body extraction helpers
# ---------------------------------------------------------------------------

def _split_into_batches(content: str) -> list[str]:
    """Split SQL content on GO batch separators.

    Returns a list of individual batch strings (GO lines removed).
    """
    parts = _SQL_GO_RE.split(content)
    return [p for p in parts if p.strip()]


def _extract_body_after_as(batch: str) -> str:
    """Return the portion of *batch* after the first AS keyword.

    If no AS is found, return the full batch (safe fallback for inline DDL).
    """
    m = _SQL_BODY_START_RE.search(batch)
    if m:
        return batch[m.end():]
    return batch


def _extract_param_text(batch: str, object_end: int) -> str:
    """Return the text between *object_end* and the AS keyword (parameter list region)."""
    m = _SQL_BODY_START_RE.search(batch, object_end)
    if m:
        return batch[object_end:m.start()]
    return ""


# ---------------------------------------------------------------------------
# Recognizer
# ---------------------------------------------------------------------------


class SqlRecognizer:
    """Recognizes SQL architectural patterns via regex.

    Detected patterns:
        - CREATE/ALTER TABLE             -> ``database_table`` nodes
        - CREATE/ALTER PROCEDURE/PROC    -> ``service`` nodes (kind=stored_procedure)
        - CREATE/ALTER FUNCTION          -> ``service`` nodes (kind=function)
        - CREATE VIEW                    -> ``module`` nodes (kind=view)
        - FOREIGN KEY ... REFERENCES     -> ``depends_on`` edges (table -> table)
        - Body FROM/JOIN references      -> ``reads`` edges (proc/view -> table)
        - Body INSERT/UPDATE/DELETE      -> ``writes`` edges (proc/view -> table)
        - Body MERGE INTO table          -> ``writes`` edges (proc/view -> table)
        - Body EXEC/EXECUTE proc_name    -> ``calls`` edges (proc -> proc)
        - Migration ALTER TABLE          -> ``writes`` edges (file module -> table)
        - CREATE INDEX ... ON table      -> ``writes`` edge (file module -> table)

    EXEC/EXECUTE skips:
        - Dynamic execution: ``EXEC(@variable)``
        - System procedures: ``sp_executesql``, ``xp_cmdshell``, etc.

    Metadata captured:
        - Table nodes: ``column_count``, ``has_primary_key``
        - Procedure/function nodes: ``parameters`` (list of ``{name, type}``)
        - File nodes: ``version`` (extracted from path like SqlServer/10.5/)
    """

    # SQL keywords that are not table names
    _SQL_KEYWORDS: frozenset[str] = frozenset({
        "SELECT", "FROM", "WHERE", "AND", "OR", "NOT", "IN", "IS", "NULL",
        "JOIN", "ON", "AS", "WITH", "BY", "GROUP", "ORDER", "HAVING",
        "INSERT", "UPDATE", "DELETE", "INTO", "VALUES", "SET",
        "CREATE", "ALTER", "DROP", "TABLE", "VIEW", "PROCEDURE", "PROC",
        "FUNCTION", "INDEX", "TRIGGER", "DATABASE", "SCHEMA",
        "BEGIN", "END", "IF", "ELSE", "WHILE", "RETURN", "DECLARE",
        "EXEC", "EXECUTE", "CAST", "CONVERT", "CASE", "WHEN", "THEN",
        "TOP", "DISTINCT", "UNION", "ALL", "EXCEPT", "INTERSECT",
        "GO", "USE", "GRANT", "REVOKE", "DENY",
        "MERGE", "USING", "MATCHED", "OUTPUT",
        "INFORMATION_SCHEMA", "SYS", "SYSOBJ", "SYSOBJ", "SYSOBJECTS",
        "SYSCOLUMNS", "SYSOBJECTS", "SYSINDEXES",
    })

    # System procedures that should be skipped when building call graphs
    _SYSTEM_PROCS: frozenset[str] = frozenset({
        "sp_executesql", "sp_execute", "xp_cmdshell", "sp_addlogin",
        "sp_adduser", "sp_configure", "sp_helpdb", "sp_who",
    })

    def recognize(self, file_path: Path, content: str) -> ScanResult:
        """Scan *content* of a SQL file and return discovered nodes/edges."""
        nodes: list[Node] = []
        edges: list[Edge] = []
        rel_path = file_path.as_posix()

        # Extract version from path if available
        version: str | None = None
        vm = _SQL_VERSION_PATH_RE.search(rel_path)
        if vm:
            version = vm.group(1)

        # Track what we've seen to avoid duplicates
        seen_tables: set[str] = set()
        seen_services: set[str] = set()
        seen_modules: set[str] = set()

        # Track objects defined in this file (node_id -> body text) for edge inference
        # Maps node_id to the body text of that object's definition
        object_bodies: dict[str, tuple[str, str]] = {}  # node_id -> (kind, body_text)

        # -----------------------------------------------------------------------
        # Phase 1: scan full content for DDL declarations
        # -----------------------------------------------------------------------

        # --- CREATE TABLE ---
        for m in _SQL_CREATE_TABLE_RE.finditer(content):
            raw = m.group(1)
            name = _strip_name(raw)
            if not name or name.upper() in self._SQL_KEYWORDS:
                continue
            if name not in seen_tables:
                seen_tables.add(name)
                node_id = f"table:{name}"
                # Extract the table body (from opening paren to matching close paren)
                body_text = self._extract_table_body(content, m.end())
                col_count = len(_SQL_COLUMN_LINE_RE.findall(body_text))
                has_pk = bool(_SQL_PK_RE.search(body_text))
                meta: dict[str, object] = {
                    "source": "sql_ddl",
                    "column_count": col_count,
                    "has_primary_key": has_pk,
                }
                if version:
                    meta["version"] = version
                nodes.append(
                    Node(
                        id=node_id,
                        type=NodeType.DATABASE_TABLE,
                        label=name,
                        file_path=rel_path,
                        metadata=meta,
                    )
                )
                # Foreign keys inside CREATE TABLE body
                for fk_m in _SQL_FK_RE.finditer(body_text):
                    ref_name = _strip_name(fk_m.group(1))
                    if ref_name and ref_name.upper() not in self._SQL_KEYWORDS:
                        edges.append(
                            Edge(
                                source=node_id,
                                target=f"table:{ref_name}",
                                type=EdgeType.DEPENDS_ON,
                                metadata={"relationship": "foreign_key", "inferred": True},
                            )
                        )

        # --- ALTER TABLE (ensure node exists; emit writes edge for migration context) ---
        for m in _SQL_ALTER_TABLE_RE.finditer(content):
            raw = m.group(1)
            name = _strip_name(raw)
            if not name or name.upper() in self._SQL_KEYWORDS:
                continue
            if name not in seen_tables:
                seen_tables.add(name)
                meta2: dict[str, object] = {"source": "sql_alter"}
                if version:
                    meta2["version"] = version
                nodes.append(
                    Node(
                        id=f"table:{name}",
                        type=NodeType.DATABASE_TABLE,
                        label=name,
                        file_path=rel_path,
                        metadata=meta2,
                    )
                )
            # Foreign keys in ALTER TABLE ... ADD CONSTRAINT ... FOREIGN KEY
            surrounding = content[m.start():m.start() + 500]
            for fk_m in _SQL_FK_RE.finditer(surrounding):
                ref_name = _strip_name(fk_m.group(1))
                if ref_name and ref_name.upper() not in self._SQL_KEYWORDS:
                    edges.append(
                        Edge(
                            source=f"table:{name}",
                            target=f"table:{ref_name}",
                            type=EdgeType.DEPENDS_ON,
                            metadata={"relationship": "foreign_key", "inferred": True},
                        )
                    )

        # --- CREATE PROCEDURE / PROC ---
        for m in _SQL_CREATE_PROC_RE.finditer(content):
            raw = m.group(1)
            name = _strip_name(raw)
            if not name or name.upper() in self._SQL_KEYWORDS:
                continue
            if name not in seen_services:
                seen_services.add(name)
                node_id = f"service:{name}"
                param_text = _extract_param_text(content, m.end())
                params = self._parse_params(param_text)
                meta3: dict[str, object] = {
                    "kind": "stored_procedure",
                    "parameters": params,
                    "source": "sql_ddl",
                }
                if version:
                    meta3["version"] = version
                nodes.append(
                    Node(
                        id=node_id,
                        type=NodeType.SERVICE,
                        label=name,
                        file_path=rel_path,
                        metadata=meta3,
                    )
                )
                body_text = _extract_body_after_as(self._get_batch_for_match(content, m.start()))
                object_bodies[node_id] = ("proc", body_text)

        # --- ALTER PROCEDURE ---
        for m in _SQL_ALTER_PROC_RE.finditer(content):
            raw = m.group(1)
            name = _strip_name(raw)
            if not name or name.upper() in self._SQL_KEYWORDS:
                continue
            if name not in seen_services:
                seen_services.add(name)
                node_id = f"service:{name}"
                meta4: dict[str, object] = {"kind": "stored_procedure", "source": "sql_alter"}
                if version:
                    meta4["version"] = version
                nodes.append(
                    Node(
                        id=node_id,
                        type=NodeType.SERVICE,
                        label=name,
                        file_path=rel_path,
                        metadata=meta4,
                    )
                )
                body_text = _extract_body_after_as(self._get_batch_for_match(content, m.start()))
                object_bodies[node_id] = ("proc", body_text)

        # --- CREATE FUNCTION ---
        for m in _SQL_CREATE_FUNC_RE.finditer(content):
            raw = m.group(1)
            name = _strip_name(raw)
            if not name or name.upper() in self._SQL_KEYWORDS:
                continue
            if name not in seen_services:
                seen_services.add(name)
                node_id = f"service:{name}"
                param_text = _extract_param_text(content, m.end())
                params = self._parse_params(param_text)
                meta5: dict[str, object] = {
                    "kind": "function",
                    "parameters": params,
                    "source": "sql_ddl",
                }
                if version:
                    meta5["version"] = version
                nodes.append(
                    Node(
                        id=node_id,
                        type=NodeType.SERVICE,
                        label=name,
                        file_path=rel_path,
                        metadata=meta5,
                    )
                )
                body_text = _extract_body_after_as(self._get_batch_for_match(content, m.start()))
                object_bodies[node_id] = ("func", body_text)

        # --- CREATE VIEW ---
        for m in _SQL_CREATE_VIEW_RE.finditer(content):
            raw = m.group(1)
            name = _strip_name(raw)
            if not name or name.upper() in self._SQL_KEYWORDS:
                continue
            if name not in seen_modules:
                seen_modules.add(name)
                node_id = f"mod:{name}"
                meta6: dict[str, object] = {"kind": "view", "source": "sql_ddl"}
                if version:
                    meta6["version"] = version
                nodes.append(
                    Node(
                        id=node_id,
                        type=NodeType.MODULE,
                        label=name,
                        file_path=rel_path,
                        metadata=meta6,
                    )
                )
                body_text = _extract_body_after_as(self._get_batch_for_match(content, m.start()))
                object_bodies[node_id] = ("view", body_text)

        # -----------------------------------------------------------------------
        # Phase 2: body-level edge inference (proc/view -> table)
        # -----------------------------------------------------------------------
        seen_edges: set[tuple[str, str, str]] = set()

        for source_id, (obj_kind, body) in object_bodies.items():
            # READ references: FROM / JOIN
            for ref_m in _SQL_READ_REF_RE.finditer(body):
                ref_name = _strip_name(ref_m.group(1))
                if not ref_name or ref_name.upper() in self._SQL_KEYWORDS:
                    continue
                target_id = f"table:{ref_name}"
                key = (source_id, target_id, EdgeType.READS)
                if key not in seen_edges:
                    seen_edges.add(key)
                    edges.append(
                        Edge(
                            source=source_id,
                            target=target_id,
                            type=EdgeType.READS,
                            metadata={"inferred": True},
                        )
                    )

            # WRITE references: INSERT INTO / UPDATE / DELETE FROM
            for ref_m in _SQL_WRITE_REF_RE.finditer(body):
                ref_name = _strip_name(ref_m.group(1))
                if not ref_name or ref_name.upper() in self._SQL_KEYWORDS:
                    continue
                target_id = f"table:{ref_name}"
                key = (source_id, target_id, EdgeType.WRITES)
                if key not in seen_edges:
                    seen_edges.add(key)
                    edges.append(
                        Edge(
                            source=source_id,
                            target=target_id,
                            type=EdgeType.WRITES,
                            metadata={"inferred": True},
                        )
                    )

            # MERGE INTO: treats target as a write (upsert)
            for ref_m in _SQL_MERGE_RE.finditer(body):
                ref_name = _strip_name(ref_m.group(1))
                if not ref_name or ref_name.upper() in self._SQL_KEYWORDS:
                    continue
                target_id = f"table:{ref_name}"
                key = (source_id, target_id, EdgeType.WRITES)
                if key not in seen_edges:
                    seen_edges.add(key)
                    edges.append(
                        Edge(
                            source=source_id,
                            target=target_id,
                            type=EdgeType.WRITES,
                            metadata={"inferred": True, "via": "merge"},
                        )
                    )

            # EXEC / EXECUTE: stored-procedure-to-stored-procedure calls
            for ref_m in _SQL_EXEC_RE.finditer(body):
                raw = ref_m.group(1).strip()
                # Skip dynamic execution: EXEC(@variable) is captured as raw starting with "@"
                if raw.startswith("@") or raw.startswith("("):
                    continue
                callee_name = _strip_name(raw)
                if not callee_name or callee_name.upper() in self._SQL_KEYWORDS:
                    continue
                # Skip system/dynamic stored procedures
                if callee_name.lower() in self._SYSTEM_PROCS:
                    continue
                target_id = f"service:{callee_name}"
                key = (source_id, target_id, EdgeType.CALLS)
                if key not in seen_edges:
                    seen_edges.add(key)
                    edges.append(
                        Edge(
                            source=source_id,
                            target=target_id,
                            type=EdgeType.CALLS,
                            metadata={"inferred": True, "style": "exec"},
                        )
                    )

        # -----------------------------------------------------------------------
        # Phase 3: migration-file-level edges
        # For files that contain ALTER TABLE or CREATE INDEX (but are NOT defining
        # procedures/views), emit a writes edge from a synthetic file module node.
        # Only emit when we have ALTER TABLE or CREATE INDEX references.
        # -----------------------------------------------------------------------
        migration_targets: set[str] = set()

        # ALTER TABLE as migration change
        for m in _SQL_ALTER_TABLE_RE.finditer(content):
            name = _strip_name(m.group(1))
            if name and name.upper() not in self._SQL_KEYWORDS:
                migration_targets.add(name)

        # CREATE INDEX as migration change
        for m in _SQL_CREATE_INDEX_RE.finditer(content):
            name = _strip_name(m.group(1))
            if name and name.upper() not in self._SQL_KEYWORDS:
                migration_targets.add(name)

        if migration_targets and not object_bodies:
            # This is a migration-only file (no procs/views); emit a file-level module node
            file_stem = file_path.stem
            file_node_id = f"mod:{file_stem}"
            if file_node_id not in {n.id for n in nodes}:
                file_meta: dict[str, object] = {"kind": "migration", "source": "sql_migration"}
                if version:
                    file_meta["version"] = version
                nodes.append(
                    Node(
                        id=file_node_id,
                        type=NodeType.MODULE,
                        label=file_stem,
                        file_path=rel_path,
                        metadata=file_meta,
                    )
                )
            for tbl_name in migration_targets:
                target_id = f"table:{tbl_name}"
                key = (file_node_id, target_id, EdgeType.WRITES)
                if key not in seen_edges:
                    seen_edges.add(key)
                    edges.append(
                        Edge(
                            source=file_node_id,
                            target=target_id,
                            type=EdgeType.WRITES,
                            metadata={"inferred": True},
                        )
                    )

        return ScanResult(nodes=nodes, edges=edges)

    # ---------------------------------------------------------------------------
    # Private helpers
    # ---------------------------------------------------------------------------

    def _extract_table_body(self, content: str, offset: int) -> str:
        """Extract text inside the CREATE TABLE body (opening paren to matching close).

        Returns an empty string if no opening paren is found within 200 chars.
        """
        # Find opening paren
        search_region = content[offset:offset + 200]
        paren_pos = search_region.find("(")
        if paren_pos == -1:
            return ""
        abs_start = offset + paren_pos + 1
        depth = 1
        i = abs_start
        while i < len(content) and depth > 0:
            ch = content[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            i += 1
        return content[abs_start:i - 1] if depth == 0 else content[abs_start:]

    def _get_batch_for_match(self, content: str, match_start: int) -> str:
        """Return the GO-delimited batch that contains *match_start*.

        If the content has no GO separators, returns the entire content from
        match_start to the end.
        """
        # Find the GO before match_start
        batch_start = 0
        for go_m in _SQL_GO_RE.finditer(content):
            if go_m.start() < match_start:
                batch_start = go_m.end()
            else:
                return content[batch_start:go_m.start()]
        return content[batch_start:]

    def _parse_params(self, param_text: str) -> list[dict[str, str]]:
        """Parse stored procedure / function parameter declarations.

        Returns a list of ``{"name": "@param", "type": "VARCHAR(100)"}`` dicts.
        """
        params: list[dict[str, str]] = []
        seen: set[str] = set()
        for m in _SQL_PARAM_RE.finditer(param_text):
            pname = m.group(1)
            ptype = m.group(2).strip()
            if pname not in seen:
                seen.add(pname)
                params.append({"name": pname, "type": ptype})
        return params

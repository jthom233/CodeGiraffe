"""Data models and parser for git diff parsing and change impact validation.

Provides Pydantic models for representing parsed diffs, test suggestions,
file coupling analysis, and change impact reports. Includes a pure
string-to-model unified diff parser with zero dependencies on graph or git.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field


class DiffHunk(BaseModel):
    """A single hunk from a unified diff, representing a contiguous change region."""

    old_start: int = 0
    old_count: int = 0
    new_start: int = 0
    new_count: int = 0
    header: str = ""


class DiffFile(BaseModel):
    """A file entry from a git diff, tracking its status and change hunks."""

    path: str
    old_path: str = ""
    status: str = "modified"  # added, deleted, renamed, modified
    hunks: list[DiffHunk] = Field(default_factory=list)
    is_binary: bool = False
    additions: int = 0
    deletions: int = 0


class TestSuggestion(BaseModel):
    """A suggested test file for validating a change, with scoring and reasoning."""

    file_path: str
    score: float = 0.0
    reason: str = ""
    strategy: str = ""  # graph, naming, blast_radius


class CouplingPair(BaseModel):
    """A pair of files that frequently change together, indicating coupling."""

    file_a: str
    file_b: str
    co_change_count: int = 0
    change_count_a: int = 0
    change_count_b: int = 0
    coupling: float = 0.0
    in_graph: bool = False
    edge_type: str = ""


class ChangeReport(BaseModel):
    """Aggregate report of a change's impact on the architecture graph."""

    changed_files: list[DiffFile] = Field(default_factory=list)
    changed_nodes: list[str] = Field(default_factory=list)
    covered_nodes: list[str] = Field(default_factory=list)
    uncovered_nodes: list[str] = Field(default_factory=list)
    contract_violations: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    total_blast_radius: int = 0


# ---------------------------------------------------------------------------
# Regex constants for unified diff parsing
# ---------------------------------------------------------------------------

_DIFF_HEADER_RE = re.compile(r"^diff --git a/(.+?) b/(.+?)$", re.MULTILINE)
_FILE_OLD_RE = re.compile(r"^--- (?:a/(.+)|/dev/null)$", re.MULTILINE)
_FILE_NEW_RE = re.compile(r"^\+\+\+ (?:b/(.+)|/dev/null)$", re.MULTILINE)
_HUNK_RE = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)?$", re.MULTILINE
)
_RENAME_FROM_RE = re.compile(r"^rename from (.+)$", re.MULTILINE)
_RENAME_TO_RE = re.compile(r"^rename to (.+)$", re.MULTILINE)
_BINARY_RE = re.compile(
    r"^(?:Binary files .+|GIT binary patch)$", re.MULTILINE
)

# Symbol hint patterns for extract_symbol_hints
_PYTHON_DEF_RE = re.compile(r"\bdef\s+(\w+)")
_PYTHON_CLASS_RE = re.compile(r"\bclass\s+(\w+)")
_GENERIC_FUNC_RE = re.compile(r"\bfunc(?:tion)?\s+(\w+)")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_diff(raw_diff: str) -> list[DiffFile]:
    """Parse a unified diff string into a list of :class:`DiffFile` objects.

    The parser handles modified, added, deleted, renamed, and binary files.
    It extracts per-hunk line counts for additions and deletions.

    Args:
        raw_diff: Raw unified diff text (e.g. output of ``git diff``).

    Returns:
        A list of :class:`DiffFile` instances, one per file in the diff.
    """
    if not raw_diff or not raw_diff.strip():
        return []

    # Split on "diff --git" boundaries. The first element before the first
    # match is always empty or preamble, so we skip it.
    sections = re.split(r"(?=^diff --git )", raw_diff, flags=re.MULTILINE)
    results: list[DiffFile] = []

    for section in sections:
        section = section.strip()
        if not section:
            continue

        header_m = _DIFF_HEADER_RE.search(section)
        if header_m is None:
            continue

        # Determine old/new paths from --- / +++ lines
        old_m = _FILE_OLD_RE.search(section)
        new_m = _FILE_NEW_RE.search(section)

        old_path = old_m.group(1) if old_m and old_m.group(1) else None
        new_path = new_m.group(1) if new_m and new_m.group(1) else None

        # Detect binary
        is_binary = _BINARY_RE.search(section) is not None

        # Detect rename
        rename_from_m = _RENAME_FROM_RE.search(section)
        rename_to_m = _RENAME_TO_RE.search(section)

        # Determine status
        if rename_from_m and rename_to_m:
            status = "renamed"
            file_old_path = rename_from_m.group(1)
            file_path = rename_to_m.group(1)
        elif old_path is None and new_path is not None:
            status = "added"
            file_path = new_path
            file_old_path = ""
        elif new_path is None and old_path is not None:
            status = "deleted"
            file_path = old_path
            file_old_path = ""
        else:
            status = "modified"
            file_path = new_path or header_m.group(2)
            file_old_path = ""

        # Parse hunks
        hunks: list[DiffHunk] = []
        additions = 0
        deletions = 0

        hunk_matches = list(_HUNK_RE.finditer(section))
        for idx, hunk_m in enumerate(hunk_matches):
            h_old_start = int(hunk_m.group(1))
            h_old_count = int(hunk_m.group(2)) if hunk_m.group(2) else 1
            h_new_start = int(hunk_m.group(3))
            h_new_count = int(hunk_m.group(4)) if hunk_m.group(4) else 1
            h_header = (hunk_m.group(5) or "").strip()

            hunks.append(
                DiffHunk(
                    old_start=h_old_start,
                    old_count=h_old_count,
                    new_start=h_new_start,
                    new_count=h_new_count,
                    header=h_header,
                )
            )

            # Count additions and deletions within this hunk's body.
            # The hunk body spans from the end of this @@ line to the start
            # of the next @@ line (or end of section).
            body_start = hunk_m.end()
            if idx + 1 < len(hunk_matches):
                body_end = hunk_matches[idx + 1].start()
            else:
                body_end = len(section)

            hunk_body = section[body_start:body_end]
            for line in hunk_body.splitlines():
                if line.startswith("+") and not line.startswith("+++"):
                    additions += 1
                elif line.startswith("-") and not line.startswith("---"):
                    deletions += 1
                # Ignore "\ No newline at end of file" and context lines

        results.append(
            DiffFile(
                path=file_path,
                old_path=file_old_path,
                status=status,
                hunks=hunks,
                is_binary=is_binary,
                additions=additions,
                deletions=deletions,
            )
        )

    return results


def extract_symbol_hints(hunks: list[DiffHunk]) -> list[str]:
    """Extract symbol name hints from hunk headers.

    Parses hunk ``header`` text for Python ``def``/``class`` names and
    generic function identifiers (Go ``func``, JS ``function``, etc.).

    Args:
        hunks: List of :class:`DiffHunk` objects to inspect.

    Returns:
        A deduplicated list of symbol names found in hunk headers.
    """
    seen: set[str] = set()
    result: list[str] = []

    for hunk in hunks:
        header = hunk.header
        if not header:
            continue

        for pattern in (_PYTHON_DEF_RE, _PYTHON_CLASS_RE, _GENERIC_FUNC_RE):
            for m in pattern.finditer(header):
                name = m.group(1)
                if name not in seen:
                    seen.add(name)
                    result.append(name)

    return result

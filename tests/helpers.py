"""Shared test helpers for git-dependent tests.

Provides _GIT_ENV, _git(), _init_repo(), and _commit_file() so they don't
need to be duplicated across test files (US6 — fixture consolidation).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

# ---------------------------------------------------------------------------
# Git helper utilities
# ---------------------------------------------------------------------------

# Explicit author identity so tests work without global git config (CI, etc.)
_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test Author",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a git command inside *cwd* with test-safe env."""
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=_GIT_ENV,
    )


def _init_repo(tmp: Path) -> Path:
    """Create a bare-bones git repo in *tmp* and return the path."""
    _git(tmp, "init")
    # Ensure default branch name is predictable.
    _git(tmp, "checkout", "-b", "main")
    return tmp


def _commit_file(repo: Path, name: str, content: str, msg: str) -> None:
    """Write a file, stage it, and commit."""
    (repo / name).write_text(content)
    _git(repo, "add", name)
    _git(repo, "commit", "-m", msg)

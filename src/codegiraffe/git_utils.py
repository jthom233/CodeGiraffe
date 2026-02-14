"""Git utility functions for change impact validation.

Thin subprocess wrappers for git CLI commands. Independent of graph or
diff_parser — provides raw git data for higher-level analysis layers.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(Exception):
    """Base exception for git operations."""


class NotAGitRepoError(GitError):
    """Raised when a path is not inside a git repository."""


def is_git_repo(project_path: str) -> bool:
    """Check whether *project_path* is inside a git repository.

    Runs ``git rev-parse --git-dir`` and returns ``True`` when the
    command succeeds (returncode 0).
    """
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        capture_output=True,
        text=True,
        cwd=project_path,
    )
    return result.returncode == 0


def get_uncommitted_diff(project_path: str) -> str:
    """Return the unified diff of uncommitted changes.

    Runs ``git diff HEAD`` to capture both staged and unstaged changes.
    If that fails (e.g. no commits yet — initial-commit scenario), falls
    back to ``git diff --cached`` so that staged files in a brand-new
    repo are still reported.

    Raises:
        NotAGitRepoError: If *project_path* is not a git repository.
    """
    if not is_git_repo(project_path):
        raise NotAGitRepoError(f"Not a git repository: {project_path}")

    result = subprocess.run(
        ["git", "diff", "HEAD"],
        capture_output=True,
        text=True,
        cwd=project_path,
    )

    if result.returncode != 0:
        # Fallback for repos with no commits yet.
        result = subprocess.run(
            ["git", "diff", "--cached"],
            capture_output=True,
            text=True,
            cwd=project_path,
        )

    return result.stdout


def get_changed_files(project_path: str) -> list[str]:
    """Return a list of file paths changed relative to HEAD.

    Combines ``git diff HEAD --name-only`` output.  Returns an empty
    list when the directory is not a git repository (no exception).
    """
    if not is_git_repo(project_path):
        return []

    result = subprocess.run(
        ["git", "diff", "HEAD", "--name-only"],
        capture_output=True,
        text=True,
        cwd=project_path,
    )

    if result.returncode != 0:
        return []

    return [line for line in result.stdout.strip().splitlines() if line]


def get_commit_file_history(
    project_path: str, depth: int = 100
) -> list[list[str]]:
    """Return per-commit lists of changed files from recent history.

    Runs ``git log --name-only`` limited to *depth* commits.  Each inner
    list contains the file paths touched by a single commit (most recent
    commit first).

    Returns an empty list when the directory is not a git repository or
    has no commits.
    """
    if not is_git_repo(project_path):
        return []

    result = subprocess.run(
        [
            "git",
            "log",
            "--name-only",
            "--pretty=format:COMMIT:%H",
            f"-n{depth}",
        ],
        capture_output=True,
        text=True,
        cwd=project_path,
    )

    if result.returncode != 0:
        return []

    commits: list[list[str]] = []
    raw = result.stdout.strip()
    if not raw:
        return []

    # Split on COMMIT: markers — the first element before the first
    # marker is always empty, so skip it.
    parts = raw.split("COMMIT:")
    for part in parts:
        part = part.strip()
        if not part:
            continue
        lines = part.splitlines()
        # First line is the commit hash; remaining non-empty lines are
        # file paths.
        files = [line.strip() for line in lines[1:] if line.strip()]
        if files:
            commits.append(files)

    return commits

"""Tests for git_utils — thin subprocess wrappers for git CLI commands.

All tests use real temporary git repos created via subprocess (no mocking).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from codegiraffe.git_utils import (
    GitError,
    NotAGitRepoError,
    get_changed_files,
    get_commit_file_history,
    get_uncommitted_diff,
    is_git_repo,
)

# ---------------------------------------------------------------------------
# Shared helpers / env
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


# ===================================================================
# TestIsGitRepo
# ===================================================================


class TestIsGitRepo:
    """Tests for is_git_repo()."""

    def test_is_git_repo_true(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        assert is_git_repo(str(tmp_path)) is True

    def test_is_git_repo_false(self, tmp_path: Path) -> None:
        # tmp_path exists but has no .git — should be False.
        assert is_git_repo(str(tmp_path)) is False


# ===================================================================
# TestGetUncommittedDiff
# ===================================================================


class TestGetUncommittedDiff:
    """Tests for get_uncommitted_diff()."""

    def test_get_uncommitted_diff_with_changes(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        _commit_file(repo, "hello.py", "print('hello')\n", "initial")

        # Modify the committed file (unstaged).
        (repo / "hello.py").write_text("print('goodbye')\n")

        diff = get_uncommitted_diff(str(repo))
        assert diff  # non-empty
        assert "hello.py" in diff
        assert "goodbye" in diff

    def test_get_uncommitted_diff_no_changes(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        _commit_file(repo, "hello.py", "print('hello')\n", "initial")

        diff = get_uncommitted_diff(str(repo))
        assert diff == ""

    def test_get_uncommitted_diff_not_git_repo(self, tmp_path: Path) -> None:
        with pytest.raises(NotAGitRepoError):
            get_uncommitted_diff(str(tmp_path))

    def test_get_uncommitted_diff_staged_changes(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        _commit_file(repo, "hello.py", "print('hello')\n", "initial")

        # Modify and stage (but do not commit).
        (repo / "hello.py").write_text("print('staged')\n")
        _git(repo, "add", "hello.py")

        diff = get_uncommitted_diff(str(repo))
        assert diff  # non-empty
        assert "staged" in diff

    def test_get_uncommitted_diff_new_repo_no_commits(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)

        # Stage a file but make NO commits — git diff HEAD will fail.
        (repo / "new.py").write_text("x = 1\n")
        _git(repo, "add", "new.py")

        diff = get_uncommitted_diff(str(repo))
        assert diff  # fallback to --cached should return content
        assert "new.py" in diff


# ===================================================================
# TestGetChangedFiles
# ===================================================================


class TestGetChangedFiles:
    """Tests for get_changed_files()."""

    def test_get_changed_files_returns_paths(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        _commit_file(repo, "a.py", "a = 1\n", "initial")

        # Modify the file (unstaged).
        (repo / "a.py").write_text("a = 2\n")

        files = get_changed_files(str(repo))
        assert files == ["a.py"]

    def test_get_changed_files_empty_when_clean(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        _commit_file(repo, "a.py", "a = 1\n", "initial")

        files = get_changed_files(str(repo))
        assert files == []

    def test_get_changed_files_not_git_repo(self, tmp_path: Path) -> None:
        # Should return empty list, NOT raise.
        files = get_changed_files(str(tmp_path))
        assert files == []


# ===================================================================
# TestGetCommitFileHistory
# ===================================================================


class TestGetCommitFileHistory:
    """Tests for get_commit_file_history()."""

    def test_get_commit_file_history(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        _commit_file(repo, "a.py", "a = 1\n", "first")
        _commit_file(repo, "b.py", "b = 1\n", "second")

        history = get_commit_file_history(str(repo))

        # Most recent commit first.
        assert len(history) == 2
        assert history[0] == ["b.py"]
        assert history[1] == ["a.py"]

    def test_get_commit_file_history_depth_limit(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        for i in range(5):
            _commit_file(repo, f"f{i}.py", f"x = {i}\n", f"commit {i}")

        history = get_commit_file_history(str(repo), depth=2)
        assert len(history) == 2

    def test_get_commit_file_history_not_git_repo(
        self, tmp_path: Path
    ) -> None:
        history = get_commit_file_history(str(tmp_path))
        assert history == []

    def test_get_commit_file_history_empty_repo(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        # No commits at all.
        history = get_commit_file_history(str(repo))
        assert history == []

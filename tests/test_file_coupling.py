"""Tests for file_coupling() in query.py.

Uses real temporary git repos (no mocking) to test co-change analysis.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from codegiraffe.graph import ArchGraph, Edge, Node
from codegiraffe.query import file_coupling
from codegiraffe.schema import EdgeType, NodeType
from tests.helpers import _GIT_ENV, _git, _init_repo


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _commit_files(repo: Path, files: dict[str, str], msg: str) -> None:
    """Write multiple files, stage, and commit."""
    for name, content in files.items():
        filepath = repo / name
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content)
        _git(repo, "add", name)
    _git(repo, "commit", "-m", msg)


# ===========================================================================
# TestFileCoupling
# ===========================================================================


class TestFileCoupling:
    """Tests for file_coupling()."""

    def test_basic_coupling(self, tmp_path: Path):
        """2 files always committed together have coupling = 1.0."""
        repo = _init_repo(tmp_path)
        g = ArchGraph()

        # Commit a.py and b.py together 3 times
        for i in range(3):
            _commit_files(repo, {"a.py": f"a={i}", "b.py": f"b={i}"}, f"commit {i}")

        result = file_coupling(g, str(repo), min_commits=1, min_coupling=0.0)
        assert len(result) >= 1
        pair = result[0]
        assert pair.coupling == 1.0
        assert {pair.file_a, pair.file_b} == {"a.py", "b.py"}

    def test_partial_coupling(self, tmp_path: Path):
        """Files committed together 2/3 times have coupling ~0.67."""
        repo = _init_repo(tmp_path)
        g = ArchGraph()

        # Commits 1 and 2: a.py + b.py together
        _commit_files(repo, {"a.py": "a=0", "b.py": "b=0"}, "commit 0")
        _commit_files(repo, {"a.py": "a=1", "b.py": "b=1"}, "commit 1")
        # Commit 3: only a.py
        _commit_files(repo, {"a.py": "a=2"}, "commit 2")

        result = file_coupling(g, str(repo), min_commits=1, min_coupling=0.0)
        pair = [p for p in result if {p.file_a, p.file_b} == {"a.py", "b.py"}]
        assert len(pair) == 1
        # co_change = 2, max(count_a=3, count_b=2) = 3 -> coupling = 2/3 ~ 0.6667
        assert abs(pair[0].coupling - 2 / 3) < 0.01

    def test_min_commits_filter(self, tmp_path: Path):
        """Pair with 1 co-change but min_commits=3 is filtered out."""
        repo = _init_repo(tmp_path)
        g = ArchGraph()

        _commit_files(repo, {"a.py": "a=0", "b.py": "b=0"}, "commit 0")

        result = file_coupling(g, str(repo), min_commits=3, min_coupling=0.0)
        assert len(result) == 0

    def test_min_coupling_filter(self, tmp_path: Path):
        """Pair with low coupling is filtered out by min_coupling."""
        repo = _init_repo(tmp_path)
        g = ArchGraph()

        # a.py changes 10 times, b.py only once (with a.py)
        _commit_files(repo, {"a.py": "a=0", "b.py": "b=0"}, "together")
        for i in range(1, 10):
            _commit_files(repo, {"a.py": f"a={i}"}, f"solo {i}")

        # co_change = 1, max(10, 1) = 10 -> coupling = 0.1
        result = file_coupling(g, str(repo), min_commits=1, min_coupling=0.5)
        pair = [p for p in result if {p.file_a, p.file_b} == {"a.py", "b.py"}]
        assert len(pair) == 0

    def test_file_path_filter(self, tmp_path: Path):
        """Only return pairs involving specified file."""
        repo = _init_repo(tmp_path)
        g = ArchGraph()

        # a+b together, c+d together
        for i in range(3):
            _commit_files(repo, {"a.py": f"a={i}", "b.py": f"b={i}"}, f"ab {i}")
        for i in range(3):
            _commit_files(repo, {"c.py": f"c={i}", "d.py": f"d={i}"}, f"cd {i}")

        result = file_coupling(
            g, str(repo), file_path="a.py", min_commits=1, min_coupling=0.0
        )
        for pair in result:
            assert pair.file_a == "a.py" or pair.file_b == "a.py"
        # c+d pair should not appear
        cd_pairs = [p for p in result if {p.file_a, p.file_b} == {"c.py", "d.py"}]
        assert len(cd_pairs) == 0

    def test_cross_reference_in_graph(self, tmp_path: Path):
        """Pair has edge in graph -> in_graph=True."""
        repo = _init_repo(tmp_path)

        g = ArchGraph()
        g.add_node(Node(id="mod:a", type=NodeType.MODULE, label="a", file_path="a.py"))
        g.add_node(Node(id="mod:b", type=NodeType.MODULE, label="b", file_path="b.py"))
        g.add_edge(Edge(source="mod:a", target="mod:b", type=EdgeType.IMPORTS))

        for i in range(3):
            _commit_files(repo, {"a.py": f"a={i}", "b.py": f"b={i}"}, f"commit {i}")

        result = file_coupling(g, str(repo), min_commits=1, min_coupling=0.0)
        pair = [p for p in result if {p.file_a, p.file_b} == {"a.py", "b.py"}]
        assert len(pair) == 1
        assert pair[0].in_graph is True
        assert pair[0].edge_type == EdgeType.IMPORTS

    def test_cross_reference_not_in_graph(self, tmp_path: Path):
        """Pair has no edge in graph -> in_graph=False."""
        repo = _init_repo(tmp_path)
        g = ArchGraph()  # empty graph

        for i in range(3):
            _commit_files(repo, {"a.py": f"a={i}", "b.py": f"b={i}"}, f"commit {i}")

        result = file_coupling(g, str(repo), min_commits=1, min_coupling=0.0)
        pair = [p for p in result if {p.file_a, p.file_b} == {"a.py", "b.py"}]
        assert len(pair) == 1
        assert pair[0].in_graph is False

    def test_top_20_limit(self, tmp_path: Path):
        """Many pairs are limited to top 20."""
        repo = _init_repo(tmp_path)
        g = ArchGraph()

        # Create 25 files all committed together -> C(25,2)=300 pairs
        files = {f"f{i}.py": f"x={i}" for i in range(25)}
        for commit_n in range(3):
            updated = {k: f"x={commit_n}" for k in files}
            _commit_files(repo, updated, f"commit {commit_n}")

        result = file_coupling(g, str(repo), min_commits=1, min_coupling=0.0)
        assert len(result) == 20

    def test_not_git_repo(self, tmp_path: Path):
        """Non-git directory returns empty list."""
        g = ArchGraph()
        result = file_coupling(g, str(tmp_path))
        assert result == []

    def test_empty_history(self, tmp_path: Path):
        """Repo with no commits returns empty list."""
        repo = _init_repo(tmp_path)
        g = ArchGraph()
        result = file_coupling(g, str(repo))
        assert result == []

    def test_single_file_commits(self, tmp_path: Path):
        """Commits with only 1 file produce no pairs."""
        repo = _init_repo(tmp_path)
        g = ArchGraph()

        _commit_files(repo, {"a.py": "a=0"}, "commit 0")
        _commit_files(repo, {"b.py": "b=0"}, "commit 1")
        _commit_files(repo, {"c.py": "c=0"}, "commit 2")

        result = file_coupling(g, str(repo), min_commits=1, min_coupling=0.0)
        assert result == []

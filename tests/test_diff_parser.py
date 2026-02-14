"""Tests for diff_parser data models and parsing functions."""

from codegiraffe.diff_parser import (
    ChangeReport,
    CouplingPair,
    DiffFile,
    DiffHunk,
    TestSuggestion,
    extract_symbol_hints,
    parse_diff,
)


def test_diff_hunk_defaults():
    """DiffHunk() has all defaults."""
    hunk = DiffHunk()
    assert hunk.old_start == 0
    assert hunk.old_count == 0
    assert hunk.new_start == 0
    assert hunk.new_count == 0
    assert hunk.header == ""


def test_diff_file_defaults():
    """DiffFile(path='foo.py') has correct defaults."""
    df = DiffFile(path="foo.py")
    assert df.path == "foo.py"
    assert df.old_path == ""
    assert df.status == "modified"
    assert df.hunks == []
    assert df.is_binary is False
    assert df.additions == 0
    assert df.deletions == 0


def test_diff_file_rename_has_old_path():
    """DiffFile for a rename has old_path and status='renamed'."""
    df = DiffFile(path="new.py", old_path="old.py", status="renamed")
    assert df.path == "new.py"
    assert df.old_path == "old.py"
    assert df.status == "renamed"


def test_change_report_structure():
    """ChangeReport() has empty lists and zero blast radius."""
    report = ChangeReport()
    assert report.changed_files == []
    assert report.changed_nodes == []
    assert report.covered_nodes == []
    assert report.uncovered_nodes == []
    assert report.contract_violations == []
    assert report.recommendations == []
    assert report.total_blast_radius == 0


def test_test_suggestion_model():
    """TestSuggestion(file_path='test.py') has correct defaults."""
    ts = TestSuggestion(file_path="test.py")
    assert ts.file_path == "test.py"
    assert ts.score == 0.0
    assert ts.reason == ""
    assert ts.strategy == ""


def test_coupling_pair_model():
    """CouplingPair(file_a='a.py', file_b='b.py') has correct defaults."""
    cp = CouplingPair(file_a="a.py", file_b="b.py")
    assert cp.file_a == "a.py"
    assert cp.file_b == "b.py"
    assert cp.co_change_count == 0
    assert cp.change_count_a == 0
    assert cp.change_count_b == 0
    assert cp.coupling == 0.0
    assert cp.in_graph is False
    assert cp.edge_type == ""


# ---------------------------------------------------------------------------
# TestParseDiff — unified diff parsing (12 tests)
# ---------------------------------------------------------------------------


class TestParseDiff:
    """Tests for parse_diff()."""

    def test_parse_single_modified_file(self):
        """Parse a diff with one modified file."""
        raw = (
            "diff --git a/foo.py b/foo.py\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -1,3 +1,4 @@\n"
            " line1\n"
            "-old\n"
            "+new\n"
            "+added\n"
        )
        result = parse_diff(raw)
        assert len(result) == 1
        df = result[0]
        assert df.path == "foo.py"
        assert df.status == "modified"
        assert df.additions == 2
        assert df.deletions == 1

    def test_parse_multiple_files(self):
        """Parse a diff with two files."""
        raw = (
            "diff --git a/a.py b/a.py\n"
            "--- a/a.py\n"
            "+++ b/a.py\n"
            "@@ -1,2 +1,2 @@\n"
            "-old\n"
            "+new\n"
            "diff --git a/b.py b/b.py\n"
            "--- a/b.py\n"
            "+++ b/b.py\n"
            "@@ -1,2 +1,3 @@\n"
            " ctx\n"
            "+added\n"
        )
        result = parse_diff(raw)
        assert len(result) == 2
        assert result[0].path == "a.py"
        assert result[1].path == "b.py"

    def test_parse_new_file(self):
        """A new file has --- /dev/null and status='added'."""
        raw = (
            "diff --git a/new.py b/new.py\n"
            "--- /dev/null\n"
            "+++ b/new.py\n"
            "@@ -0,0 +1,3 @@\n"
            "+line1\n"
            "+line2\n"
            "+line3\n"
        )
        result = parse_diff(raw)
        assert len(result) == 1
        df = result[0]
        assert df.path == "new.py"
        assert df.status == "added"
        assert df.additions == 3
        assert df.deletions == 0

    def test_parse_deleted_file(self):
        """A deleted file has +++ /dev/null and status='deleted'."""
        raw = (
            "diff --git a/old.py b/old.py\n"
            "--- a/old.py\n"
            "+++ /dev/null\n"
            "@@ -1,2 +0,0 @@\n"
            "-line1\n"
            "-line2\n"
        )
        result = parse_diff(raw)
        assert len(result) == 1
        df = result[0]
        assert df.path == "old.py"
        assert df.status == "deleted"
        assert df.additions == 0
        assert df.deletions == 2

    def test_parse_renamed_file(self):
        """A renamed file has rename from/to and status='renamed'."""
        raw = (
            "diff --git a/old_name.py b/new_name.py\n"
            "similarity index 95%\n"
            "rename from old_name.py\n"
            "rename to new_name.py\n"
            "--- a/old_name.py\n"
            "+++ b/new_name.py\n"
            "@@ -1,3 +1,3 @@\n"
            " same\n"
            "-old\n"
            "+new\n"
        )
        result = parse_diff(raw)
        assert len(result) == 1
        df = result[0]
        assert df.path == "new_name.py"
        assert df.old_path == "old_name.py"
        assert df.status == "renamed"

    def test_parse_binary_file(self):
        """A binary file has 'Binary files' line and is_binary=True."""
        raw = (
            "diff --git a/image.png b/image.png\n"
            "Binary files a/image.png and b/image.png differ\n"
        )
        result = parse_diff(raw)
        assert len(result) == 1
        df = result[0]
        assert df.is_binary is True
        assert df.hunks == []

    def test_parse_hunks(self):
        """Verify DiffHunk objects are correctly populated."""
        raw = (
            "diff --git a/foo.py b/foo.py\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -10,5 +10,6 @@ def existing()\n"
            " ctx\n"
            "+new_line\n"
            "@@ -30,3 +31,4 @@ class Bar\n"
            " ctx\n"
            "-removed\n"
            "+added1\n"
            "+added2\n"
        )
        result = parse_diff(raw)
        assert len(result) == 1
        df = result[0]
        assert len(df.hunks) == 2

        h0 = df.hunks[0]
        assert h0.old_start == 10
        assert h0.old_count == 5
        assert h0.new_start == 10
        assert h0.new_count == 6

        h1 = df.hunks[1]
        assert h1.old_start == 30
        assert h1.old_count == 3
        assert h1.new_start == 31
        assert h1.new_count == 4

    def test_parse_hunk_header_context(self):
        """The text after @@ markers is captured as header."""
        raw = (
            "diff --git a/foo.py b/foo.py\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -1,3 +1,4 @@ def foo()\n"
            " ctx\n"
            "+new\n"
        )
        result = parse_diff(raw)
        assert result[0].hunks[0].header == "def foo()"

    def test_parse_addition_deletion_counts(self):
        """Verify additions and deletions are counted correctly."""
        raw = (
            "diff --git a/foo.py b/foo.py\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -1,5 +1,6 @@\n"
            " ctx\n"
            "-del1\n"
            "-del2\n"
            "+add1\n"
            "+add2\n"
            "+add3\n"
            " ctx\n"
        )
        result = parse_diff(raw)
        df = result[0]
        assert df.additions == 3
        assert df.deletions == 2

    def test_parse_empty_diff(self):
        """Empty string returns empty list."""
        assert parse_diff("") == []
        assert parse_diff("   ") == []

    def test_parse_diff_with_no_newline_marker(self):
        r"""Handle '\ No newline at end of file' lines gracefully."""
        raw = (
            "diff --git a/foo.py b/foo.py\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -1,2 +1,2 @@\n"
            "-old\n"
            "+new\n"
            "\\ No newline at end of file\n"
        )
        result = parse_diff(raw)
        assert len(result) == 1
        df = result[0]
        # The backslash line should NOT count as an addition or deletion
        assert df.additions == 1
        assert df.deletions == 1

    def test_parse_path_with_spaces(self):
        """Handle file paths that contain spaces."""
        raw = (
            "diff --git a/my dir/my file.py b/my dir/my file.py\n"
            "--- a/my dir/my file.py\n"
            "+++ b/my dir/my file.py\n"
            "@@ -1,2 +1,3 @@\n"
            " ctx\n"
            "+new\n"
        )
        result = parse_diff(raw)
        assert len(result) == 1
        assert result[0].path == "my dir/my file.py"


# ---------------------------------------------------------------------------
# TestExtractSymbolHints (4 tests)
# ---------------------------------------------------------------------------


class TestExtractSymbolHints:
    """Tests for extract_symbol_hints()."""

    def test_extract_python_function(self):
        """Header 'def my_function()' yields ['my_function']."""
        hunks = [DiffHunk(header="def my_function()")]
        result = extract_symbol_hints(hunks)
        assert "my_function" in result

    def test_extract_python_class(self):
        """Header 'class MyClass:' yields ['MyClass']."""
        hunks = [DiffHunk(header="class MyClass:")]
        result = extract_symbol_hints(hunks)
        assert "MyClass" in result

    def test_extract_empty_header(self):
        """Empty header yields empty list."""
        hunks = [DiffHunk(header="")]
        result = extract_symbol_hints(hunks)
        assert result == []

    def test_extract_deduplication(self):
        """Duplicate symbol names across hunks are deduplicated."""
        hunks = [
            DiffHunk(header="def foo()"),
            DiffHunk(header="def foo()"),
            DiffHunk(header="def bar()"),
        ]
        result = extract_symbol_hints(hunks)
        assert result.count("foo") == 1
        assert "bar" in result
        assert len(result) == 2

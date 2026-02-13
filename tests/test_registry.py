"""Tests for the recognizer registry (codegiraffe.registry)."""

import pytest
from pathlib import Path

from codegiraffe.graph import Node
from codegiraffe.registry import RecognizerRegistry, get_default_registry, register_recognizer
from codegiraffe.scanner import (
    PatternRecognizer,
    PythonRecognizer,
    ScanResult,
    scan_project,
)
from codegiraffe.schema import NodeType


class _StubRecognizer:
    """Minimal recognizer that produces a single node for any file."""

    def __init__(self, prefix: str = "stub") -> None:
        self._prefix = prefix

    def recognize(self, file_path: Path, content: str) -> ScanResult:
        node_id = f"{self._prefix}:{file_path.name}"
        return ScanResult(
            nodes=[
                Node(
                    id=node_id,
                    type=NodeType.SERVICE,
                    label=file_path.name,
                    file_path=str(file_path),
                )
            ],
            edges=[],
        )


class TestRecognizerRegistry:
    """Tests for RecognizerRegistry class."""

    def test_register_with_extensions(self) -> None:
        """Register a recognizer for .py; verify it shows up for .py files."""
        registry = RecognizerRegistry()
        recognizer = _StubRecognizer()
        registry.register(recognizer, extensions=[".py"])

        result = registry.get_recognizers(Path("foo.py"))
        assert recognizer in result

    def test_register_global(self) -> None:
        """Register without extensions; verify it runs on all file types."""
        registry = RecognizerRegistry()
        recognizer = _StubRecognizer()
        registry.register(recognizer, extensions=None)

        assert recognizer in registry.get_recognizers(Path("foo.py"))
        assert recognizer in registry.get_recognizers(Path("bar.js"))
        assert recognizer in registry.get_recognizers(Path("baz.txt"))

    def test_get_recognizers_no_match(self) -> None:
        """For an unregistered extension, only global recognizers are returned."""
        registry = RecognizerRegistry()
        py_rec = _StubRecognizer("py")
        global_rec = _StubRecognizer("global")
        registry.register(py_rec, extensions=[".py"])
        registry.register(global_rec, extensions=None)

        result = registry.get_recognizers(Path("file.rs"))
        assert global_rec in result
        assert py_rec not in result

    def test_registered_extensions(self) -> None:
        """Property returns the correct set of registered extensions."""
        registry = RecognizerRegistry()
        registry.register(_StubRecognizer(), extensions=[".py", ".pyi"])
        registry.register(_StubRecognizer(), extensions=[".js"])

        assert registry.registered_extensions == {".py", ".pyi", ".js"}

    def test_multiple_recognizers_same_extension(self) -> None:
        """Two recognizers for .py are both returned."""
        registry = RecognizerRegistry()
        rec_a = _StubRecognizer("a")
        rec_b = _StubRecognizer("b")
        registry.register(rec_a, extensions=[".py"])
        registry.register(rec_b, extensions=[".py"])

        result = registry.get_recognizers(Path("module.py"))
        assert rec_a in result
        assert rec_b in result
        assert len(result) == 2

    def test_default_registry_has_python(self) -> None:
        """get_default_registry() includes PythonRecognizer for .py files."""
        # Reset the global default to force re-initialization
        import codegiraffe.registry as reg_mod

        original = reg_mod._default_registry
        try:
            reg_mod._default_registry = None
            registry = get_default_registry()

            assert ".py" in registry.registered_extensions
            assert ".pyi" in registry.registered_extensions

            recognizers = registry.get_recognizers(Path("test.py"))
            assert len(recognizers) >= 1
            assert any(isinstance(r, PythonRecognizer) for r in recognizers)
        finally:
            reg_mod._default_registry = original

    def test_register_recognizer_convenience(self) -> None:
        """register_recognizer() convenience function works."""
        import codegiraffe.registry as reg_mod

        original = reg_mod._default_registry
        try:
            reg_mod._default_registry = None
            stub = _StubRecognizer("convenience")
            register_recognizer(stub, extensions=[".txt"])

            registry = get_default_registry()
            result = registry.get_recognizers(Path("readme.txt"))
            assert stub in result
        finally:
            reg_mod._default_registry = original

    def test_global_and_extension_recognizers_combined(self) -> None:
        """Global recognizers are combined with extension-specific ones."""
        registry = RecognizerRegistry()
        global_rec = _StubRecognizer("global")
        py_rec = _StubRecognizer("py")
        registry.register(global_rec, extensions=None)
        registry.register(py_rec, extensions=[".py"])

        result = registry.get_recognizers(Path("foo.py"))
        assert global_rec in result
        assert py_rec in result
        assert len(result) == 2

    def test_registered_extensions_empty_initially(self) -> None:
        """A fresh registry has no registered extensions."""
        registry = RecognizerRegistry()
        assert registry.registered_extensions == set()

    def test_case_insensitive_suffix_matching(self) -> None:
        """File suffix matching is case-insensitive."""
        registry = RecognizerRegistry()
        recognizer = _StubRecognizer()
        registry.register(recognizer, extensions=[".py"])

        # Path.suffix preserves case, but get_recognizers lowercases it
        result = registry.get_recognizers(Path("Module.PY"))
        assert recognizer in result


class TestScanProjectWithRegistry:
    """Tests for scan_project() with the registry parameter."""

    def test_scan_project_with_registry(self, tmp_path: Path) -> None:
        """Register a mock recognizer for .txt, scan a project, verify nodes found."""
        # Create .txt files in the project
        (tmp_path / "notes.txt").write_text("some text content")
        (tmp_path / "config.txt").write_text("key=value")

        registry = RecognizerRegistry()
        registry.register(_StubRecognizer("txt"), extensions=[".txt"])

        result = scan_project(str(tmp_path), registry=registry)

        node_ids = {n.id for n in result.nodes}
        assert "txt:notes.txt" in node_ids
        assert "txt:config.txt" in node_ids

    def test_scan_project_registry_ignores_unregistered_extensions(
        self, tmp_path: Path
    ) -> None:
        """Files with unregistered extensions are skipped."""
        (tmp_path / "code.py").write_text("x = 1")
        (tmp_path / "data.txt").write_text("hello")

        registry = RecognizerRegistry()
        registry.register(_StubRecognizer("txt"), extensions=[".txt"])

        result = scan_project(str(tmp_path), registry=registry)

        node_ids = {n.id for n in result.nodes}
        assert "txt:data.txt" in node_ids
        # .py should not be scanned because no .py recognizer is registered
        assert not any("code.py" in nid for nid in node_ids)

    def test_scan_project_global_recognizer_scans_all_files(
        self, tmp_path: Path
    ) -> None:
        """A global recognizer runs on every file."""
        (tmp_path / "a.py").write_text("pass")
        (tmp_path / "b.js").write_text("// js")
        (tmp_path / "c.txt").write_text("text")

        registry = RecognizerRegistry()
        registry.register(_StubRecognizer("all"), extensions=None)

        result = scan_project(str(tmp_path), registry=registry)

        node_ids = {n.id for n in result.nodes}
        assert "all:a.py" in node_ids
        assert "all:b.js" in node_ids
        assert "all:c.txt" in node_ids

    def test_scan_project_legacy_recognizers_still_work(
        self, sample_project: Path
    ) -> None:
        """Passing recognizers= (legacy) still works as before."""
        result = scan_project(
            str(sample_project), recognizers=[PythonRecognizer()]
        )

        endpoint_ids = {n.id for n in result.nodes if n.type == NodeType.ENDPOINT}
        assert "endpoint:/api/users" in endpoint_ids

    def test_scan_project_default_registry_works(
        self, sample_project: Path
    ) -> None:
        """Calling scan_project() with no args uses the default registry."""
        result = scan_project(str(sample_project))

        endpoint_ids = {n.id for n in result.nodes if n.type == NodeType.ENDPOINT}
        assert "endpoint:/api/users" in endpoint_ids

    def test_scan_project_registry_skips_ignored_dirs(
        self, tmp_path: Path
    ) -> None:
        """Registry-based scan still respects _should_skip()."""
        ignored = tmp_path / ".git"
        ignored.mkdir()
        (ignored / "secret.txt").write_text("hidden")
        (tmp_path / "visible.txt").write_text("public")

        registry = RecognizerRegistry()
        registry.register(_StubRecognizer("txt"), extensions=[".txt"])

        result = scan_project(str(tmp_path), registry=registry)

        node_ids = {n.id for n in result.nodes}
        assert "txt:visible.txt" in node_ids
        assert "txt:secret.txt" not in node_ids

    def test_scan_project_registry_takes_precedence_over_recognizers(
        self, tmp_path: Path
    ) -> None:
        """When both registry and recognizers are provided, registry wins."""
        (tmp_path / "data.txt").write_text("hello")
        (tmp_path / "code.py").write_text("x = 1")

        registry = RecognizerRegistry()
        registry.register(_StubRecognizer("txt"), extensions=[".txt"])

        # Pass both: registry should take precedence
        result = scan_project(
            str(tmp_path),
            recognizers=[PythonRecognizer()],
            registry=registry,
        )

        node_ids = {n.id for n in result.nodes}
        assert "txt:data.txt" in node_ids
        # .py should not produce stub results because registry doesn't have .py
        assert not any("code.py" in nid for nid in node_ids)

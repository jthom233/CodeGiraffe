"""Recognizer registry for plugin system.

Provides a registry that maps file extensions to pattern recognizers,
enabling language-agnostic scanning. Recognizers can be registered for
specific file extensions or globally (to run on all files).
"""

from __future__ import annotations

from pathlib import Path

from codegiraffe.scanner import PatternRecognizer, ScanResult


class RecognizerRegistry:
    """Registry for pattern recognizers with file extension mapping."""

    def __init__(self) -> None:
        self._recognizers: dict[str, list[PatternRecognizer]] = {}  # extension -> [recognizers]
        self._global_recognizers: list[PatternRecognizer] = []  # run on all files

    def register(
        self,
        recognizer: PatternRecognizer,
        extensions: list[str] | None = None,
    ) -> None:
        """Register a recognizer for specific file extensions.

        If *extensions* is ``None``, the recognizer runs on all files.
        Extensions should include the dot (e.g., ``['.py', '.pyi']``).
        """
        if extensions is None:
            self._global_recognizers.append(recognizer)
        else:
            for ext in extensions:
                self._recognizers.setdefault(ext, []).append(recognizer)

    def get_recognizers(self, file_path: Path) -> list[PatternRecognizer]:
        """Return all recognizers applicable to a given file path."""
        suffix = file_path.suffix.lower()
        result = list(self._global_recognizers)
        result.extend(self._recognizers.get(suffix, []))
        return result

    @property
    def registered_extensions(self) -> set[str]:
        """Return all registered file extensions."""
        return set(self._recognizers.keys())


# ---------------------------------------------------------------------------
# Default registry
# ---------------------------------------------------------------------------

_default_registry: RecognizerRegistry | None = None


def get_default_registry() -> RecognizerRegistry:
    """Return the default recognizer registry with built-in recognizers.

    Lazily creates and populates the registry on first call. Registers
    recognizers for Python, TypeScript, Go, Rust, and Java files.
    """
    global _default_registry
    if _default_registry is None:
        _default_registry = RecognizerRegistry()
        from codegiraffe.recognizers import (
            GoRecognizer,
            JavaRecognizer,
            RustRecognizer,
            TypeScriptRecognizer,
        )
        from codegiraffe.scanner import PythonRecognizer

        _default_registry.register(PythonRecognizer(), extensions=[".py", ".pyi"])
        _default_registry.register(
            TypeScriptRecognizer(), extensions=[".ts", ".tsx", ".mts", ".cts"]
        )
        _default_registry.register(GoRecognizer(), extensions=[".go"])
        _default_registry.register(RustRecognizer(), extensions=[".rs"])
        _default_registry.register(JavaRecognizer(), extensions=[".java"])
    return _default_registry


def register_recognizer(
    recognizer: PatternRecognizer,
    extensions: list[str] | None = None,
) -> None:
    """Convenience function to register a recognizer in the default registry."""
    get_default_registry().register(recognizer, extensions)

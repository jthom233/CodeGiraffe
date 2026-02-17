"""Code Giraffe - Architecture knowledge graph MCP server."""

__version__ = "0.11.0"

from codegiraffe.registry import RecognizerRegistry, get_default_registry, register_recognizer

__all__ = [
    "RecognizerRegistry",
    "get_default_registry",
    "register_recognizer",
]

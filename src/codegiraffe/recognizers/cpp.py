"""C/C++ pattern recognizer for Code Giraffe.

Detects architectural patterns in .c, .cpp, .h, .hpp, .cc, .cxx files including:
    - #include directives (local)        -> ImportInfo (imports edges between modules)
    - C++ class with inheritance         -> service nodes
    - Socket patterns                    -> queue nodes (kind=socket)
    - getenv() calls                     -> env_var nodes
    - curl patterns                      -> external_api nodes
    - #define macros                     -> config nodes
"""

from __future__ import annotations

import re
from pathlib import Path

from codegiraffe.graph import Edge, Node
from codegiraffe.scanner import ScanResult, ImportInfo, ImplementationInfo
from codegiraffe.schema import NodeType

# ---------------------------------------------------------------------------
# Compiled regex patterns
# ---------------------------------------------------------------------------

# Local #include directives (double-quoted only, not system <...> includes)
_CPP_INCLUDE_RE = re.compile(r'#include\s+"([^"]+)"')

# Socket function calls
_CPP_SOCKET_RE = re.compile(r"\b(socket|connect|bind|listen|accept)\s*\(")

# getenv() calls
_CPP_GETENV_RE = re.compile(r'getenv\s*\(\s*"(\w+)"')

# curl CURLOPT_URL patterns
_CPP_CURL_RE = re.compile(r'CURLOPT_URL\s*,\s*"(https?://[^"]+)"')

# #define macros
_CPP_DEFINE_RE = re.compile(r"#define\s+(\w+)\s+(.+)")

# Include guard suffixes to exclude from config nodes
_CPP_INCLUDE_GUARD_SUFFIXES = ("_H", "_H_", "_HPP", "_HPP_")

_CPP_CLASS_INHERITANCE_RE = re.compile(r'class\s+(\w+)\s*:\s*((?:(?:public|private|protected)\s+\w+\s*,?\s*)+)')
_CPP_BASE_CLASS_RE = re.compile(r'(?:public|private|protected)\s+(\w+)')


# ---------------------------------------------------------------------------
# Recognizer
# ---------------------------------------------------------------------------


class CppRecognizer:
    """Recognizes common C/C++ architectural patterns via regex.

    Detected patterns:
        - ``#include "..."`` local includes      -> ``ImportInfo`` (imports edges between modules)
        - C++ class with inheritance             -> ``service`` nodes
        - Socket function calls                  -> ``queue`` nodes (kind=socket)
        - ``getenv()`` calls                     -> ``env_var`` nodes
        - curl ``CURLOPT_URL`` patterns          -> ``external_api`` nodes
        - ``#define`` macros                     -> ``config`` nodes

    Note: Plain structs and plain classes without inheritance are NOT mapped to service
    nodes — C structs are data structures and C functions are not services.  Only C++
    classes that explicitly inherit (``class Foo : public Bar``) are treated as service
    nodes since those are more likely to be actual service/component implementations.
    """

    def recognize(self, file_path: Path, content: str) -> ScanResult:
        """Scan *content* of a C/C++ file and return discovered nodes/edges."""
        nodes: list[Node] = []
        edges: list[Edge] = []
        rel_path = file_path.as_posix()
        filename_stem = file_path.stem

        captured_names: set[str] = set()

        # --- Socket patterns -> QUEUE (kind=socket) ---
        seen_socket = False
        for match in _CPP_SOCKET_RE.finditer(content):
            if not seen_socket:
                seen_socket = True
                node_id = f"queue:socket:{filename_stem}"
                nodes.append(
                    Node(
                        id=node_id,
                        type=NodeType.QUEUE,
                        label=f"socket:{filename_stem}",
                        file_path=rel_path,
                        metadata={"kind": "socket"},
                    )
                )

        # --- getenv() -> ENV_VAR ---
        seen_env_vars: set[str] = set()
        for match in _CPP_GETENV_RE.finditer(content):
            var_name = match.group(1)
            if var_name not in seen_env_vars:
                seen_env_vars.add(var_name)
                node_id = f"env:{var_name}"
                nodes.append(
                    Node(
                        id=node_id,
                        type=NodeType.ENV_VAR,
                        label=var_name,
                        file_path=rel_path,
                        metadata={"variable": var_name},
                    )
                )

        # --- curl patterns -> EXTERNAL_API ---
        seen_urls: set[str] = set()
        for match in _CPP_CURL_RE.finditer(content):
            url = match.group(1)
            if url not in seen_urls:
                seen_urls.add(url)
                node_id = f"api:{url}"
                nodes.append(
                    Node(
                        id=node_id,
                        type=NodeType.EXTERNAL_API,
                        label=url,
                        file_path=rel_path,
                        metadata={"url": url},
                    )
                )

        # --- C++ classes with inheritance -> SERVICE ---
        # Only classes that explicitly inherit are treated as service nodes.
        # Plain structs and classes without inheritance are data structures, not services.
        for match in _CPP_CLASS_INHERITANCE_RE.finditer(content):
            class_name = match.group(1)
            if class_name not in captured_names:
                captured_names.add(class_name)
                node_id = f"service:{class_name}"
                nodes.append(
                    Node(
                        id=node_id,
                        type=NodeType.SERVICE,
                        label=class_name,
                        file_path=rel_path,
                        metadata={"kind": "class"},
                    )
                )

        # --- #define macros -> CONFIG ---
        seen_defines: set[str] = set()
        for match in _CPP_DEFINE_RE.finditer(content):
            macro_name = match.group(1)
            # Exclude include guards
            if macro_name.endswith(_CPP_INCLUDE_GUARD_SUFFIXES):
                continue
            if macro_name not in seen_defines:
                seen_defines.add(macro_name)
                node_id = f"config:{macro_name}"
                nodes.append(
                    Node(
                        id=node_id,
                        type=NodeType.CONFIG,
                        label=macro_name,
                        file_path=rel_path,
                        metadata={"macro": macro_name, "value": match.group(2).strip()},
                    )
                )

        # --- #include (local only) -> ImportInfo (imports edges between modules) ---
        imports: list[ImportInfo] = []
        for match in _CPP_INCLUDE_RE.finditer(content):
            include_path = match.group(1)
            # Strip header extension before converting path separators
            for ext in (".h", ".hpp", ".hxx", ".hh"):
                if include_path.endswith(ext):
                    include_path = include_path[: -len(ext)]
                    break
            module_path = include_path.replace("/", ".")
            imports.append(ImportInfo(module_path=module_path, style="absolute"))

        # --- Class inheritance -> ImplementationInfo ---
        implementations: list[ImplementationInfo] = []
        for match in _CPP_CLASS_INHERITANCE_RE.finditer(content):
            child = match.group(1)
            for base_match in _CPP_BASE_CLASS_RE.finditer(match.group(2)):
                implementations.append(ImplementationInfo(child_class=child, parent_class=base_match.group(1), file_path=file_path.as_posix()))

        return ScanResult(nodes=nodes, edges=edges, imports=imports, implementations=implementations)

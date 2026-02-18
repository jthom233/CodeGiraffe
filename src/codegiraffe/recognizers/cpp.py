"""C/C++ pattern recognizer for Code Giraffe.

Detects architectural patterns in .c, .cpp, .h, .hpp, .cc, .cxx files including:
    - #include directives (local)        -> depends_on edges
    - Struct/class definitions           -> service nodes
    - Socket patterns                    -> queue nodes (kind=socket)
    - getenv() calls                     -> env_var nodes
    - curl patterns                      -> external_api nodes
    - Function definitions               -> service nodes
    - #define macros                      -> config nodes
"""

from __future__ import annotations

import re
from pathlib import Path

from codegiraffe.graph import Edge, Node
from codegiraffe.scanner import ScanResult, ImportInfo, ImplementationInfo
from codegiraffe.schema import EdgeType, NodeType

# ---------------------------------------------------------------------------
# Compiled regex patterns
# ---------------------------------------------------------------------------

# Local #include directives (double-quoted only, not system <...> includes)
_CPP_INCLUDE_RE = re.compile(r'#include\s+"([^"]+)"')

# Struct/class definitions
_CPP_STRUCT_CLASS_RE = re.compile(r"(?:struct|class)\s+(\w+)\s*(?:[:{])")

# Socket function calls
_CPP_SOCKET_RE = re.compile(r"\b(socket|connect|bind|listen|accept)\s*\(")

# getenv() calls
_CPP_GETENV_RE = re.compile(r'getenv\s*\(\s*"(\w+)"')

# curl CURLOPT_URL patterns
_CPP_CURL_RE = re.compile(r'CURLOPT_URL\s*,\s*"(https?://[^"]+)"')

# Function definitions (at start of line or after whitespace)
_CPP_FUNC_RE = re.compile(
    r"^(?:static\s+)?(?:inline\s+)?(?:const\s+)?(?:unsigned\s+)?"
    r"(?:void|int|char|float|double|bool|size_t|long|short|auto|\w+(?:\s*\*+)?)"
    r"\s+(\w+)\s*\([^)]*\)\s*\{",
    re.MULTILINE,
)

# Control flow keywords to exclude from function detection
_CPP_CONTROL_FLOW = frozenset(
    {"if", "while", "for", "switch", "return", "else", "do", "sizeof", "typeof"}
)

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
        - ``#include "..."`` local includes      -> ``depends_on`` edges
        - Struct/class definitions                -> ``service`` nodes
        - Socket function calls                   -> ``queue`` nodes (kind=socket)
        - ``getenv()`` calls                      -> ``env_var`` nodes
        - curl ``CURLOPT_URL`` patterns           -> ``external_api`` nodes
        - Function definitions                    -> ``service`` nodes
        - ``#define`` macros                      -> ``config`` nodes
    """

    def recognize(self, file_path: Path, content: str) -> ScanResult:
        """Scan *content* of a C/C++ file and return discovered nodes/edges."""
        nodes: list[Node] = []
        edges: list[Edge] = []
        rel_path = file_path.as_posix()
        filename_stem = file_path.stem

        captured_names: set[str] = set()

        # Service node for the current file (used as edge source)
        file_service_id = f"service:{filename_stem}"

        # --- #include (local only) -> DEPENDS_ON edges ---
        seen_includes: set[str] = set()
        for match in _CPP_INCLUDE_RE.finditer(content):
            include_path = match.group(1)
            if include_path not in seen_includes:
                seen_includes.add(include_path)
                # Strip directory and extension to get module name
                include_stem = Path(include_path).stem
                target_id = f"service:{include_stem}"
                nodes.append(
                    Node(
                        id=target_id,
                        type=NodeType.SERVICE,
                        label=include_stem,
                        file_path=rel_path,
                        metadata={"include": include_path},
                    )
                )
                edges.append(
                    Edge(
                        source=file_service_id,
                        target=target_id,
                        type=EdgeType.DEPENDS_ON,
                        metadata={"include": include_path},
                    )
                )
                captured_names.add(include_stem)

        if seen_includes and filename_stem not in captured_names:
            captured_names.add(filename_stem)
            nodes.append(
                Node(
                    id=file_service_id,
                    type=NodeType.SERVICE,
                    label=filename_stem,
                    file_path=rel_path,
                    metadata={"kind": "compilation_unit"},
                )
            )

        # --- Struct/class definitions -> SERVICE ---
        for match in _CPP_STRUCT_CLASS_RE.finditer(content):
            name = match.group(1)
            if name not in captured_names:
                captured_names.add(name)
                node_id = f"service:{name}"
                nodes.append(
                    Node(
                        id=node_id,
                        type=NodeType.SERVICE,
                        label=name,
                        file_path=rel_path,
                        metadata={"kind": "struct_or_class"},
                    )
                )

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

        # --- Function definitions -> SERVICE ---
        for match in _CPP_FUNC_RE.finditer(content):
            func_name = match.group(1)
            if func_name not in _CPP_CONTROL_FLOW and func_name not in captured_names:
                captured_names.add(func_name)
                node_id = f"service:{func_name}"
                nodes.append(
                    Node(
                        id=node_id,
                        type=NodeType.SERVICE,
                        label=func_name,
                        file_path=rel_path,
                        metadata={"kind": "function"},
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

        imports: list[ImportInfo] = []
        # Re-scan for local includes to generate ImportInfo
        for match in _CPP_INCLUDE_RE.finditer(content):
            include_path = match.group(1)
            # Strip header extension before converting path separators
            for ext in (".h", ".hpp", ".hxx", ".hh"):
                if include_path.endswith(ext):
                    include_path = include_path[: -len(ext)]
                    break
            module_path = include_path.replace("/", ".")
            imports.append(ImportInfo(module_path=module_path, style="absolute"))

        implementations: list[ImplementationInfo] = []
        for match in _CPP_CLASS_INHERITANCE_RE.finditer(content):
            child = match.group(1)
            for base_match in _CPP_BASE_CLASS_RE.finditer(match.group(2)):
                implementations.append(ImplementationInfo(child_class=child, parent_class=base_match.group(1), file_path=file_path.as_posix()))

        return ScanResult(nodes=nodes, edges=edges, imports=imports, implementations=implementations)

"""Lua pattern recognizer for Code Giraffe.

Detects architectural patterns in .lua files including:
    - require() / dofile() / loadfile()          -> ImportInfo
    - Table-as-class patterns (setmetatable, extend, new, subclass, create)
                                                  -> service nodes
    - os.getenv() access                          -> env_var nodes
    - LibStub() (WoW addon library loading)       -> external_api nodes
    - C_Namespace.Function() (WoW C API)          -> external_api nodes
    - RegisterEvent() (WoW event registration)    -> event nodes
    - RegisterChatCommand() (WoW slash commands)  -> endpoint nodes
    - :SetScript("OnUpdate", ...) frames          -> worker nodes
"""

from __future__ import annotations

import re
from pathlib import Path

from codegiraffe.graph import Edge, Node
from codegiraffe.scanner import ImportInfo, ScanResult
from codegiraffe.schema import NodeType

# ---------------------------------------------------------------------------
# Compiled regex patterns
# ---------------------------------------------------------------------------

# require("module") or require 'module' (with/without parens)
_LUA_REQUIRE_RE = re.compile(r"""\brequire\s*[\(]?\s*["']([^"']+)["']\s*[\)]?""")

# dofile("path") / loadfile("path")
_LUA_DOFILE_RE = re.compile(r"""\b(?:dofile|loadfile)\s*\(\s*["']([^"']+)["']\s*\)""")

# Table-as-class patterns — only PascalCase names to reduce noise
# Matches: MyClass = setmetatable({...}, ...) or MyClass = Base:extend(...)
_LUA_CLASS_RE = re.compile(
    r"""^\s*(?:local\s+)?([A-Z]\w+)\s*=\s*(?:setmetatable\s*\(|(\w+):(?:extend|new|subclass|create)\s*\()""",
    re.MULTILINE,
)

# os.getenv("KEY")
_LUA_ENV_RE = re.compile(r"""os\.getenv\s*\(\s*["']([^"']+)["']\s*\)""")

# LibStub("LibName") — WoW addon library system
_LUA_LIBSTUB_RE = re.compile(r"""LibStub\s*\(\s*["']([^"']+)["']\s*\)""")

# C_Namespace.Method — WoW C API namespaces.
# No trailing \( required so aliased references like
#   local GetBuff = C_UnitAuras.GetBuffDataByIndex
# are also captured alongside direct calls.
_LUA_WOW_API_RE = re.compile(r"""\b(C_\w+)\.\w+""")

# RegisterEvent("EVENT_NAME", ...) or :RegisterEvent("EVENT_NAME")
_LUA_EVENT_RE = re.compile(r"""(?::|\b)RegisterEvent\s*\(\s*["']([A-Z0-9_]+)["']""")

# RegisterChatCommand("cmd", ...) — WoW slash command registration
_LUA_SLASH_CMD_RE = re.compile(r"""RegisterChatCommand\s*\(\s*["'](/?[\w-]+)["']""")

# :SetScript("OnUpdate", ...) — WoW OnUpdate frame handler
_LUA_ONUPDATE_RE = re.compile(r""":SetScript\s*\(\s*["']OnUpdate["']""")

# LibStub("AceAddon-3.0"):NewAddon("AddonName", ...) — main addon object
_LUA_NEWADDON_RE = re.compile(
    r"""LibStub\s*\(\s*["']AceAddon[^"']*["']\s*\)\s*:\s*NewAddon\s*\(\s*["']([^"']+)["']"""
)

# Block comments: --[[ ... ]]  (with optional equals: --[==[...]==])
# Uses a backreference so the closing delimiter must match the opening one.
_LUA_BLOCK_COMMENT_RE = re.compile(r"--\[(=*)\[.*?\]\1\]", re.DOTALL)

# Long strings: [[ ... ]] or [=[ ... ]=] etc. (multi-line string literals)
# Uses a backreference so the closing delimiter must match the opening one.
_LUA_LONG_STRING_RE = re.compile(r"\[(=*)\[.*?\]\1\]", re.DOTALL)

# Line comments: -- ... (after block comments are stripped)
_LUA_LINE_COMMENT_RE = re.compile(r"--[^\n]*")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strip_lua_comments_and_long_strings(content: str) -> str:
    """Strip Lua block comments, long strings, and line comments.

    Order matters:
    1. Block comments (``--[[ ... ]]``) — these start with ``--`` so must be
       removed before line comments.
    2. Long strings (``[[ ... ]]``) — raw multi-line literals that can contain
       arbitrary content (e.g. WoW addon encoded pack data).
    3. Line comments (``-- ...``).

    Newlines inside removed spans are preserved (replaced with spaces that
    do not contain ``\\n``) so that ``re.MULTILINE`` line anchors used by
    the class/function patterns still work correctly against the surrounding
    code.  We substitute with a single space rather than an empty string to
    avoid accidentally merging adjacent tokens.
    """
    # Step 1: remove block comments (--[[ ... ]])
    result = _LUA_BLOCK_COMMENT_RE.sub(
        lambda m: "\n" * m.group(0).count("\n") + " ",
        content,
    )
    # Step 2: remove long strings ([[ ... ]])
    result = _LUA_LONG_STRING_RE.sub(
        lambda m: "\n" * m.group(0).count("\n") + " ",
        result,
    )
    # Step 3: remove line comments (-- ...)
    result = _LUA_LINE_COMMENT_RE.sub("", result)
    return result


# ---------------------------------------------------------------------------
# Recognizer
# ---------------------------------------------------------------------------


class LuaRecognizer:
    """Lua pattern recognizer for CodeGiraffe.

    Detects:
    - require/dofile/loadfile imports
    - Table-as-class patterns (setmetatable, extend, new, subclass, create)
    - os.getenv environment variables
    - WoW addon patterns: LibStub, C_* APIs, RegisterEvent, slash commands,
      OnUpdate workers
    """

    def recognize(self, file_path: Path, content: str) -> ScanResult:
        """Scan *content* of a Lua file and return discovered nodes/edges."""
        rel_path = file_path.as_posix()
        nodes: list[Node] = []
        edges: list[Edge] = []
        imports: list[ImportInfo] = []

        # Strip comments and long strings before any pattern matching.
        stripped = _strip_lua_comments_and_long_strings(content)

        seen_nodes: set[str] = set()

        # --- Imports: require() ---
        for match in _LUA_REQUIRE_RE.finditer(stripped):
            module_path = match.group(1)
            imports.append(ImportInfo(module_path=module_path, style="absolute"))

        # --- Imports: dofile() / loadfile() ---
        for match in _LUA_DOFILE_RE.finditer(stripped):
            file_ref = match.group(1)
            imports.append(ImportInfo(module_path=file_ref, style="absolute"))

        # --- Service nodes: LibStub AceAddon NewAddon (main addon object) ---
        # Process BEFORE class patterns so the addon name is in seen_nodes and
        # won't be duplicated if a class pattern also matches the same name.
        for match in _LUA_NEWADDON_RE.finditer(stripped):
            addon_name = match.group(1)
            node_id = f"service:{addon_name}"
            if node_id not in seen_nodes:
                seen_nodes.add(node_id)
                nodes.append(
                    Node(
                        id=node_id,
                        type=NodeType.SERVICE,
                        label=addon_name,
                        file_path=rel_path,
                        metadata={
                            "class_name": addon_name,
                            "language": "lua",
                            "framework": "wow-aceaddon",
                        },
                    )
                )

        # --- Service nodes: table-as-class patterns ---
        for match in _LUA_CLASS_RE.finditer(stripped):
            class_name = match.group(1)
            node_id = f"service:{class_name}"
            if node_id not in seen_nodes:
                seen_nodes.add(node_id)
                nodes.append(
                    Node(
                        id=node_id,
                        type=NodeType.SERVICE,
                        label=class_name,
                        file_path=rel_path,
                        metadata={"class_name": class_name, "language": "lua"},
                    )
                )

        # --- Environment variables: os.getenv() ---
        seen_env: set[str] = set()
        for match in _LUA_ENV_RE.finditer(stripped):
            var_name = match.group(1)
            if var_name not in seen_env:
                seen_env.add(var_name)
                node_id = f"env:{var_name}"
                if node_id not in seen_nodes:
                    seen_nodes.add(node_id)
                    nodes.append(
                        Node(
                            id=node_id,
                            type=NodeType.ENV_VAR,
                            label=var_name,
                            file_path=rel_path,
                            metadata={"variable": var_name},
                        )
                    )

        # --- External API nodes: LibStub() (WoW) ---
        seen_libstub: set[str] = set()
        for match in _LUA_LIBSTUB_RE.finditer(stripped):
            lib_name = match.group(1)
            if lib_name not in seen_libstub:
                seen_libstub.add(lib_name)
                node_id = f"ext:{lib_name}"
                if node_id not in seen_nodes:
                    seen_nodes.add(node_id)
                    nodes.append(
                        Node(
                            id=node_id,
                            type=NodeType.EXTERNAL_API,
                            label=lib_name,
                            file_path=rel_path,
                            metadata={"library": lib_name, "framework": "wow-libstub"},
                        )
                    )

        # --- External API nodes: C_Namespace (WoW C API) ---
        # One node per C_ namespace, not per call.
        seen_apis: set[str] = set()
        for match in _LUA_WOW_API_RE.finditer(stripped):
            namespace = match.group(1)
            if namespace not in seen_apis:
                seen_apis.add(namespace)
                node_id = f"ext:{namespace}"
                if node_id not in seen_nodes:
                    seen_nodes.add(node_id)
                    nodes.append(
                        Node(
                            id=node_id,
                            type=NodeType.EXTERNAL_API,
                            label=namespace,
                            file_path=rel_path,
                            metadata={"namespace": namespace, "framework": "wow-api"},
                        )
                    )

        # --- Event nodes: RegisterEvent() (WoW) ---
        seen_events: set[str] = set()
        for match in _LUA_EVENT_RE.finditer(stripped):
            event_name = match.group(1)
            if event_name not in seen_events:
                seen_events.add(event_name)
                node_id = f"event:{event_name}"
                if node_id not in seen_nodes:
                    seen_nodes.add(node_id)
                    nodes.append(
                        Node(
                            id=node_id,
                            type=NodeType.EVENT,
                            label=event_name,
                            file_path=rel_path,
                            metadata={"event": event_name, "framework": "wow"},
                        )
                    )

        # --- Endpoint nodes: RegisterChatCommand() (WoW slash commands) ---
        seen_commands: set[str] = set()
        for match in _LUA_SLASH_CMD_RE.finditer(stripped):
            cmd = match.group(1)
            # Normalise: ensure leading slash
            if not cmd.startswith("/"):
                cmd = "/" + cmd
            if cmd not in seen_commands:
                seen_commands.add(cmd)
                node_id = f"endpoint:{cmd}"
                if node_id not in seen_nodes:
                    seen_nodes.add(node_id)
                    nodes.append(
                        Node(
                            id=node_id,
                            type=NodeType.ENDPOINT,
                            label=cmd,
                            file_path=rel_path,
                            metadata={"command": cmd, "framework": "wow"},
                        )
                    )

        # --- Worker nodes: :SetScript("OnUpdate", ...) ---
        # One worker node per file that uses this pattern. The node ID is
        # file-scoped (worker:OnUpdate:<stem>) so multiple files each produce
        # their own distinct node rather than colliding on a single shared ID.
        if _LUA_ONUPDATE_RE.search(stripped):
            module_name = file_path.stem
            node_id = f"worker:OnUpdate:{module_name}"
            nodes.append(
                Node(
                    id=node_id,
                    type=NodeType.WORKER,
                    label="OnUpdate",
                    file_path=rel_path,
                    metadata={"script": "OnUpdate", "framework": "wow"},
                )
            )

        return ScanResult(nodes=nodes, edges=edges, imports=imports)

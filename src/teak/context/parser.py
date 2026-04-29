from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

SUPPORTED_LANGUAGES: tuple[str, ...] = ("python", "typescript", "javascript", "rust", "go")


@dataclass(frozen=True)
class ParsedSymbol:
    name: str
    kind: str  # "function" | "class" | "method" | "import"
    file: Path
    start_line: int
    end_line: int
    parent: Optional[str] = None
    body: str = ""


@dataclass
class FileParse:
    file: Path
    language: str
    symbols: list[ParsedSymbol] = field(default_factory=list)
    calls: list[tuple[str, str]] = field(default_factory=list)  # (caller, callee)
    imports: list[str] = field(default_factory=list)


def language_for(path: Path) -> Optional[str]:
    """Map a file extension to a tree-sitter language name."""
    ext = path.suffix.lower()
    return {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "tsx",
        ".js": "javascript",
        ".jsx": "javascript",
        ".rs": "rust",
        ".go": "go",
    }.get(ext)


# Per-language node-type config. Each entry:
#   "definition_types": map[node.type] -> kind
#   "name_field": child field that holds the identifier (or None → first identifier child)
#   "import_types": set of node types treated as imports
#   "call_types": set of node types treated as calls
_LANG_CONFIG: dict[str, dict] = {
    "python": {
        "definition_types": {
            "function_definition": "function",
            "class_definition": "class",
        },
        "name_field": "name",
        "import_types": {"import_statement", "import_from_statement"},
        "call_types": {"call"},
        "method_parent_types": {"class_definition"},
    },
    "javascript": {
        "definition_types": {
            "function_declaration": "function",
            "method_definition": "method",
            "class_declaration": "class",
        },
        "name_field": "name",
        "import_types": {"import_statement"},
        "call_types": {"call_expression"},
        "method_parent_types": {"class_declaration"},
    },
    "typescript": {
        "definition_types": {
            "function_declaration": "function",
            "method_definition": "method",
            "method_signature": "method",
            "class_declaration": "class",
            "interface_declaration": "class",
        },
        "name_field": "name",
        "import_types": {"import_statement"},
        "call_types": {"call_expression"},
        "method_parent_types": {"class_declaration", "interface_declaration"},
    },
    "tsx": {
        "definition_types": {
            "function_declaration": "function",
            "method_definition": "method",
            "class_declaration": "class",
        },
        "name_field": "name",
        "import_types": {"import_statement"},
        "call_types": {"call_expression"},
        "method_parent_types": {"class_declaration"},
    },
    "rust": {
        "definition_types": {
            "function_item": "function",
            "struct_item": "class",
            "enum_item": "class",
            "trait_item": "class",
        },
        "name_field": "name",
        "import_types": {"use_declaration"},
        "call_types": {"call_expression"},
        "method_parent_types": {"impl_item"},
    },
    "go": {
        "definition_types": {
            "function_declaration": "function",
            "method_declaration": "method",
            "type_declaration": "class",
        },
        "name_field": "name",
        "import_types": {"import_declaration", "import_spec"},
        "call_types": {"call_expression"},
        "method_parent_types": set(),
    },
}


def _node_text(node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _identifier_name(node, source: bytes, name_field: Optional[str]) -> Optional[str]:
    if name_field:
        child = node.child_by_field_name(name_field)
        if child is not None:
            return _node_text(child, source)
    for child in node.children:
        if child.type == "identifier" or child.type == "type_identifier":
            return _node_text(child, source)
    return None


def _call_callee_name(call_node, source: bytes) -> Optional[str]:
    fn = call_node.child_by_field_name("function")
    if fn is None and call_node.children:
        fn = call_node.children[0]
    if fn is None:
        return None
    if fn.type in ("identifier", "field_expression", "selector_expression"):
        text = _node_text(fn, source)
        return text.split(".")[-1] or None
    if fn.type == "attribute":
        attr = fn.child_by_field_name("attribute")
        if attr is not None:
            return _node_text(attr, source)
    return None


def _walk_calls_inside(node, source: bytes, call_types: set[str]) -> Iterable[str]:
    stack = list(node.children)
    while stack:
        cur = stack.pop()
        if cur.type in call_types:
            name = _call_callee_name(cur, source)
            if name:
                yield name
        stack.extend(cur.children)


def parse_file(path: Path) -> FileParse:
    """Parse `path` with tree-sitter and return its top-level symbols + edges.

    Returns an empty FileParse for unsupported languages or unreadable files.
    """
    lang = language_for(path)
    if lang is None or lang not in _LANG_CONFIG:
        return FileParse(file=path, language="")

    try:
        from tree_sitter_language_pack import get_parser
    except ImportError:
        return FileParse(file=path, language=lang)

    try:
        source = path.read_bytes()
    except OSError:
        return FileParse(file=path, language=lang)

    parser = get_parser(lang)
    tree = parser.parse(source)
    cfg = _LANG_CONFIG[lang]

    symbols: list[ParsedSymbol] = []
    calls: list[tuple[str, str]] = []
    imports: list[str] = []

    def _kind_with_parent(node, kind: str) -> tuple[str, Optional[str]]:
        if kind != "function":
            return kind, None
        # Walk up to detect class enclosure.
        parent_node = node.parent
        while parent_node is not None:
            if parent_node.type in cfg["method_parent_types"]:
                pname = _identifier_name(parent_node, source, cfg["name_field"])
                return "method", pname
            parent_node = parent_node.parent
        return "function", None

    def _visit(node) -> None:
        if node.type in cfg["import_types"]:
            imports.append(_node_text(node, source).strip())
            return

        kind = cfg["definition_types"].get(node.type)
        if kind is not None:
            name = _identifier_name(node, source, cfg["name_field"])
            if name:
                resolved_kind, parent = _kind_with_parent(node, kind)
                body = _node_text(node, source)
                symbols.append(
                    ParsedSymbol(
                        name=name,
                        kind=resolved_kind,
                        file=path,
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        parent=parent,
                        body=body,
                    )
                )
                # Capture calls inside function/method bodies only.
                if resolved_kind in ("function", "method"):
                    for callee in _walk_calls_inside(node, source, cfg["call_types"]):
                        calls.append((name, callee))
                # Recurse into class bodies to pick up methods, but stop inside
                # function bodies (we only want top-level + methods).
                if resolved_kind == "class":
                    for child in node.children:
                        _visit(child)
                return
        for child in node.children:
            _visit(child)

    _visit(tree.root_node)

    return FileParse(
        file=path,
        language=lang,
        symbols=symbols,
        calls=calls,
        imports=imports,
    )


def parse_files(paths: Iterable[Path]) -> dict[Path, FileParse]:
    return {p: parse_file(p) for p in paths if language_for(p) is not None}

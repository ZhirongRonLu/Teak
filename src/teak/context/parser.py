from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

SUPPORTED_LANGUAGES: tuple[str, ...] = ("python", "typescript", "javascript", "rust", "go")


@dataclass
class ParsedSymbol:
    name: str
    kind: str  # "function" | "class" | "import" | "method"
    file: Path
    start_line: int
    end_line: int
    parent: str | None = None


def language_for(path: Path) -> str | None:
    """Map a file extension to a tree-sitter language name."""
    ext = path.suffix.lower()
    return {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
        ".rs": "rust",
        ".go": "go",
    }.get(ext)


def parse_file(path: Path) -> list[ParsedSymbol]:
    """Parse `path` with tree-sitter and return its top-level symbols."""
    raise NotImplementedError(path)


def parse_files(paths: Iterable[Path]) -> dict[Path, list[ParsedSymbol]]:
    return {p: parse_file(p) for p in paths if language_for(p) is not None}

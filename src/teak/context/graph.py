from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Symbol:
    name: str
    kind: str
    file: Path
    start_line: int
    end_line: int


@dataclass
class KnowledgeGraph:
    """In-memory view of the project's call/import graph.

    Backed by SQLite for durability; this object is the working set used by RAG.
    """

    symbols: dict[str, Symbol] = field(default_factory=dict)
    calls: dict[str, set[str]] = field(default_factory=dict)  # caller -> callees
    imports: dict[Path, set[str]] = field(default_factory=dict)  # file -> imported names

    def add_symbol(self, symbol: Symbol) -> None:
        self.symbols[symbol.name] = symbol

    def add_call(self, caller: str, callee: str) -> None:
        self.calls.setdefault(caller, set()).add(callee)

    def neighbors(self, symbol_name: str, depth: int = 1) -> set[str]:
        """Return symbols reachable from `symbol_name` within `depth` hops."""
        raise NotImplementedError

    def subgraph_for_query(self, seed_symbols: list[str], budget: int) -> "KnowledgeGraph":
        """Return a reduced graph small enough to fit `budget` tokens of context."""
        raise NotImplementedError

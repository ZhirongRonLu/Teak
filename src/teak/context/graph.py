from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from teak.context.storage import VectorStore


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

    Nodes are symbol names. Edges:
      - calls: caller_name -> {callee_name, ...}  (intra- and inter-file)
      - reverse_calls: callee -> {caller, ...}     (used for `neighbors`)
      - imports: file -> {imported_module_name}
    """

    symbols: dict[str, Symbol] = field(default_factory=dict)
    calls: dict[str, set[str]] = field(default_factory=dict)
    reverse_calls: dict[str, set[str]] = field(default_factory=dict)
    imports: dict[Path, set[str]] = field(default_factory=dict)

    def add_symbol(self, symbol: Symbol) -> None:
        self.symbols[symbol.name] = symbol

    def add_call(self, caller: str, callee: str) -> None:
        self.calls.setdefault(caller, set()).add(callee)
        self.reverse_calls.setdefault(callee, set()).add(caller)

    def neighbors(self, symbol_name: str, depth: int = 1) -> set[str]:
        """Symbols reachable from `symbol_name` within `depth` hops, excluding self."""
        if depth < 1:
            return set()
        seen: set[str] = {symbol_name}
        frontier: deque[tuple[str, int]] = deque([(symbol_name, 0)])
        result: set[str] = set()

        while frontier:
            node, d = frontier.popleft()
            if d >= depth:
                continue
            for nxt in self.calls.get(node, set()) | self.reverse_calls.get(node, set()):
                if nxt in seen:
                    continue
                seen.add(nxt)
                result.add(nxt)
                frontier.append((nxt, d + 1))

        return result

    def subgraph_for_query(
        self,
        seed_symbols: list[str],
        token_budget: int,
        chars_per_token: int = 4,
    ) -> "KnowledgeGraph":
        """Reduced graph small enough to fit `token_budget` tokens of context."""
        char_budget = token_budget * chars_per_token
        out = KnowledgeGraph()
        spent = 0

        def _try_add(name: str) -> bool:
            nonlocal spent
            if name in out.symbols:
                return True
            sym = self.symbols.get(name)
            if sym is None:
                return False
            cost = max(1, sym.end_line - sym.start_line + 1) * 40  # rough body estimate
            if spent + cost > char_budget and out.symbols:
                return False
            out.add_symbol(sym)
            spent += cost
            for callee in self.calls.get(name, set()):
                out.calls.setdefault(name, set()).add(callee)
            return True

        # BFS layered: seeds first, then their neighbors at increasing depth.
        layered: deque[tuple[str, int]] = deque((s, 0) for s in seed_symbols)
        seen: set[str] = set(seed_symbols)
        while layered:
            name, depth = layered.popleft()
            if not _try_add(name):
                if not out.symbols:
                    continue
                break
            if depth >= 2:
                continue
            for nxt in self.calls.get(name, set()) | self.reverse_calls.get(name, set()):
                if nxt not in seen:
                    seen.add(nxt)
                    layered.append((nxt, depth + 1))

        return out


def load_graph_from_store(store: VectorStore) -> KnowledgeGraph:
    """Materialize a graph from the persistent SQLite store."""
    graph = KnowledgeGraph()
    with store.connect() as conn:
        rows = conn.execute(
            "SELECT name, kind, file, start_line, end_line FROM symbols"
        ).fetchall()
        for name, kind, file, start, end in rows:
            graph.add_symbol(
                Symbol(name=name, kind=kind, file=Path(file), start_line=start, end_line=end)
            )

        for caller, callee in conn.execute("SELECT caller, callee FROM calls").fetchall():
            graph.add_call(caller, callee)

        for file, statement in conn.execute(
            "SELECT file, statement FROM imports"
        ).fetchall():
            graph.imports.setdefault(Path(file), set()).add(statement)

    return graph

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from teak.context.embedder import Embedder
from teak.context.graph import KnowledgeGraph, load_graph_from_store
from teak.context.storage import SymbolRecord, VectorStore


@dataclass
class RetrievedContext:
    """A bounded slice of project context to send to the LLM."""

    snippets: list[str] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    estimated_tokens: int = 0

    def to_prompt(self) -> str:
        if not self.snippets:
            return ""
        header = "## Relevant project context\n"
        return header + "\n\n".join(self.snippets)


class SubgraphRAG:
    """Retrieve a minimal, relevant code subgraph for a query.

    1. Embed the query.
    2. Find seed symbols via vector search in `VectorStore`.
    3. Expand seeds through `KnowledgeGraph.neighbors` until token budget is hit.
    4. Return concrete source snippets + symbol identifiers.
    """

    def __init__(
        self,
        store: VectorStore,
        embedder: Embedder,
        graph: Optional[KnowledgeGraph] = None,
        chars_per_token: int = 4,
    ) -> None:
        self.store = store
        self.embedder = embedder
        self.graph = graph or load_graph_from_store(store)
        self.chars_per_token = chars_per_token

    def retrieve(
        self,
        query: str,
        token_budget: int = 800,
        seed_k: int = 6,
        expand_depth: int = 1,
    ) -> RetrievedContext:
        if token_budget <= 0:
            return RetrievedContext()

        vectors = self.embedder.embed([query])
        if not vectors:
            return RetrievedContext()
        seeds = self.store.query_similar(vectors[0], k=seed_k)
        if not seeds:
            return RetrievedContext()

        seed_records = self.store.get_symbols([sid for sid, _ in seeds])
        if not seed_records:
            return RetrievedContext()

        # Expand by names through the call graph; resolve back to records.
        seen_ids: set[int] = {r.id for r in seed_records}
        ordered: list[SymbolRecord] = list(seed_records)

        if expand_depth > 0:
            expansion: list[str] = []
            for r in seed_records:
                expansion.extend(self.graph.neighbors(r.name, depth=expand_depth))
            seen_names: set[str] = set()
            for name in expansion:
                if name in seen_names:
                    continue
                seen_names.add(name)
                for record in self.store.get_symbols_by_name(name):
                    if record.id in seen_ids:
                        continue
                    seen_ids.add(record.id)
                    ordered.append(record)

        snippets: list[str] = []
        symbol_names: list[str] = []
        char_budget = token_budget * self.chars_per_token
        spent = 0
        for record in ordered:
            block = self._format_snippet(record)
            if spent + len(block) > char_budget and snippets:
                break
            snippets.append(block)
            symbol_names.append(record.name)
            spent += len(block)

        return RetrievedContext(
            snippets=snippets,
            symbols=symbol_names,
            estimated_tokens=spent // self.chars_per_token,
        )

    @staticmethod
    def _format_snippet(record: SymbolRecord) -> str:
        header = f"### {record.kind} `{record.name}` — {record.file}:{record.start_line}"
        body = record.body.strip() or f"(symbol {record.name})"
        return f"{header}\n```\n{body}\n```"

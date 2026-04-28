from __future__ import annotations

from dataclasses import dataclass

from teak.context.graph import KnowledgeGraph
from teak.context.storage import VectorStore


@dataclass
class RetrievedContext:
    """A bounded slice of project context to send to the LLM."""

    snippets: list[str]
    symbols: list[str]
    estimated_tokens: int


class SubgraphRAG:
    """Retrieve a minimal, relevant code subgraph for a query.

    1. Embed the query.
    2. Find seed symbols via vector search in `VectorStore`.
    3. Expand seeds through `KnowledgeGraph.neighbors` until token budget is hit.
    4. Return concrete source snippets + symbol identifiers.
    """

    def __init__(self, graph: KnowledgeGraph, store: VectorStore) -> None:
        self.graph = graph
        self.store = store

    def retrieve(self, query: str, token_budget: int) -> RetrievedContext:
        raise NotImplementedError(query, token_budget)

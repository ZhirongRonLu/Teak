from __future__ import annotations

import hashlib
import math
import os
from dataclasses import dataclass
from typing import Protocol


class Embedder(Protocol):
    """Embed a batch of texts into fixed-dimension vectors."""

    dim: int
    name: str

    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


@dataclass
class HashEmbedder:
    """Deterministic hash-based embedder.

    Quality is poor — comparable to bag-of-tokens — but it's offline, free, and
    deterministic, which makes it ideal for tests and for users without an
    embedding API key. Real LiteLLM-backed embeddings ship via LiteLLMEmbedder.
    """

    dim: int = 256
    name: str = "hash-256"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for token in self._tokenize(text):
            h = hashlib.sha1(token.encode("utf-8")).digest()
            idx = int.from_bytes(h[:4], "little") % self.dim
            sign = 1.0 if h[4] & 1 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        out: list[str] = []
        cur: list[str] = []
        for ch in text.lower():
            if ch.isalnum() or ch == "_":
                cur.append(ch)
            elif cur:
                out.append("".join(cur))
                cur = []
        if cur:
            out.append("".join(cur))
        return out


@dataclass
class LiteLLMEmbedder:
    """LiteLLM-backed embedder. Works with OpenAI, Voyage, Cohere, etc."""

    model: str = "text-embedding-3-small"
    dim: int = 1536
    name: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            self.name = self.model

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        import litellm

        response = litellm.embedding(model=self.model, input=texts)
        data = getattr(response, "data", None) or response["data"]
        out: list[list[float]] = []
        for item in data:
            if isinstance(item, dict):
                out.append(list(item["embedding"]))
            else:
                out.append(list(item.embedding))
        return out


def choose_embedder() -> Embedder:
    """Pick an embedder based on available providers.

    Priority:
      1. `TEAK_EMBEDDING_MODEL` (explicit override; e.g. "ollama/nomic-embed-text").
      2. Ollama (when `OLLAMA_HOST` is set OR a local daemon answers).
      3. OpenAI (`OPENAI_API_KEY`) → text-embedding-3-small.
      4. Voyage (`VOYAGE_API_KEY`) → voyage-3.
      5. HashEmbedder fallback so retrieval functions offline with no setup.
    """
    explicit = os.environ.get("TEAK_EMBEDDING_MODEL")
    if explicit:
        dim = int(os.environ.get("TEAK_EMBEDDING_DIM", "0")) or _guess_dim(explicit)
        return LiteLLMEmbedder(model=explicit, dim=dim, name=explicit)

    if os.environ.get("OLLAMA_HOST") or os.environ.get("TEAK_PREFER_OLLAMA"):
        return LiteLLMEmbedder(
            model="ollama/nomic-embed-text",
            dim=768,
            name="ollama/nomic-embed-text",
        )

    if os.environ.get("OPENAI_API_KEY"):
        return LiteLLMEmbedder(model="text-embedding-3-small", dim=1536)
    if os.environ.get("VOYAGE_API_KEY"):
        return LiteLLMEmbedder(model="voyage/voyage-3", dim=1024)
    return HashEmbedder()


def _guess_dim(model: str) -> int:
    """Reasonable default dim for common embedding models."""
    table = {
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
        "voyage-3": 1024,
        "nomic-embed-text": 768,
        "mxbai-embed-large": 1024,
        "bge-m3": 1024,
    }
    for key, dim in table.items():
        if key in model:
            return dim
    return 1536  # safe default; sqlite-vec table will recreate if mismatched

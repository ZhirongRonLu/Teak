from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from teak.llm.budget import BudgetTracker


@dataclass
class LLMResponse:
    text: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    cache_hit_tokens: int = 0


class LLMClient:
    """Thin wrapper over LiteLLM that enforces budgets and tracks cache hits.

    LiteLLM gives us provider routing for free (OpenAI, Anthropic, Grok, Ollama).
    We add:
      - Anthropic prompt-cache headers for the brain prefix
      - per-session cost accounting via `BudgetTracker`
      - automatic downshift to a cheaper model if `tracker.would_exceed(...)`
    """

    def __init__(self, default_model: str, tracker: Optional[BudgetTracker] = None) -> None:
        self.default_model = default_model
        self.tracker = tracker

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        model: Optional[str] = None,
        cache_prefix: bool = False,
    ) -> LLMResponse:
        raise NotImplementedError(messages, model, cache_prefix)

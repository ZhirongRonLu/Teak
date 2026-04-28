from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import litellm

from teak.llm.budget import BudgetTracker


@dataclass
class LLMResponse:
    text: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    cache_hit_tokens: int = 0


class LLMClient:
    """Thin wrapper over LiteLLM that tracks cost and (optionally) enforces a budget.

    Phase 0: tracks tokens + cost, no prompt caching, no auto-downshift.
    Phase 1+ will add Anthropic cache_control on the brain prefix.
    Phase 4+ will add hard budget enforcement and model routing.
    """

    def __init__(self, default_model: str, tracker: Optional[BudgetTracker] = None) -> None:
        self.default_model = default_model
        self.tracker = tracker

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        model: Optional[str] = None,
        json_mode: bool = False,
        cache_prefix: bool = False,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": messages,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        response = litellm.completion(**kwargs)
        text = response.choices[0].message.content or ""
        usage = response.usage
        tokens_in = getattr(usage, "prompt_tokens", 0) or 0
        tokens_out = getattr(usage, "completion_tokens", 0) or 0

        try:
            cost = float(litellm.completion_cost(completion_response=response) or 0.0)
        except Exception:
            cost = 0.0

        if self.tracker is not None:
            self.tracker.charge(cost)

        return LLMResponse(
            text=text,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
        )

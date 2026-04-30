from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import litellm
from rich.console import Console

from teak.llm.budget import BudgetExceeded, BudgetTracker
from teak.llm.cache import build_cached_messages
from teak.llm.routing import TaskKind, choose_model

_console = Console()


@dataclass
class LLMResponse:
    text: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    model: str = ""


class LLMClient:
    """LiteLLM wrapper that owns:

      - per-task model routing (cheap planner vs heavy default)
      - prompt caching on the brain prefix (Anthropic cache_control)
      - hard budget enforcement (pre-flight estimate + post-call charge)
      - optional auto-downshift when the budget is nearly exhausted
    """

    DOWNSHIFT_THRESHOLD: float = 0.95
    WARN_THRESHOLD: float = 0.80

    def __init__(
        self,
        default_model: str,
        planner_model: Optional[str] = None,
        tracker: Optional[BudgetTracker] = None,
    ) -> None:
        self.default_model = default_model
        self.planner_model = planner_model or default_model
        self.tracker = tracker

        # Cumulative metrics across all calls in this session.
        self.total_tokens_in = 0
        self.total_tokens_out = 0
        self.total_cost_usd = 0.0
        self.total_cache_read_tokens = 0
        self.total_cache_creation_tokens = 0

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        model: Optional[str] = None,
        json_mode: bool = False,
        kind: TaskKind = TaskKind.GENERATE_CODE,
    ) -> LLMResponse:
        """One-shot completion. `kind` drives routing; pass pre-built messages."""
        chosen = self._pick_model(model, kind)
        chosen = self._apply_downshift(chosen)
        self._maybe_warn()
        self._preflight(chosen, messages)

        kwargs: dict[str, Any] = {"model": chosen, "messages": messages}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        response = litellm.completion(**kwargs)
        return self._record(response, chosen)

    def complete_cached(
        self,
        *,
        cached_prefix: str,
        instructions: str,
        user_messages: list[dict[str, Any]],
        kind: TaskKind = TaskKind.GENERATE_CODE,
        json_mode: bool = False,
        model: Optional[str] = None,
    ) -> LLMResponse:
        """Convenience: build a cache-aware system block and call complete()."""
        messages = build_cached_messages(
            cached_prefix=cached_prefix,
            instructions=instructions,
            user_messages=user_messages,
        )
        return self.complete(messages, model=model, json_mode=json_mode, kind=kind)

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _pick_model(self, model_override: Optional[str], kind: TaskKind) -> str:
        if model_override:
            return model_override
        return choose_model(kind, default=self.default_model, planner=self.planner_model)

    def _apply_downshift(self, model: str) -> str:
        if self.tracker is None:
            return model
        if self.tracker.fraction_spent() >= self.DOWNSHIFT_THRESHOLD and model != self.planner_model:
            _console.print(
                f"[yellow]budget at {self.tracker.fraction_spent():.0%} — "
                f"downshifting to {self.planner_model}[/yellow]"
            )
            return self.planner_model
        return model

    def _maybe_warn(self) -> None:
        if self.tracker is None:
            return
        if (
            not self.tracker.warned
            and self.tracker.fraction_spent() >= self.WARN_THRESHOLD
        ):
            _console.print(
                f"[yellow]heads up: ${self.tracker.spent_usd:.4f} of "
                f"${self.tracker.budget_usd:.4f} spent ({self.tracker.fraction_spent():.0%})[/yellow]"
            )
            self.tracker.warned = True

    def _preflight(self, model: str, messages: list[dict[str, Any]]) -> None:
        if self.tracker is None:
            return
        try:
            tokens_in = int(litellm.token_counter(model=model, messages=messages))
        except Exception:
            tokens_in = sum(_rough_token_count(m) for m in messages)
        # Assume an upper bound on completion tokens proportional to input
        # for planning/summarization; for code generation we let it be larger.
        tokens_out = max(256, min(1024, tokens_in // 2))
        estimate = _estimate_cost(model, tokens_in, tokens_out)
        if self.tracker.would_exceed(estimate):
            raise BudgetExceeded(
                f"pre-flight estimate ${estimate:.4f} would exceed budget "
                f"(spent ${self.tracker.spent_usd:.4f} of ${self.tracker.budget_usd:.4f})"
            )

    def _record(self, response: Any, model: str) -> LLMResponse:
        text = response.choices[0].message.content or ""
        usage = response.usage
        tokens_in = int(getattr(usage, "prompt_tokens", 0) or 0)
        tokens_out = int(getattr(usage, "completion_tokens", 0) or 0)
        cache_read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        cache_creation = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)

        try:
            cost = float(litellm.completion_cost(completion_response=response) or 0.0)
        except Exception:
            cost = 0.0

        if self.tracker is not None:
            try:
                self.tracker.charge(cost)
            except BudgetExceeded:
                # Already spent — record but don't block this finished call.
                self.tracker.spent_usd += cost
                raise

        self.total_tokens_in += tokens_in
        self.total_tokens_out += tokens_out
        self.total_cost_usd += cost
        self.total_cache_read_tokens += cache_read
        self.total_cache_creation_tokens += cache_creation

        return LLMResponse(
            text=text,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
            cache_read_tokens=cache_read,
            cache_creation_tokens=cache_creation,
            model=model,
        )


def _estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    try:
        in_cost, out_cost = litellm.cost_per_token(
            model=model, prompt_tokens=tokens_in, completion_tokens=tokens_out
        )
        return float(in_cost) + float(out_cost)
    except Exception:
        return 0.0


def _rough_token_count(msg: dict[str, Any]) -> int:
    content = msg.get("content")
    if isinstance(content, str):
        return max(1, len(content) // 4)
    if isinstance(content, list):
        total = 0
        for block in content:
            text = block.get("text", "") if isinstance(block, dict) else ""
            total += max(1, len(text) // 4)
        return total
    return 1

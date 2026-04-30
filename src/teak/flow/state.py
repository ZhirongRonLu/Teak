from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Mode(str, Enum):
    QUICK = "quick"
    PLAN = "plan"
    AGENTIC = "agentic"


@dataclass
class PlanStep:
    title: str
    rationale: str
    target_files: list[str] = field(default_factory=list)
    approved: Optional[bool] = None


@dataclass
class SessionState:
    """Shared state passed between LangGraph nodes.

    LangGraph will serialize this between steps; keep fields JSON-friendly.
    """

    task: str
    mode: Mode = Mode.PLAN
    branch: str = ""
    plan: list[PlanStep] = field(default_factory=list)
    current_step: int = 0
    diffs: list[str] = field(default_factory=list)
    test_failures: list[str] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    budget_usd: Optional[float] = None
    handoff_summary: str = ""
    previous_handoff: str = ""

    # Per-step bookkeeping (Phase 3)
    step_attempts: dict[int, int] = field(default_factory=dict)
    last_failure: str = ""
    last_commit_sha: str = ""
    verifier_command: Optional[str] = None
    max_step_retries: int = 2
    auto: bool = False  # auto-approve plan + every step (used by `teak bench`)

    @property
    def over_budget(self) -> bool:
        return self.budget_usd is not None and self.cost_usd >= self.budget_usd

    @property
    def steps_remaining(self) -> bool:
        return self.current_step < len(self.plan)

    def current(self) -> Optional[PlanStep]:
        if not self.steps_remaining:
            return None
        return self.plan[self.current_step]

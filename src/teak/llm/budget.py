from __future__ import annotations

from dataclasses import dataclass


class BudgetExceeded(RuntimeError):
    """Raised when a session would exceed its hard token budget."""


@dataclass
class BudgetTracker:
    """Hard per-session USD budget. Not advisory — blocks calls that would breach it."""

    budget_usd: float
    spent_usd: float = 0.0
    warned: bool = False

    def remaining(self) -> float:
        return max(0.0, self.budget_usd - self.spent_usd)

    def fraction_spent(self) -> float:
        if self.budget_usd <= 0:
            return 1.0
        return min(1.0, self.spent_usd / self.budget_usd)

    def would_exceed(self, estimated_cost: float) -> bool:
        return self.spent_usd + estimated_cost > self.budget_usd

    def charge(self, cost_usd: float) -> None:
        if self.would_exceed(cost_usd):
            raise BudgetExceeded(
                f"would exceed budget: spent ${self.spent_usd:.4f} of ${self.budget_usd:.4f}, "
                f"call cost ${cost_usd:.4f}"
            )
        self.spent_usd += cost_usd

    def pre_check(self, estimated_cost: float) -> None:
        """Fail before a call we know we can't afford."""
        if self.would_exceed(estimated_cost):
            raise BudgetExceeded(
                f"pre-flight estimate ${estimated_cost:.4f} would exceed budget "
                f"(remaining ${self.remaining():.4f})"
            )

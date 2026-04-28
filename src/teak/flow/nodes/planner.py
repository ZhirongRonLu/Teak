from __future__ import annotations

from teak.flow.state import PlanStep, SessionState


def run(state: SessionState) -> SessionState:
    """Read brain (cached) + retrieve subgraph + emit a structured plan.

    The plan is a list of `PlanStep`s, each describing one logical change.
    """
    raise NotImplementedError(state, PlanStep)

from __future__ import annotations

from teak.flow.state import Mode, SessionState


def run(state: SessionState) -> SessionState:
    """Classify the task: trivial → QuickMode, otherwise PlanMode.

    A cheap model is enough here; this gate exists to skip the full plan/approve
    loop for one-line edits and pure questions.
    """
    raise NotImplementedError(state, Mode)

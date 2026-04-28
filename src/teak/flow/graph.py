from __future__ import annotations

from typing import Optional

from teak.config import TeakConfig
from teak.flow.nodes import (
    brain_updater,
    executor,
    human_approval,
    planner,
    router,
    verifier,
)
from teak.flow.state import Mode, SessionState


def build_graph():
    """Construct the LangGraph state machine.

    Wiring (from README §5):

        Router
          ├─ QuickMode  ──────────────────────────────────────────► END
          └─ PlanMode
                Planner → HumanApproval ⟲ (edit/approve/reject)
                              ↓
                          Executor (one change → git commit)
                              ↓
                          Verifier (tests → loop back to Executor on fail)
                              ↓
                          BrainUpdater (propose updates → human approval) → END
    """
    raise NotImplementedError(
        router.run,
        planner.run,
        human_approval.run,
        executor.run,
        verifier.run,
        brain_updater.run,
    )


def run_session(
    config: TeakConfig,
    task: Optional[str] = None,
    budget_usd: Optional[float] = None,
    model: Optional[str] = None,
) -> SessionState:
    """Compile the graph and run a single session to completion."""
    initial = SessionState(
        task=task or "",
        mode=Mode.QUICK if not task else Mode.PLAN,
        budget_usd=budget_usd,
    )
    raise NotImplementedError(config, initial, model)

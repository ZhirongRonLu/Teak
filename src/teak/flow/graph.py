from __future__ import annotations

from typing import Optional

from langgraph.graph import END, START, StateGraph

from teak.brain.manager import BrainManager
from teak.config import TeakConfig
from teak.flow.nodes import brain_updater as brain_updater_node
from teak.flow.nodes import executor as executor_node
from teak.flow.nodes import human_approval as approval_node
from teak.flow.nodes import planner as planner_node
from teak.flow.state import Mode, SessionState
from teak.llm.budget import BudgetTracker
from teak.llm.client import LLMClient
from teak.vcs.repo import SessionRepo


def _route_after_approval(state: SessionState) -> str:
    return "executor" if state.plan else END


def _route_after_executor(state: SessionState, *, brain_active: bool) -> str:
    if brain_active and state.diffs:
        return "brain_updater"
    return END


def build_graph(
    client: LLMClient,
    repo: SessionRepo,
    config: TeakConfig,
    brain: Optional[BrainManager] = None,
):
    """Phase 1 graph:

        START → planner → approval → (plan empty → END | else → executor)
                                              ↓
                                    (brain present → brain_updater → END | else → END)

    Router and Verifier nodes land in later phases.
    """
    builder = StateGraph(SessionState)
    builder.add_node("planner", planner_node.make_node(client, brain=brain))
    builder.add_node("approval", approval_node.make_node())
    builder.add_node(
        "executor",
        executor_node.make_node(client, repo, config.project_root, brain=brain),
    )

    brain_active = brain is not None and brain.exists()
    if brain_active:
        builder.add_node(
            "brain_updater", brain_updater_node.make_node(client, brain, repo)
        )

    builder.add_edge(START, "planner")
    builder.add_edge("planner", "approval")
    builder.add_conditional_edges(
        "approval", _route_after_approval, {"executor": "executor", END: END}
    )
    if brain_active:
        builder.add_conditional_edges(
            "executor",
            lambda s: _route_after_executor(s, brain_active=True),
            {"brain_updater": "brain_updater", END: END},
        )
        builder.add_edge("brain_updater", END)
    else:
        builder.add_edge("executor", END)

    return builder.compile()


def run_session(
    config: TeakConfig,
    task: Optional[str] = None,
    budget_usd: Optional[float] = None,
    model: Optional[str] = None,
) -> SessionState:
    if not task:
        raise ValueError("Phase 0 requires a task; QuickMode lands in a later phase")

    tracker = BudgetTracker(budget_usd=budget_usd) if budget_usd is not None else None
    client = LLMClient(default_model=model or config.default_model, tracker=tracker)
    repo = SessionRepo(project_root=config.project_root)
    brain = BrainManager(config)

    branch = repo.start_session_branch()
    initial = SessionState(
        task=task,
        mode=Mode.PLAN,
        branch=branch,
        budget_usd=budget_usd,
    )

    graph = build_graph(client, repo, config, brain=brain)
    final = graph.invoke(initial)

    if isinstance(final, SessionState):
        return final
    return SessionState(**{k: v for k, v in final.items() if k in SessionState.__dataclass_fields__})

from __future__ import annotations

from typing import Optional

from langgraph.graph import END, START, StateGraph
from rich.console import Console

from teak.brain.manager import BrainManager
from teak.config import TeakConfig
from teak.context.embedder import choose_embedder
from teak.context.indexer import Indexer
from teak.context.rag import SubgraphRAG
from teak.context.storage import VectorStore
from teak.flow.nodes import brain_updater as brain_updater_node
from teak.flow.nodes import convention_check as convention_check_node
from teak.flow.nodes import executor as executor_node
from teak.flow.nodes import handoff as handoff_node
from teak.flow.nodes import human_approval as approval_node
from teak.flow.nodes import planner as planner_node
from teak.flow.nodes import step_review as step_review_node
from teak.flow.nodes import verifier as verifier_node
from teak.flow.state import Mode, SessionState
from teak.llm.budget import BudgetTracker
from teak.llm.client import LLMClient
from teak.session.handoff import load_last_handoff
from teak.vcs.repo import SessionRepo

_console = Console()


# ---- routing helpers --------------------------------------------------------


def _route_after_plan_approval(state: SessionState) -> str:
    return "step_runner" if state.plan else END


def _route_after_step_runner(state: SessionState) -> str:
    return "step_review"


def _route_after_step_review(state: SessionState) -> str:
    # last_commit_sha set ⇒ change was kept and needs verification.
    if state.last_commit_sha:
        return "verifier"
    return "step_runner" if state.steps_remaining else "brain_updater"


def _route_after_verifier(state: SessionState) -> str:
    # If a retry is in flight (commit was reset, failure recorded), the executor
    # runs again on the same step.
    if not state.last_commit_sha and state.last_failure:
        return "step_runner"
    return "step_runner" if state.steps_remaining else "brain_updater"


# ---- build ------------------------------------------------------------------


def build_graph(
    client: LLMClient,
    repo: SessionRepo,
    config: TeakConfig,
    brain: Optional[BrainManager] = None,
    rag: Optional[SubgraphRAG] = None,
):
    """Phase 3 graph (per-step loop):

        START
          → planner
          → plan_approval
              ├─ empty plan → END
              └─ plan present
                  → step_runner ⇄ step_review (reject = git reset)
                                ⇄ verifier (fail-retry loop)
                                → next step | brain_updater
          → handoff
          → END
    """
    builder = StateGraph(SessionState)

    builder.add_node("planner", planner_node.make_node(client, brain=brain, rag=rag))
    if brain is not None:
        builder.add_node(
            "convention_check", convention_check_node.make_node(client, brain)
        )
    builder.add_node("plan_approval", approval_node.make_node())
    builder.add_node(
        "step_runner",
        executor_node.make_node(
            client, repo, config.project_root, brain=brain, rag=rag
        ),
    )
    builder.add_node("step_review", step_review_node.make_node(repo))
    builder.add_node("verifier", verifier_node.make_node(repo, config.project_root))
    builder.add_node(
        "brain_updater",
        brain_updater_node.make_node(client, brain, repo) if brain is not None else _noop_node(),
    )
    builder.add_node(
        "handoff",
        handoff_node.make_node(client, config, repo, brain=brain),
    )

    builder.add_edge(START, "planner")
    if brain is not None:
        builder.add_edge("planner", "convention_check")
        builder.add_edge("convention_check", "plan_approval")
    else:
        builder.add_edge("planner", "plan_approval")
    builder.add_conditional_edges(
        "plan_approval",
        _route_after_plan_approval,
        {"step_runner": "step_runner", END: END},
    )
    builder.add_conditional_edges(
        "step_runner", _route_after_step_runner, {"step_review": "step_review"}
    )
    builder.add_conditional_edges(
        "step_review",
        _route_after_step_review,
        {
            "verifier": "verifier",
            "step_runner": "step_runner",
            "brain_updater": "brain_updater",
        },
    )
    builder.add_conditional_edges(
        "verifier",
        _route_after_verifier,
        {
            "step_runner": "step_runner",
            "brain_updater": "brain_updater",
        },
    )
    builder.add_edge("brain_updater", "handoff")
    builder.add_edge("handoff", END)

    return builder.compile()


def _noop_node():
    def run(state: SessionState) -> dict:  # noqa: ARG001
        return {}

    return run


def _make_rag(config: TeakConfig) -> Optional[SubgraphRAG]:
    """Bootstrap (or refresh) the index and return a ready-to-use RAG."""
    try:
        embedder = choose_embedder()
        store = VectorStore(config.db_path)
        indexer = Indexer(config, store, embedder=embedder)
        report = indexer.bootstrap()
        if (report["indexed"] + report["skipped"]) == 0:
            return None
        if report["indexed"]:
            _console.print(
                f"[dim]indexed {report['indexed']} file(s), "
                f"skipped {report['skipped']}, removed {report['removed']}[/dim]"
            )
        return SubgraphRAG(store, embedder)
    except Exception as e:
        _console.print(f"[yellow]context index unavailable: {e}[/yellow]")
        return None


def run_session(
    config: TeakConfig,
    task: Optional[str] = None,
    budget_usd: Optional[float] = None,
    model: Optional[str] = None,
    planner_model: Optional[str] = None,
    use_context: bool = True,
    verifier_command: Optional[str] = None,
    max_step_retries: int = 2,
    auto: bool = False,
) -> SessionState:
    if not task:
        raise ValueError("Phase 0 requires a task; QuickMode lands in a later phase")

    tracker = BudgetTracker(budget_usd=budget_usd) if budget_usd is not None else None
    client = LLMClient(
        default_model=model or config.default_model,
        planner_model=planner_model or config.planner_model,
        tracker=tracker,
    )
    repo = SessionRepo(project_root=config.project_root)
    brain = BrainManager(config)
    rag = _make_rag(config) if use_context else None

    previous = load_last_handoff(config)
    if previous is not None:
        _console.print(
            f"[dim]Continuing from handoff {previous.created_at} on {previous.branch}[/dim]"
        )

    branch = repo.start_session_branch()
    initial = SessionState(
        task=task,
        mode=Mode.PLAN,
        branch=branch,
        budget_usd=budget_usd,
        verifier_command=verifier_command,
        max_step_retries=max_step_retries,
        previous_handoff=previous.to_prompt() if previous else "",
        auto=auto,
    )

    graph = build_graph(client, repo, config, brain=brain, rag=rag)
    final = graph.invoke(initial)

    if isinstance(final, SessionState):
        result = final
    else:
        result = SessionState(
            **{k: v for k, v in final.items() if k in SessionState.__dataclass_fields__}
        )

    # Pull cumulative cache stats off the client so the dashboard sees them.
    result.cache_read_tokens = client.total_cache_read_tokens
    result.cache_creation_tokens = client.total_cache_creation_tokens
    return result

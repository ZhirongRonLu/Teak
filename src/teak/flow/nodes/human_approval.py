from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from teak.flow.state import PlanStep, SessionState

_console = Console()


def _render_plan(plan: list[PlanStep]) -> None:
    if not plan:
        _console.print("[yellow]Planner produced no steps.[/yellow]")
        return
    for i, step in enumerate(plan, 1):
        body = f"[bold]{step.title}[/bold]\n{step.rationale}"
        if step.target_files:
            body += "\n\n[dim]files:[/dim] " + ", ".join(step.target_files)
        _console.print(Panel(body, title=f"Step {i}/{len(plan)}", border_style="cyan"))


def make_node():
    """Phase 0: inline rich prompt. Will swap to LangGraph interrupt() once the
    textual TUI lands so the approval can resume from a paused checkpoint."""

    def run(state: SessionState) -> dict:
        _render_plan(state.plan)
        if not state.plan:
            return {"plan": []}

        choice = Prompt.ask(
            "[bold]Approve plan?[/bold]",
            choices=["a", "r"],
            default="a",
            show_choices=True,
        )
        if choice == "r":
            return {"plan": []}

        approved = [
            PlanStep(
                title=s.title,
                rationale=s.rationale,
                target_files=list(s.target_files),
                approved=True,
            )
            for s in state.plan
        ]
        return {"plan": approved}

    return run

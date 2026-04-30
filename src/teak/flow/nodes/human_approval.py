from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from teak.flow.nodes.planner import parse_plan
from teak.flow.state import PlanStep, SessionState

_console = Console()


def _render_plan(plan: list[PlanStep]) -> None:
    if not plan:
        _console.print("[yellow]No steps in plan.[/yellow]")
        return
    for i, step in enumerate(plan, 1):
        body = f"[bold]{step.title}[/bold]\n{step.rationale}"
        if step.target_files:
            body += "\n\n[dim]files:[/dim] " + ", ".join(step.target_files)
        _console.print(Panel(body, title=f"Step {i}/{len(plan)}", border_style="cyan"))


def _render_violations(violations: list[str]) -> None:
    if not violations:
        return
    body = "\n".join(f"• {v}" for v in violations)
    _console.print(
        Panel(body, title="convention check", border_style="red")
    )


def _plan_to_json(plan: list[PlanStep]) -> str:
    payload = {
        "steps": [
            {
                "title": s.title,
                "rationale": s.rationale,
                "target_files": list(s.target_files),
            }
            for s in plan
        ]
    }
    return json.dumps(payload, indent=2) + "\n"


def _edit_plan(plan: list[PlanStep]) -> list[PlanStep]:
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
    _console.print(
        "[dim]Opening plan in editor. Save and close to continue. "
        "Set [italic]\"steps\"[/italic] to [] to reject.[/dim]"
    )
    with tempfile.NamedTemporaryFile(
        mode="w+", suffix=".teak-plan.json", delete=False, encoding="utf-8"
    ) as tf:
        tf.write(_plan_to_json(plan))
        path = Path(tf.name)
    try:
        while True:
            subprocess.run([editor, str(path)], check=False)
            text = path.read_text(encoding="utf-8")
            try:
                steps, _notes = parse_plan(text)
                return steps
            except (ValueError, json.JSONDecodeError) as e:
                _console.print(f"[red]Invalid plan: {e}[/red]")
                if Prompt.ask("Re-open editor?", choices=["y", "n"], default="y") == "n":
                    return plan
    finally:
        path.unlink(missing_ok=True)


def make_node():
    """Phase 0: rich prompt + $EDITOR for edits. Will swap to LangGraph
    interrupt() once the textual TUI lands so approval can resume from a
    paused checkpoint."""

    def run(state: SessionState) -> dict:
        plan = list(state.plan)
        if state.auto:
            return {
                "plan": [
                    PlanStep(
                        title=s.title,
                        rationale=s.rationale,
                        target_files=list(s.target_files),
                        approved=True,
                    )
                    for s in plan
                ],
                "test_failures": [],
            }
        while True:
            _render_plan(plan)
            if not plan:
                return {"plan": []}
            _render_violations(state.test_failures)

            choice = Prompt.ask(
                r"[bold]Approve plan?[/bold] \[a]pprove / \[e]dit / \[r]eject",
                choices=["a", "e", "r"],
                default="a",
                show_choices=False,
            )
            if choice == "r":
                return {"plan": []}
            if choice == "e":
                plan = _edit_plan(plan)
                continue

            return {
                "plan": [
                    PlanStep(
                        title=s.title,
                        rationale=s.rationale,
                        target_files=list(s.target_files),
                        approved=True,
                    )
                    for s in plan
                ]
            }

    return run

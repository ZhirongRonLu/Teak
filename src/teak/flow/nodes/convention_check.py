from __future__ import annotations

from rich.console import Console
from rich.panel import Panel

from teak.brain.manager import BrainManager, ConventionViolation
from teak.flow.state import SessionState
from teak.llm.client import LLMClient

_console = Console()


def make_node(client: LLMClient, brain: BrainManager):
    """Run after the planner; before plan_approval.

    Skipped when the brain isn't initialized. Violations land on
    `state.test_failures` so the approval node can render them — that field
    already exists and is short-lived per session.
    """

    def run(state: SessionState) -> dict:
        if not brain.exists() or not state.plan:
            return {}

        descriptions = [
            f"{step.title}: {step.rationale} (files: {', '.join(step.target_files)})"
            for step in state.plan
        ]
        try:
            violations = brain.detect_violations(descriptions, client)
        except Exception as e:
            _console.print(f"[yellow]convention check skipped: {e}[/yellow]")
            return {}

        if not violations:
            return {}

        _render_violations(violations, len(state.plan))
        return {
            "test_failures": [
                _format_violation(v) for v in violations
            ]
        }

    return run


def _format_violation(v: ConventionViolation) -> str:
    prefix = f"step {v.step_index + 1}" if v.step_index >= 0 else "plan"
    return f"{prefix}: {v.rule} — {v.detail}"


def _render_violations(violations: list[ConventionViolation], n_steps: int) -> None:
    lines: list[str] = []
    for v in violations:
        if 0 <= v.step_index < n_steps:
            head = f"step {v.step_index + 1}"
        else:
            head = "plan"
        lines.append(f"[bold red]{head}[/bold red] · {v.rule}")
        if v.detail:
            lines.append(f"  {v.detail}")
    _console.print(
        Panel(
            "\n".join(lines),
            title="convention violations",
            border_style="red",
        )
    )

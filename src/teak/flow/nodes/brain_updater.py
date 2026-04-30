from __future__ import annotations

import difflib

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from teak.brain.manager import BrainManager
from teak.flow.state import SessionState
from teak.llm.client import LLMClient
from teak.vcs.repo import SessionRepo

_console = Console()


def _render_diff(name: str, before: str, after: str) -> None:
    if before == after:
        return
    diff = "\n".join(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=f"a/{name}",
            tofile=f"b/{name}",
            lineterm="",
        )
    )
    _console.print(Panel(diff or "(no textual diff)", title=name, border_style="magenta"))


def make_node(client: LLMClient, brain: BrainManager, repo: SessionRepo):
    """After execution, propose minimal brain updates and route through approval."""

    def run(state: SessionState) -> dict:
        if not brain.exists():
            return {}
        if not state.diffs:
            return {}

        diff_summary = repo.diff_summary() or "(no diff available)"

        try:
            updates = brain.propose_updates(diff_summary, client)
        except Exception as e:
            _console.print(f"[yellow]brain updater skipped: {e}[/yellow]")
            return {}

        if not updates:
            _console.print("[dim]No brain updates proposed.[/dim]")
            return {}

        approved: dict[str, str] = {}
        current = brain.read_all()
        for name, new_content in updates.items():
            old = current.get(name, "")
            if old == new_content:
                continue
            if state.auto:
                approved[name] = new_content
                continue
            _render_diff(name, old, new_content)
            choice = Prompt.ask(
                f"Apply update to [bold]{name}[/bold]?",
                choices=["y", "n"],
                default="y",
            )
            if choice == "y":
                approved[name] = new_content

        if approved:
            brain.apply_updates(approved)
            sha = repo.commit_step("teak: update project brain")
            if sha:
                _console.print(f"[green]brain updated in {sha[:8]}[/green]")
            else:
                _console.print("[green]brain updated[/green]")

        return {}

    return run

from __future__ import annotations

from typing import Optional

from rich.console import Console

from teak.brain.manager import BrainManager
from teak.config import TeakConfig
from teak.flow.state import SessionState
from teak.llm.client import LLMClient
from teak.session.handoff import Handoff, generate_handoff
from teak.vcs.repo import SessionRepo

_console = Console()


def make_node(
    client: LLMClient,
    config: TeakConfig,
    repo: SessionRepo,
    brain: Optional[BrainManager] = None,
):
    """Generate + persist a handoff at the end of the session.

    Skipped when no commits were produced — there's nothing to hand off.
    """

    def run(state: SessionState) -> dict:
        if not state.diffs:
            return {}

        diff_summary = ""
        try:
            diff_summary = repo.diff_summary()
        except Exception:
            pass

        try:
            handoff: Handoff = generate_handoff(
                state, config, client=client, diff_summary=diff_summary, brain=brain
            )
        except Exception as e:
            _console.print(f"[yellow]handoff skipped: {e}[/yellow]")
            return {}

        _console.print(
            f"\n[bold]Session handoff[/bold] [dim]({handoff.created_at})[/dim]"
        )
        _console.print(handoff.summary)
        if handoff.pending:
            _console.print(
                "[bold]Pending:[/bold] " + "; ".join(handoff.pending)
            )
        if handoff.decisions:
            _console.print(
                "[bold]Decisions:[/bold] " + "; ".join(handoff.decisions)
            )

        return {"handoff_summary": handoff.summary}

    return run

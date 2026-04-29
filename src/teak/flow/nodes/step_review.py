from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.syntax import Syntax

from teak.flow.state import SessionState
from teak.vcs.repo import SessionRepo

_console = Console()


def _show_last_commit_diff(repo: SessionRepo, sha: str) -> None:
    try:
        stat = repo.repo.git.show(sha, "--stat", "--format=")
        patch = repo.repo.git.show(sha, "--format=")
    except Exception as e:
        _console.print(f"[yellow]could not render diff: {e}[/yellow]")
        return
    if stat.strip():
        _console.print(Panel(stat.strip(), title=f"{sha[:8]} stat", border_style="cyan"))
    if patch.strip():
        if len(patch) > 4000:
            patch = patch[:4000] + "\n…(truncated)"
        _console.print(Syntax(patch, "diff", word_wrap=True, line_numbers=False))


def make_node(repo: SessionRepo):
    """After a commit, render the diff and gate on user approval.

    Approve → continue (verifier or next step).
    Reject  → `git reset --hard HEAD~1` and drop the sha; advance to next step.
    """

    def run(state: SessionState) -> dict:
        sha = state.last_commit_sha
        if not sha:
            # Executor didn't commit this step — nothing to review.
            return {"current_step": state.current_step + 1, "last_commit_sha": ""}

        _show_last_commit_diff(repo, sha)
        choice = Prompt.ask(
            r"[bold]Accept this change?[/bold] \[a]ccept / \[r]eject",
            choices=["a", "r"],
            default="a",
            show_choices=False,
        )

        if choice == "r":
            try:
                repo.reset_last()
            except Exception as e:
                _console.print(f"[red]reset failed: {e}[/red]")
            new_diffs = [s for s in state.diffs if s != sha]
            _console.print("[yellow]  rejected — reverted last commit[/yellow]")
            return {
                "diffs": new_diffs,
                "current_step": state.current_step + 1,
                "last_failure": "",
                "last_commit_sha": "",
            }

        return {"last_commit_sha": sha}

    return run

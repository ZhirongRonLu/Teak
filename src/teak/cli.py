from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from teak import __version__
from teak.brain.bootstrapper import bootstrap_brain
from teak.brain.manager import BRAIN_FILES, BrainManager
from teak.brain.templates import list_templates
from teak.config import TeakConfig, load_config
from teak.flow.graph import run_session
from teak.session.handoff import generate_handoff, load_last_handoff
from teak.vcs.repo import DirtyWorkingTree

app = typer.Typer(
    name="teak",
    help="Teak — AI coding companion with a persistent Project Brain.",
    no_args_is_help=True,
)
console = Console()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"teak {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True
    ),
) -> None:
    """Root callback — global flags live here."""


@app.command()
def init(
    path: Path = typer.Argument(Path.cwd(), help="Project root."),
    template: Optional[str] = typer.Option(
        None,
        "--template",
        help="Brain template to seed from (skip the LLM survey).",
    ),
    list_templates_flag: bool = typer.Option(
        False,
        "--list-templates",
        help="List available built-in brain templates and exit.",
    ),
) -> None:
    """Bootstrap `.teak/brain/` for this project."""
    if list_templates_flag:
        for tpl in list_templates():
            console.print(f"[bold]{tpl.name}[/bold] — {tpl.description}")
        raise typer.Exit()

    project_root = path.resolve()
    if not project_root.is_dir():
        console.print(f"[red]not a directory: {project_root}[/red]")
        raise typer.Exit(code=1)

    existing = TeakConfig.for_project(project_root)
    if existing.brain_dir.is_dir() and any(existing.brain_dir.iterdir()):
        console.print(
            f"[yellow]brain already exists at {existing.brain_dir}; "
            "delete it or edit it with `teak brain --edit`[/yellow]"
        )
        raise typer.Exit(code=1)

    if template:
        console.print(f"Installing brain template [bold]{template}[/bold]…")
    else:
        console.print("Surveying codebase and drafting brain (≈30s)…")

    try:
        manager = bootstrap_brain(project_root, template=template)
    except KeyError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)
    except Exception as e:
        console.print(f"[red]bootstrap failed: {e}[/red]")
        raise typer.Exit(code=1)

    console.print(
        f"[green]Brain initialized at[/green] [bold]{manager.config.brain_dir}[/bold]"
    )
    for line in manager.summary_lines():
        console.print(f"  • {line}")
    console.print(
        "\nReview drafts with [dim]teak brain[/dim] — edit with [dim]teak brain --edit[/dim]."
    )


@app.command()
def chat(
    budget: Optional[float] = typer.Option(None, help="Per-session token budget in USD."),
    model: Optional[str] = typer.Option(None, help="Override LLM model id."),
) -> None:
    """Start an interactive Teak session (QuickMode — not in Phase 0)."""
    config = load_config()
    raise NotImplementedError(run_session, config, budget, model)


@app.command()
def plan(
    task: str = typer.Argument(..., help="What you want Teak to do."),
    budget: Optional[float] = typer.Option(None, help="Per-session token budget in USD."),
    model: Optional[str] = typer.Option(None, help="Override LLM model id."),
) -> None:
    """Generate, approve, and execute a plan for `task`."""
    config = load_config()
    try:
        state = run_session(config, task=task, budget_usd=budget, model=model)
    except DirtyWorkingTree as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    console.print(f"\n[green]Session complete on branch [bold]{state.branch}[/bold][/green]")
    console.print(
        f"Spent ${state.cost_usd:.4f} "
        f"({state.tokens_in} in / {state.tokens_out} out, "
        f"{len(state.diffs)} commits)"
    )
    if state.diffs:
        console.print(
            "\nReview with: [dim]git log "
            f"{state.branch}[/dim]\n"
            "Merge with:  [dim]git checkout <your-branch> && git merge "
            f"{state.branch}[/dim]"
        )


@app.command()
def brain(
    edit: bool = typer.Option(False, "--edit", help="Open brain files in $EDITOR."),
) -> None:
    """View or edit the Project Brain."""
    manager = BrainManager.for_cwd()
    if not manager.exists():
        console.print(
            "[yellow]No brain found.[/yellow] Run [dim]teak init[/dim] to create one."
        )
        raise typer.Exit(code=1)

    if edit:
        editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
        paths = [str(manager.files[name].path) for name in BRAIN_FILES]
        subprocess.run([editor, *paths], check=False)
        return

    for name in BRAIN_FILES:
        body = manager.files[name].read().strip() or "_(empty)_"
        console.print(Panel(Markdown(body), title=name, border_style="cyan"))


@app.command()
def session() -> None:
    """Show the last session handoff summary."""
    raise NotImplementedError(load_last_handoff, generate_handoff)


@app.command()
def status() -> None:
    """Show token usage, budget, and brain health."""
    config: TeakConfig = load_config()
    raise NotImplementedError(config)


if __name__ == "__main__":
    app()

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
from teak.context.embedder import choose_embedder
from teak.context.indexer import Indexer
from teak.context.storage import VectorStore
from teak.flow.graph import run_session
from teak.session.handoff import load_last_handoff
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
    no_context: bool = typer.Option(
        False,
        "--no-context",
        help="Skip subgraph RAG retrieval (faster start, no project context).",
    ),
    verify: Optional[str] = typer.Option(
        None,
        "--verify",
        help='Command to run after each accepted step (e.g. "pytest -q").',
    ),
    auto_verify: bool = typer.Option(
        False,
        "--auto-verify",
        help="Detect a default verifier command for the project (pytest / npm test / cargo test).",
    ),
    max_retries: int = typer.Option(
        2, "--max-retries", help="Verifier retries per step before prompting."
    ),
) -> None:
    """Generate, approve, and execute a plan for `task`."""
    config = load_config()

    verifier_command = verify
    if verifier_command is None and auto_verify:
        from teak.flow.nodes.verifier import detect_default_command
        verifier_command = detect_default_command(config.project_root) or None
        if verifier_command:
            console.print(f"[dim]auto-verify: {verifier_command}[/dim]")
        else:
            console.print("[yellow]auto-verify: no test runner detected[/yellow]")

    try:
        state = run_session(
            config,
            task=task,
            budget_usd=budget,
            model=model,
            use_context=not no_context,
            verifier_command=verifier_command,
            max_step_retries=max_retries,
        )
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
def index(
    force: bool = typer.Option(
        False, "--force", help="Re-embed every file regardless of hash."
    ),
) -> None:
    """Bootstrap (or refresh) the Tree-sitter + sqlite-vec context index."""
    config = load_config()
    embedder = choose_embedder()
    store = VectorStore(config.db_path)
    indexer = Indexer(config, store, embedder=embedder)
    if force:
        # Cheapest "re-embed everything" is to drop file rows so hashes mismatch.
        with store.connect() as conn:
            conn.execute("DELETE FROM files")
    console.print(f"Indexing with embedder [bold]{embedder.name}[/bold] (dim {embedder.dim})…")
    report = indexer.bootstrap()
    stats = store.stats()
    console.print(
        f"[green]indexed {report['indexed']}, skipped {report['skipped']}, "
        f"removed {report['removed']}[/green]"
    )
    console.print(
        f"  files: {stats['files']}  symbols: {stats['symbols']}  "
        f"calls: {stats['calls']}  imports: {stats['imports']}"
    )


@app.command()
def session() -> None:
    """Show the last session handoff summary."""
    config = load_config()
    handoff = load_last_handoff(config)
    if handoff is None:
        console.print(
            "[yellow]No handoff yet.[/yellow] Run [dim]teak plan[/dim] to start one."
        )
        raise typer.Exit(code=1)
    console.print(
        Panel(
            handoff.summary,
            title=f"{handoff.created_at} — {handoff.branch}",
            border_style="cyan",
        )
    )
    if handoff.pending:
        console.print("[bold]Pending:[/bold]")
        for item in handoff.pending:
            console.print(f"  • {item}")
    if handoff.decisions:
        console.print("[bold]Decisions:[/bold]")
        for item in handoff.decisions:
            console.print(f"  • {item}")


@app.command()
def status() -> None:
    """Show token usage, budget, and brain/index health."""
    config: TeakConfig = load_config()
    console.print(f"[bold]Project:[/bold] {config.project_root}")
    console.print(f"[bold]Default model:[/bold] {config.default_model}")

    brain_manager = BrainManager(config)
    if brain_manager.exists():
        console.print("[bold]Brain:[/bold] [green]ready[/green]")
        for line in brain_manager.summary_lines():
            console.print(f"  • {line}")
    else:
        console.print(
            "[bold]Brain:[/bold] [yellow]not initialized[/yellow] — run [dim]teak init[/dim]"
        )

    if config.db_path.exists():
        store = VectorStore(config.db_path)
        try:
            stats = store.stats()
            console.print(
                f"[bold]Index:[/bold] {stats['files']} files, "
                f"{stats['symbols']} symbols, {stats['calls']} call edges, "
                f"{stats['imports']} imports"
            )
        except Exception as e:
            console.print(f"[bold]Index:[/bold] [yellow]unreadable: {e}[/yellow]")
    else:
        console.print(
            "[bold]Index:[/bold] [yellow]empty[/yellow] — run [dim]teak index[/dim]"
        )


if __name__ == "__main__":
    app()

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from teak.flow.state import SessionState
from teak.vcs.repo import SessionRepo

_console = Console()


def _run_command(command: str, cwd: Path) -> tuple[int, str]:
    """Run `command` in `cwd`. Returns (exit_code, combined_output)."""
    try:
        proc = subprocess.run(
            shlex.split(command),
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        return 124, "verifier timed out after 600s"
    except FileNotFoundError as e:
        return 127, f"verifier command not found: {e}"
    output = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, output[-4000:]  # cap to last 4 KB


def make_node(repo: SessionRepo, project_root: Path):
    """Run the configured verifier command after each accepted step.

    No command configured → no-op (advance).
    Pass → advance current_step.
    Fail with retries left → reset_last, route back to step_runner with failure.
    Fail with retries exhausted → ask user keep / revert / abort.
    """

    def run(state: SessionState) -> dict:
        if not state.verifier_command:
            return {"current_step": state.current_step + 1, "last_failure": ""}

        _console.print(f"[dim]verifier: {state.verifier_command}[/dim]")
        code, output = _run_command(state.verifier_command, project_root)

        if code == 0:
            _console.print("[green]  verifier passed[/green]")
            return {"current_step": state.current_step + 1, "last_failure": ""}

        idx = state.current_step
        attempts = state.step_attempts.get(idx, 0)
        retries_left = state.max_step_retries - attempts

        _console.print(
            Panel(
                output.strip() or "(no output)",
                title=f"verifier failed (exit {code})",
                border_style="red",
            )
        )

        if retries_left > 0:
            _console.print(
                f"[yellow]  retrying step (attempt {attempts + 1}/"
                f"{state.max_step_retries + 1})[/yellow]"
            )
            try:
                if state.last_commit_sha:
                    repo.reset_last()
            except Exception as e:
                _console.print(f"[red]  reset failed: {e}[/red]")
            new_diffs = [s for s in state.diffs if s != state.last_commit_sha]
            return {
                "diffs": new_diffs,
                "last_failure": output,
                "last_commit_sha": "",
            }

        if state.auto:
            choice = "r"  # auto-mode: revert and skip exhausted step
        else:
            choice = Prompt.ask(
                r"[bold]Retries exhausted.[/bold] \[k]eep failing change / "
                r"\[r]evert and skip / \[a]bort session",
                choices=["k", "r", "a"],
                default="r",
                show_choices=False,
            )
        if choice == "k":
            return {
                "current_step": state.current_step + 1,
                "last_failure": output,
            }
        if choice == "a":
            return {
                "current_step": len(state.plan),
                "last_failure": output,
            }
        # default: revert and skip
        try:
            if state.last_commit_sha:
                repo.reset_last()
        except Exception as e:
            _console.print(f"[red]  reset failed: {e}[/red]")
        new_diffs = [s for s in state.diffs if s != state.last_commit_sha]
        return {
            "diffs": new_diffs,
            "current_step": state.current_step + 1,
            "last_failure": output,
            "last_commit_sha": "",
        }

    return run


def detect_default_command(project_root: Path) -> str:
    """Best-effort guess at a verify command for the project. Empty if unknown."""
    pyproj = project_root / "pyproject.toml"
    if pyproj.is_file():
        try:
            text = pyproj.read_text(encoding="utf-8")
            if "[tool.pytest" in text or "pytest" in text:
                return "pytest -q"
        except OSError:
            pass
    pkg_json = project_root / "package.json"
    if pkg_json.is_file():
        try:
            import json
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
            scripts = data.get("scripts", {})
            if "test" in scripts:
                return "npm test --silent"
        except (OSError, ValueError):
            pass
    cargo = project_root / "Cargo.toml"
    if cargo.is_file():
        return "cargo test --quiet"
    gomod = project_root / "go.mod"
    if gomod.is_file():
        return "go test ./..."
    return ""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rich.console import Console

from teak import prompts
from teak.flow.state import PlanStep, SessionState
from teak.llm.client import LLMClient
from teak.vcs.repo import SessionRepo

_console = Console()


def _read_targets(project_root: Path, paths: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for rel in paths:
        p = project_root / rel
        out[rel] = p.read_text(encoding="utf-8") if p.is_file() else ""
    return out


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise ValueError("executor response was not valid JSON")


def _write_files(project_root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        p = project_root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


def _execute_step(
    step: PlanStep,
    *,
    project_root: Path,
    client: LLMClient,
    system_prompt: str,
) -> tuple[dict[str, str], int, int, float]:
    current = _read_targets(project_root, step.target_files)
    user_payload = {
        "step": {
            "title": step.title,
            "rationale": step.rationale,
            "target_files": step.target_files,
        },
        "current_files": current,
    }
    response = client.complete(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload)},
        ],
        json_mode=True,
    )
    data = _extract_json(response.text)
    files = data.get("files") or {}
    if not isinstance(files, dict):
        raise ValueError("executor returned non-dict 'files'")
    return (
        {str(k): str(v) for k, v in files.items()},
        response.tokens_in,
        response.tokens_out,
        response.cost_usd,
    )


def make_node(client: LLMClient, repo: SessionRepo, project_root: Path):
    system_prompt = prompts.load("executor")

    def run(state: SessionState) -> dict:
        diffs: list[str] = list(state.diffs)
        tokens_in = state.tokens_in
        tokens_out = state.tokens_out
        cost = state.cost_usd

        for i, step in enumerate(state.plan, 1):
            if step.approved is False:
                continue
            _console.print(f"[cyan]Executing step {i}/{len(state.plan)}: {step.title}[/cyan]")
            files, ti, to, c = _execute_step(
                step,
                project_root=project_root,
                client=client,
                system_prompt=system_prompt,
            )
            tokens_in += ti
            tokens_out += to
            cost += c

            if not files:
                _console.print("[yellow]  (no file changes)[/yellow]")
                continue

            _write_files(project_root, files)
            sha = repo.commit_step(f"teak: {step.title}")
            if sha:
                diffs.append(sha)
                _console.print(f"[green]  committed {sha[:8]}[/green]")

        return {
            "diffs": diffs,
            "current_step": len(state.plan),
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": cost,
        }

    return run

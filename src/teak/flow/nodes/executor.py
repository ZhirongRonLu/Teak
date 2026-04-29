from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from rich.console import Console

from teak import prompts
from teak.brain.manager import BrainManager
from teak.context.rag import SubgraphRAG
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


def execute_one_step(
    step: PlanStep,
    *,
    project_root: Path,
    client: LLMClient,
    system_prompt: str,
    rag: Optional[SubgraphRAG] = None,
    rag_token_budget: int = 800,
    failure_context: str = "",
) -> tuple[dict[str, str], int, int, float]:
    """Run the LLM for one plan step and return the proposed file contents.

    Pure: reads target files, calls the LLM, returns (files, tokens_in,
    tokens_out, cost_usd). Does not write to disk or commit.
    """
    current = _read_targets(project_root, step.target_files)
    user_payload: dict[str, Any] = {
        "step": {
            "title": step.title,
            "rationale": step.rationale,
            "target_files": step.target_files,
        },
        "current_files": current,
    }
    if failure_context:
        user_payload["previous_failure"] = failure_context

    user_messages: list[dict[str, Any]] = [
        {"role": "user", "content": json.dumps(user_payload)},
    ]
    if rag is not None:
        query = " ".join([step.title, step.rationale, *step.target_files])
        ctx = rag.retrieve(query, token_budget=rag_token_budget)
        if ctx.snippets:
            user_messages.insert(0, {"role": "user", "content": ctx.to_prompt()})

    response = client.complete(
        [{"role": "system", "content": system_prompt}, *user_messages],
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


def make_node(
    client: LLMClient,
    repo: SessionRepo,
    project_root: Path,
    brain: Optional[BrainManager] = None,
    rag: Optional[SubgraphRAG] = None,
    rag_token_budget: int = 800,
):
    """Single-step executor node.

    Reads `state.current_step`, runs one LLM call, writes the proposed files,
    and commits. Returns updated counters and the new commit sha. Approval
    and verification happen in downstream nodes.
    """
    executor_prompt = prompts.load("executor")
    brain_prompt = brain.cached_system_prompt() if brain and brain.exists() else ""
    system_prompt = "\n\n".join(p for p in (brain_prompt, executor_prompt) if p)

    def run(state: SessionState) -> dict:
        step = state.current()
        if step is None:
            return {}
        if step.approved is False:
            return {"current_step": state.current_step + 1}

        idx = state.current_step
        attempts = dict(state.step_attempts)
        attempts[idx] = attempts.get(idx, 0) + 1

        _console.print(
            f"[cyan]Executing step {idx + 1}/{len(state.plan)}: {step.title}[/cyan]"
            + (f" [dim](retry {attempts[idx] - 1})[/dim]" if attempts[idx] > 1 else "")
        )

        files, ti, to, cost = execute_one_step(
            step,
            project_root=project_root,
            client=client,
            system_prompt=system_prompt,
            rag=rag,
            rag_token_budget=rag_token_budget,
            failure_context=state.last_failure,
        )

        new_diffs = list(state.diffs)
        sha = ""
        if files:
            _write_files(project_root, files)
            sha = repo.commit_step(f"teak: {step.title}")
            if sha:
                new_diffs.append(sha)
                _console.print(f"[green]  committed {sha[:8]}[/green]")
            else:
                _console.print("[yellow]  (executor produced no changes)[/yellow]")
        else:
            _console.print("[yellow]  (executor returned no file changes)[/yellow]")

        return {
            "diffs": new_diffs,
            "tokens_in": state.tokens_in + ti,
            "tokens_out": state.tokens_out + to,
            "cost_usd": state.cost_usd + cost,
            "step_attempts": attempts,
            "last_failure": "",
            "last_commit_sha": sha,
        }

    return run

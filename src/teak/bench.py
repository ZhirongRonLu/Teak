"""Token efficiency benchmark harness.

Measures tokens / cost / cache hit ratio across a list of tasks defined in
JSON. Per task you can run:

  - `teak`: full Teak session in `--auto` mode (planner → executor → handoff).
  - `naive`: a single LLM call where the prompt is the entire source tree
    concatenated. This is the strawman every IDE-style coding tool starts
    with — it's what Teak's subgraph RAG + brain caching is meant to beat.

Output is CSV so you can paste it into a spreadsheet or a launch blog post.
The benchmark binary itself is purposely short and dumb: it doesn't try to
score correctness, only spend.
"""
from __future__ import annotations

import csv
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Optional

import litellm

from teak.brain.bootstrapper import _SKIP_DIR_NAMES
from teak.config import TeakConfig
from teak.context.parser import language_for
from teak.flow.graph import run_session
from teak.llm.client import LLMClient
from teak.llm.routing import TaskKind
from teak.vcs.repo import SessionRepo


@dataclass
class TaskSpec:
    name: str
    project_path: str
    task: str
    base_ref: str = "HEAD"  # commit to reset to between modes


@dataclass
class BenchResult:
    task: str
    mode: str  # "teak" | "naive"
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    elapsed_s: float = 0.0
    error: str = ""


# ---- task list IO ----------------------------------------------------------


def load_tasks(path: Path) -> list[TaskSpec]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    tasks_raw = raw.get("tasks", raw) if isinstance(raw, dict) else raw
    out: list[TaskSpec] = []
    for entry in tasks_raw:
        out.append(
            TaskSpec(
                name=str(entry["name"]),
                project_path=str(entry["project_path"]),
                task=str(entry["task"]),
                base_ref=str(entry.get("base_ref", "HEAD")),
            )
        )
    return out


def write_csv(results: list[BenchResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(asdict(results[0]).keys()) if results else ["task"])
        writer.writeheader()
        for r in results:
            writer.writerow(asdict(r))


# ---- runners ---------------------------------------------------------------


def _reset_to(repo_path: Path, ref: str) -> None:
    """Hard reset the project's working tree back to `ref`."""
    sr = SessionRepo(project_root=repo_path)
    try:
        sr._repo.git.reset("--hard", ref)
        sr._repo.git.clean("-fd")
    except Exception:
        pass


def run_teak(spec: TaskSpec, *, model: Optional[str] = None) -> BenchResult:
    project = Path(spec.project_path).resolve()
    config = TeakConfig.for_project(project)
    started = time.monotonic()
    try:
        state = run_session(
            config,
            task=spec.task,
            model=model,
            auto=True,
            use_context=True,
            max_step_retries=1,
        )
    except Exception as e:
        return BenchResult(task=spec.name, mode="teak", error=str(e))
    elapsed = time.monotonic() - started
    return BenchResult(
        task=spec.name,
        mode="teak",
        tokens_in=state.tokens_in,
        tokens_out=state.tokens_out,
        cost_usd=state.cost_usd,
        cache_read_tokens=state.cache_read_tokens,
        cache_creation_tokens=state.cache_creation_tokens,
        elapsed_s=elapsed,
    )


def _gather_source(project: Path, max_bytes: int = 200_000) -> dict[str, str]:
    """Read all language-supported source files up to a byte cap."""
    out: dict[str, str] = {}
    total = 0
    for path in sorted(project.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(project).parts
        if any(part in _SKIP_DIR_NAMES for part in rel_parts[:-1]):
            continue
        if language_for(path) is None:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if total + len(text) > max_bytes:
            break
        out[str(path.relative_to(project))] = text
        total += len(text)
    return out


def run_naive(spec: TaskSpec, *, model: str) -> BenchResult:
    """Strawman baseline: dump the source tree, ask once, count tokens."""
    project = Path(spec.project_path).resolve()
    files = _gather_source(project)
    payload = {
        "task": spec.task,
        "files": files,
    }
    messages = [
        {
            "role": "system",
            "content": (
                "You are a coding assistant. Given the entire codebase below, "
                "produce the file edits required to accomplish the task. "
                "Respond with ONLY a JSON object: "
                '{"files": {"<path>": "<full new content>"}, "summary": "..."}'
            ),
        },
        {"role": "user", "content": json.dumps(payload)},
    ]
    started = time.monotonic()
    client = LLMClient(default_model=model)
    try:
        resp = client.complete(messages, json_mode=True, kind=TaskKind.GENERATE_CODE)
    except Exception as e:
        return BenchResult(task=spec.name, mode="naive", error=str(e))
    elapsed = time.monotonic() - started
    return BenchResult(
        task=spec.name,
        mode="naive",
        tokens_in=resp.tokens_in,
        tokens_out=resp.tokens_out,
        cost_usd=resp.cost_usd,
        cache_read_tokens=resp.cache_read_tokens,
        cache_creation_tokens=resp.cache_creation_tokens,
        elapsed_s=elapsed,
    )


def run_benchmark(
    tasks: Iterable[TaskSpec],
    *,
    modes: list[str],
    model: str,
) -> list[BenchResult]:
    """Run every task in every requested mode. Resets the repo between modes.

    The caller is responsible for `tasks.json` integrity and for reviewing /
    discarding any changes the agent left on disk.
    """
    results: list[BenchResult] = []
    for spec in tasks:
        for mode in modes:
            _reset_to(Path(spec.project_path), spec.base_ref)
            if mode == "teak":
                results.append(run_teak(spec, model=model))
            elif mode == "naive":
                results.append(run_naive(spec, model=model))
            else:
                results.append(BenchResult(task=spec.name, mode=mode, error="unknown mode"))
            _reset_to(Path(spec.project_path), spec.base_ref)
    return results


def summarize(results: list[BenchResult]) -> dict[str, dict[str, float]]:
    """Aggregate per-mode totals across all tasks."""
    by_mode: dict[str, dict[str, float]] = {}
    for r in results:
        bucket = by_mode.setdefault(
            r.mode,
            {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "cache_read_tokens": 0},
        )
        bucket["tokens_in"] += r.tokens_in
        bucket["tokens_out"] += r.tokens_out
        bucket["cost_usd"] += r.cost_usd
        bucket["cache_read_tokens"] += r.cache_read_tokens
    return by_mode

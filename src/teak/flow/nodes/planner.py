from __future__ import annotations

import json
from typing import Any, Optional

from teak import prompts
from teak.brain.manager import BrainManager
from teak.context.rag import SubgraphRAG
from teak.flow.state import PlanStep, SessionState
from teak.llm.client import LLMClient


def parse_plan(text: str) -> tuple[list[PlanStep], str]:
    data = _extract_json(text)
    raw_steps = data.get("steps", [])
    if not isinstance(raw_steps, list):
        raise ValueError(f"planner returned non-list 'steps': {type(raw_steps).__name__}")

    steps: list[PlanStep] = []
    for i, raw in enumerate(raw_steps):
        if not isinstance(raw, dict):
            raise ValueError(f"step {i} is not an object")
        steps.append(
            PlanStep(
                title=str(raw.get("title", f"step {i + 1}")),
                rationale=str(raw.get("rationale", "")),
                target_files=[str(p) for p in raw.get("target_files", [])],
            )
        )
    return steps, str(data.get("notes", ""))


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Tolerate ```json ... ``` fences if a model ignores json_mode.
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError("planner response was not valid JSON")


def make_node(
    client: LLMClient,
    brain: Optional[BrainManager] = None,
    rag: Optional[SubgraphRAG] = None,
    rag_token_budget: int = 600,
):
    planner_prompt = prompts.load("planner")
    brain_prompt = brain.cached_system_prompt() if brain and brain.exists() else ""

    def run(state: SessionState) -> dict:
        system_parts = [p for p in (brain_prompt, planner_prompt) if p]
        user_parts: list[str] = []
        if state.previous_handoff:
            user_parts.append(state.previous_handoff)
        user_parts.append(f"Task: {state.task}")
        if rag is not None:
            ctx = rag.retrieve(state.task, token_budget=rag_token_budget)
            if ctx.snippets:
                user_parts.append(ctx.to_prompt())
        messages = [
            {"role": "system", "content": "\n\n".join(system_parts)},
            {"role": "user", "content": "\n\n".join(user_parts)},
        ]
        response = client.complete(messages, json_mode=True)
        steps, _notes = parse_plan(response.text)
        return {
            "plan": steps,
            "tokens_in": state.tokens_in + response.tokens_in,
            "tokens_out": state.tokens_out + response.tokens_out,
            "cost_usd": state.cost_usd + response.cost_usd,
        }

    return run

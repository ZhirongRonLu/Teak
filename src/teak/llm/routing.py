from __future__ import annotations

from enum import Enum


class TaskKind(str, Enum):
    PLAN = "plan"
    SUMMARIZE = "summarize"
    GENERATE_CODE = "generate_code"
    QUICK_CHAT = "quick_chat"


def choose_model(kind: TaskKind, *, default: str, planner: str) -> str:
    """Cheap model for planning/summarization, heavy model for code generation.

    `default` is the heavy model; `planner` is the cheap one.
    """
    if kind in (TaskKind.PLAN, TaskKind.SUMMARIZE, TaskKind.QUICK_CHAT):
        return planner
    return default

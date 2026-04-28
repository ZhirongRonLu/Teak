from __future__ import annotations

from teak.flow.state import SessionState


def run(state: SessionState) -> SessionState:
    """LangGraph interrupt: present the plan in the textual TUI.

    The user can:
      - approve each step (set `step.approved = True`)
      - edit a step's title/rationale
      - reject a step (drops out of the plan)
      - reject the whole plan (raises an interrupt to abort)
    """
    raise NotImplementedError(state)

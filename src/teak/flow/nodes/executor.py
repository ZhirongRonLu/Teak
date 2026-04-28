from __future__ import annotations

from teak.flow.state import SessionState


def run(state: SessionState) -> SessionState:
    """Execute exactly one approved plan step.

    Steps:
      1. Pick `state.plan[state.current_step]`.
      2. Generate the code change (heavy model).
      3. Show inline diff to user; on accept, commit to the session branch.
      4. Increment `state.current_step` and append the diff.

    On reject: `git reset HEAD~1` and stay on the same step (Planner can revise).
    """
    raise NotImplementedError(state)

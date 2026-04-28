from __future__ import annotations

from teak.flow.state import SessionState


def run(state: SessionState) -> SessionState:
    """After the session completes, propose minimal brain updates.

    Reads `state.diffs`, asks the LLM for diffs to ARCHITECTURE/CONVENTIONS/
    DECISIONS/MEMORY, and routes them through human approval before writing.
    """
    raise NotImplementedError(state)

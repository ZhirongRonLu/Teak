from __future__ import annotations

from teak.flow.state import SessionState


def run(state: SessionState) -> SessionState:
    """Run the project's tests + linter after each executor step.

    On failure: append failure output to `state.test_failures` and route back to
    the Executor for self-correction (with a retry budget). On success: clear
    failures and continue to the next plan step.
    """
    raise NotImplementedError(state)

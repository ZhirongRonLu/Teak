from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from teak.config import TeakConfig
from teak.flow.state import SessionState


@dataclass
class Handoff:
    """One-paragraph summary that auto-prepends to the next session."""

    created_at: datetime
    branch: str
    summary: str
    pending: list[str]
    decisions: list[str]


def generate_handoff(state: SessionState, config: TeakConfig) -> Handoff:
    """Build the handoff summary from session diffs + decisions.

    Persisted into the `sessions` table so `load_last_handoff` can recover it.
    """
    raise NotImplementedError(state, config)


def load_last_handoff(config: TeakConfig) -> Optional[Handoff]:
    """Return the most recent handoff for this project, or None on first run."""
    raise NotImplementedError(config)

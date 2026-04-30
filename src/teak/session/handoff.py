from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

from teak import prompts
from teak.brain.manager import BrainManager
from teak.config import TeakConfig
from teak.context.storage import VectorStore
from teak.flow.state import SessionState
from teak.llm.client import LLMClient
from teak.llm.routing import TaskKind


@dataclass
class Handoff:
    """One-paragraph summary that auto-prepends to the next session."""

    created_at: str  # ISO8601 string for round-tripping through SQLite
    branch: str
    summary: str
    pending: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0

    def to_prompt(self) -> str:
        parts = [f"## Previous session ({self.created_at}, branch {self.branch})", self.summary]
        if self.pending:
            parts.append("**Pending:** " + "; ".join(self.pending))
        if self.decisions:
            parts.append("**Decisions:** " + "; ".join(self.decisions))
        return "\n\n".join(parts)


def _parse_handoff_json(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("handoff response was not valid JSON")
        return json.loads(text[start : end + 1])


def parse_handoff_payload(text: str, branch: str, created_at: Optional[str] = None) -> Handoff:
    data = _parse_handoff_json(text)
    summary = str(data.get("summary", "")).strip()
    if not summary:
        raise ValueError("handoff missing 'summary'")
    pending = [str(p) for p in data.get("pending", []) if isinstance(p, str)]
    decisions = [str(d) for d in data.get("decisions", []) if isinstance(d, str)]
    return Handoff(
        created_at=created_at or _utc_now(),
        branch=branch,
        summary=summary,
        pending=pending,
        decisions=decisions,
    )


def generate_handoff(
    state: SessionState,
    config: TeakConfig,
    *,
    client: LLMClient,
    diff_summary: str = "",
    brain: Optional[BrainManager] = None,
) -> Handoff:
    """Build the handoff summary from session diffs + decisions."""
    system_prompt = prompts.load("handoff")
    cached_prefix = brain.cached_system_prompt() if brain and brain.exists() else ""

    payload = {
        "task": state.task,
        "branch": state.branch,
        "diff_summary": diff_summary or "(no diff)",
        "commits": state.diffs,
        "tokens_in": state.tokens_in,
        "tokens_out": state.tokens_out,
        "cost_usd": state.cost_usd,
        "last_failure": state.last_failure,
    }
    response = client.complete_cached(
        cached_prefix=cached_prefix,
        instructions=system_prompt,
        user_messages=[{"role": "user", "content": json.dumps(payload)}],
        json_mode=True,
        kind=TaskKind.SUMMARIZE,
    )
    handoff = parse_handoff_payload(response.text, branch=state.branch)
    handoff.tokens_in = state.tokens_in
    handoff.tokens_out = state.tokens_out
    handoff.cost_usd = state.cost_usd
    handoff.cache_read_tokens = state.cache_read_tokens
    handoff.cache_creation_tokens = state.cache_creation_tokens
    persist_handoff(handoff, config, state)
    return handoff


def persist_handoff(handoff: Handoff, config: TeakConfig, state: SessionState) -> None:
    """Write the handoff (and accompanying session row) into SQLite."""
    store = VectorStore(config.db_path)
    config.db_path.parent.mkdir(parents=True, exist_ok=True)
    with store.connect() as conn:
        # The vec table is optional here; only the `sessions` table is touched.
        conn.executescript(VectorStore.BASE_SCHEMA)
        conn.execute(
            "INSERT INTO sessions(started_at, ended_at, branch, tokens_in, tokens_out, cost_usd, handoff) "
            "VALUES(?, ?, ?, ?, ?, ?, ?)",
            (
                handoff.created_at,
                handoff.created_at,
                handoff.branch,
                state.tokens_in,
                state.tokens_out,
                state.cost_usd,
                json.dumps(asdict(handoff)),
            ),
        )


def load_all_handoffs(config: TeakConfig) -> list[Handoff]:
    """All handoffs in chronological order (oldest first)."""
    if not config.db_path.exists():
        return []
    store = VectorStore(config.db_path)
    handoffs: list[Handoff] = []
    with store.connect() as conn:
        rows = conn.execute(
            "SELECT handoff FROM sessions WHERE handoff IS NOT NULL ORDER BY id ASC"
        ).fetchall()
    for row in rows:
        if not row[0]:
            continue
        try:
            data = json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            continue
        handoffs.append(
            Handoff(
                created_at=data.get("created_at", ""),
                branch=data.get("branch", ""),
                summary=data.get("summary", ""),
                pending=list(data.get("pending", [])),
                decisions=list(data.get("decisions", [])),
                tokens_in=int(data.get("tokens_in", 0) or 0),
                tokens_out=int(data.get("tokens_out", 0) or 0),
                cost_usd=float(data.get("cost_usd", 0.0) or 0.0),
                cache_read_tokens=int(data.get("cache_read_tokens", 0) or 0),
                cache_creation_tokens=int(data.get("cache_creation_tokens", 0) or 0),
            )
        )
    return handoffs


def aggregate_usage(handoffs: list[Handoff]) -> dict[str, float]:
    """Sum tokens / cost / cache stats across a list of handoffs."""
    total_in = sum(h.tokens_in for h in handoffs)
    total_out = sum(h.tokens_out for h in handoffs)
    cache_read = sum(h.cache_read_tokens for h in handoffs)
    cache_creation = sum(h.cache_creation_tokens for h in handoffs)
    cost = sum(h.cost_usd for h in handoffs)
    cache_billable = total_in  # input side
    hit_ratio = (cache_read / cache_billable) if cache_billable else 0.0
    return {
        "sessions": len(handoffs),
        "tokens_in": total_in,
        "tokens_out": total_out,
        "cost_usd": cost,
        "cache_read_tokens": cache_read,
        "cache_creation_tokens": cache_creation,
        "cache_hit_ratio": hit_ratio,
    }


def load_last_handoff(config: TeakConfig) -> Optional[Handoff]:
    """Return the most recent handoff for this project, or None on first run."""
    if not config.db_path.exists():
        return None
    store = VectorStore(config.db_path)
    with store.connect() as conn:
        row = conn.execute(
            "SELECT handoff FROM sessions WHERE handoff IS NOT NULL "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if row is None or not row[0]:
        return None
    try:
        data = json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        return None
    return Handoff(
        created_at=data.get("created_at", ""),
        branch=data.get("branch", ""),
        summary=data.get("summary", ""),
        pending=list(data.get("pending", [])),
        decisions=list(data.get("decisions", [])),
        tokens_in=int(data.get("tokens_in", 0) or 0),
        tokens_out=int(data.get("tokens_out", 0) or 0),
        cost_usd=float(data.get("cost_usd", 0.0) or 0.0),
        cache_read_tokens=int(data.get("cache_read_tokens", 0) or 0),
        cache_creation_tokens=int(data.get("cache_creation_tokens", 0) or 0),
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

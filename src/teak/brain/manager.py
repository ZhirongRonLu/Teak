from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from teak import prompts
from teak.config import TeakConfig, load_config
from teak.llm.client import LLMClient
from teak.llm.routing import TaskKind

BRAIN_FILES: tuple[str, ...] = (
    "ARCHITECTURE.md",
    "CONVENTIONS.md",
    "DECISIONS.md",
    "MEMORY.md",
)


@dataclass
class BrainFile:
    name: str
    path: Path

    def read(self) -> str:
        return self.path.read_text(encoding="utf-8") if self.path.exists() else ""

    def write(self, content: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(content, encoding="utf-8")


class BrainManager:
    """Read, write, and validate the four Project Brain files."""

    def __init__(self, config: TeakConfig) -> None:
        self.config = config
        self.files: dict[str, BrainFile] = {
            name: BrainFile(name=name, path=config.brain_dir / name)
            for name in BRAIN_FILES
        }

    @classmethod
    def for_cwd(cls) -> "BrainManager":
        return cls(load_config())

    def exists(self) -> bool:
        return self.config.brain_dir.is_dir() and all(
            f.path.exists() for f in self.files.values()
        )

    def read_all(self) -> dict[str, str]:
        return {name: f.read() for name, f in self.files.items()}

    def cached_system_prompt(self) -> str:
        """System.md prefix + all four brain files concatenated.

        Phase 1: returns the stitched string. Phase 4 will mark this prefix as
        cacheable via Anthropic cache_control headers — the structure is fixed
        now so the cache key stays stable across sessions.
        """
        base = prompts.load("system").rstrip()
        if not self.exists():
            return base + "\n\n(no project brain initialized)\n"

        sections: list[str] = [base, ""]
        for name in BRAIN_FILES:
            body = self.files[name].read().strip()
            sections.append(f"## {name}\n\n{body}\n")
        return "\n".join(sections)

    def propose_updates(
        self,
        diff_summary: str,
        client: LLMClient,
    ) -> dict[str, str]:
        """Ask the LLM for minimal updates to brain files based on session diffs.

        Returns a dict mapping brain file names → new full content. Files the
        LLM judged unchanged are omitted from the result.
        """
        system_prompt = prompts.load("brain_updater")
        current = self.read_all()
        payload = {
            "current_brain": current,
            "diff_summary": diff_summary,
        }
        response = client.complete_cached(
            cached_prefix=self.cached_system_prompt(),
            instructions=system_prompt,
            user_messages=[{"role": "user", "content": json.dumps(payload)}],
            json_mode=True,
            kind=TaskKind.SUMMARIZE,
        )
        return parse_brain_update(response.text)

    def apply_updates(self, updates: dict[str, str]) -> None:
        for name, content in updates.items():
            if name not in self.files:
                raise KeyError(f"unknown brain file: {name}")
            self.files[name].write(content)

    def detect_violations(
        self,
        planned_changes: Iterable[str],
        client: LLMClient,
    ) -> list[ConventionViolation]:
        """LLM-backed convention check.

        Returns one entry per *flagged* step. An empty list means the plan is
        compatible with the current CONVENTIONS.md / DECISIONS.md.
        """
        steps = [s for s in planned_changes if s.strip()]
        if not steps or not self.exists():
            return []

        system_prompt = prompts.load("convention_check")
        payload = {
            "conventions": self.files["CONVENTIONS.md"].read(),
            "decisions": self.files["DECISIONS.md"].read(),
            "planned_steps": [
                {"index": i, "description": text} for i, text in enumerate(steps)
            ],
        }
        response = client.complete_cached(
            cached_prefix=self.cached_system_prompt(),
            instructions=system_prompt,
            user_messages=[{"role": "user", "content": json.dumps(payload)}],
            json_mode=True,
            kind=TaskKind.SUMMARIZE,
        )
        return parse_violations(response.text)

    def summary_lines(self) -> list[str]:
        """Short human-readable status line per brain file (for `teak brain`)."""
        out: list[str] = []
        for name in BRAIN_FILES:
            f = self.files[name]
            if not f.path.exists():
                out.append(f"{name}: missing")
                continue
            text = f.read().strip()
            head = text.splitlines()[0] if text else "(empty)"
            out.append(f"{name}: {len(text)} chars — {head[:80]}")
        return out


@dataclass
class ConventionViolation:
    step_index: int
    rule: str  # the convention/decision the step appears to break
    detail: str  # one-sentence explanation


def parse_violations(text: str) -> list[ConventionViolation]:
    text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("convention check response was not valid JSON")
        data = json.loads(text[start : end + 1])

    if not isinstance(data, dict):
        raise ValueError("convention check response is not a JSON object")
    raw = data.get("violations", [])
    if not isinstance(raw, list):
        raise ValueError("'violations' must be a list")

    out: list[ConventionViolation] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValueError("each violation must be an object")
        try:
            idx = int(entry.get("step_index", -1))
        except (TypeError, ValueError):
            idx = -1
        rule = str(entry.get("rule", "")).strip()
        detail = str(entry.get("detail", "")).strip()
        if not rule and not detail:
            continue
        out.append(ConventionViolation(step_index=idx, rule=rule, detail=detail))
    return out


def parse_brain_update(text: str) -> dict[str, str]:
    """Parse the JSON object returned by the brain_updater prompt."""
    text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("brain updater response was not valid JSON")
        data = json.loads(text[start : end + 1])

    if not isinstance(data, dict):
        raise ValueError("brain updater response is not a JSON object")

    raw_updates = data.get("updates")
    if raw_updates in (None, {}):
        return {}
    if not isinstance(raw_updates, dict):
        raise ValueError("'updates' must be an object")

    out: dict[str, str] = {}
    for name, content in raw_updates.items():
        if name not in BRAIN_FILES:
            raise ValueError(f"unknown brain file in update: {name!r}")
        if not isinstance(content, str):
            raise ValueError(f"update for {name} is not a string")
        out[name] = content
    return out


def load_brain(config: Optional[TeakConfig] = None) -> BrainManager:
    return BrainManager(config or load_config())

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from teak.config import TeakConfig, load_config

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
        """Concatenated brain content, formatted for prompt-cached system prompts."""
        raise NotImplementedError

    def propose_updates(self, diff_summary: str) -> dict[str, str]:
        """Ask the LLM for minimal updates to brain files based on session diffs."""
        raise NotImplementedError

    def apply_updates(self, updates: dict[str, str]) -> None:
        for name, content in updates.items():
            if name not in self.files:
                raise KeyError(f"unknown brain file: {name}")
            self.files[name].write(content)

    def detect_violations(self, planned_changes: Iterable[str]) -> list[str]:
        """Return a list of convention violations detected in `planned_changes`."""
        raise NotImplementedError

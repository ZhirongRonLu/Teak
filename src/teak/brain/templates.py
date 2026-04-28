from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class BrainTemplate:
    """A community-shareable starter brain for a common stack."""

    name: str
    description: str
    files: dict[str, str]  # filename -> markdown content

    def install_into(self, brain_dir: Path) -> None:
        brain_dir.mkdir(parents=True, exist_ok=True)
        for name, content in self.files.items():
            (brain_dir / name).write_text(content, encoding="utf-8")


def list_templates() -> list[BrainTemplate]:
    """Return all known templates (built-in + user-installed)."""
    raise NotImplementedError


def load_template(name: str) -> BrainTemplate:
    """Load a single template by name (e.g. 'django-rest', 'next-monorepo')."""
    raise NotImplementedError(name)

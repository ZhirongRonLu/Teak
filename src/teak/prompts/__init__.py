from __future__ import annotations

from importlib import resources
from typing import Final

_PROMPTS_PACKAGE: Final[str] = "teak.prompts"


def load(name: str) -> str:
    """Load a prompt template by name (without the .md suffix)."""
    return resources.files(_PROMPTS_PACKAGE).joinpath(f"{name}.md").read_text(
        encoding="utf-8"
    )

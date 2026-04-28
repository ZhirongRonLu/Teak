from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

TEAK_DIR_NAME = ".teak"
BRAIN_DIR_NAME = "brain"
DB_FILE_NAME = "teak.db"
TEMPLATES_DIR_NAME = "templates"


@dataclass
class TeakConfig:
    """Resolved configuration for a single Teak invocation."""

    project_root: Path
    teak_dir: Path
    brain_dir: Path
    db_path: Path
    templates_dir: Path
    default_model: str = "anthropic/claude-sonnet-4-6"
    planner_model: str = "anthropic/claude-haiku-4-5-20251001"
    session_budget_usd: Optional[float] = None
    languages: tuple[str, ...] = field(
        default_factory=lambda: ("python", "typescript", "javascript", "rust", "go")
    )

    @classmethod
    def for_project(cls, project_root: Path) -> "TeakConfig":
        teak_dir = project_root / TEAK_DIR_NAME
        return cls(
            project_root=project_root,
            teak_dir=teak_dir,
            brain_dir=teak_dir / BRAIN_DIR_NAME,
            db_path=teak_dir / DB_FILE_NAME,
            templates_dir=teak_dir / TEMPLATES_DIR_NAME,
        )


def find_project_root(start: Optional[Path] = None) -> Path:
    """Walk up from `start` to find the nearest directory containing `.teak/`.

    Falls back to the current working directory if no `.teak/` is found.
    """
    cwd = (start or Path.cwd()).resolve()
    for candidate in (cwd, *cwd.parents):
        if (candidate / TEAK_DIR_NAME).is_dir():
            return candidate
    return cwd


def load_config(start: Optional[Path] = None) -> TeakConfig:
    """Load configuration for the project rooted at or above `start`."""
    return TeakConfig.for_project(find_project_root(start))

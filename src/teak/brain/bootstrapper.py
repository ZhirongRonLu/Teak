from __future__ import annotations

from pathlib import Path
from typing import Optional

from teak.brain.manager import BrainManager
from teak.config import TeakConfig


def bootstrap_brain(
    project_root: Path,
    template: Optional[str] = None,
) -> BrainManager:
    """Generate initial brain files for a project.

    Steps:
      1. Create `.teak/brain/` and `.teak/templates/`.
      2. If `template` is given, copy that template into the brain.
      3. Otherwise, run a Tree-sitter pass to map the codebase, then ask the
         LLM to draft ARCHITECTURE/CONVENTIONS/DECISIONS/MEMORY in <30s.
      4. Return a BrainManager pointed at the populated directory.

    The user reviews and approves the draft via `teak brain --edit`.
    """
    config = TeakConfig.for_project(project_root)
    config.brain_dir.mkdir(parents=True, exist_ok=True)
    config.templates_dir.mkdir(parents=True, exist_ok=True)
    raise NotImplementedError(template)


def survey_codebase(project_root: Path) -> dict:
    """Run a fast Tree-sitter survey: top-level structure, modules, key symbols."""
    raise NotImplementedError(project_root)

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from teak import prompts
from teak.brain.manager import BRAIN_FILES, BrainManager
from teak.brain.templates import load_template
from teak.config import TeakConfig
from teak.llm.client import LLMClient


_SKIP_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".teak",
        ".venv",
        "venv",
        "env",
        ".env",
        "node_modules",
        "build",
        "dist",
        "target",
        ".next",
        ".nuxt",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".idea",
        ".vscode",
        ".DS_Store",
        "vendor",
        "coverage",
    }
)

_MANIFEST_FILES: tuple[str, ...] = (
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "requirements.txt",
    "package.json",
    "tsconfig.json",
    "Cargo.toml",
    "go.mod",
    "Gemfile",
    "pom.xml",
    "build.gradle",
)

_README_NAMES: tuple[str, ...] = ("README.md", "README.rst", "README.txt", "README")

_SOURCE_EXTS: frozenset[str] = frozenset(
    {".py", ".ts", ".tsx", ".js", ".jsx", ".rs", ".go", ".java", ".rb"}
)

_MAX_TREE_ENTRIES: int = 200
_MAX_FILE_SNIPPET_BYTES: int = 1500
_MAX_MANIFEST_BYTES: int = 4000
_MAX_README_BYTES: int = 4000


@dataclass
class CodebaseSurvey:
    project_root: Path
    tree: list[str]
    manifests: dict[str, str]
    readme: Optional[str]
    source_snippets: dict[str, str]

    def to_prompt(self) -> str:
        parts: list[str] = [f"# Project at {self.project_root.name}"]
        if self.readme:
            parts.append("## README\n" + self.readme)
        if self.manifests:
            parts.append("## Manifests")
            for name, body in self.manifests.items():
                parts.append(f"### {name}\n```\n{body}\n```")
        parts.append("## File tree (truncated)")
        parts.append("```\n" + "\n".join(self.tree) + "\n```")
        if self.source_snippets:
            parts.append("## Source snippets")
            for name, body in self.source_snippets.items():
                parts.append(f"### {name}\n```\n{body}\n```")
        return "\n\n".join(parts)


def _iter_files(project_root: Path) -> Iterable[Path]:
    for path in project_root.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(project_root).parts
        if any(part in _SKIP_DIR_NAMES for part in rel_parts[:-1]):
            continue
        yield path


def _read_truncated(path: Path, limit: int) -> str:
    try:
        data = path.read_bytes()[:limit]
        return data.decode("utf-8", errors="replace")
    except OSError:
        return ""


def _pick_source_snippets(files: list[Path], project_root: Path, max_files: int = 6) -> dict[str, str]:
    candidates = [p for p in files if p.suffix in _SOURCE_EXTS]
    candidates.sort(key=lambda p: (len(p.relative_to(project_root).parts), str(p)))
    snippets: dict[str, str] = {}
    for path in candidates[:max_files]:
        rel = str(path.relative_to(project_root))
        snippets[rel] = _read_truncated(path, _MAX_FILE_SNIPPET_BYTES)
    return snippets


def survey_codebase(project_root: Path) -> CodebaseSurvey:
    """Fast filesystem survey: tree + manifests + README + a handful of source snippets."""
    project_root = project_root.resolve()
    files: list[Path] = list(_iter_files(project_root))

    tree: list[str] = []
    for path in sorted(files, key=lambda p: str(p.relative_to(project_root)))[:_MAX_TREE_ENTRIES]:
        tree.append(str(path.relative_to(project_root)))

    manifests: dict[str, str] = {}
    for name in _MANIFEST_FILES:
        candidate = project_root / name
        if candidate.is_file():
            manifests[name] = _read_truncated(candidate, _MAX_MANIFEST_BYTES)

    readme: Optional[str] = None
    for name in _README_NAMES:
        candidate = project_root / name
        if candidate.is_file():
            readme = _read_truncated(candidate, _MAX_README_BYTES)
            break

    snippets = _pick_source_snippets(files, project_root)

    return CodebaseSurvey(
        project_root=project_root,
        tree=tree,
        manifests=manifests,
        readme=readme,
        source_snippets=snippets,
    )


def _parse_brain_payload(text: str) -> dict[str, str]:
    text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("bootstrapper response was not valid JSON")
        data = json.loads(text[start : end + 1])

    if not isinstance(data, dict):
        raise ValueError("bootstrapper response is not a JSON object")

    out: dict[str, str] = {}
    for name in BRAIN_FILES:
        value = data.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"missing or empty content for {name}")
        out[name] = value
    return out


def _draft_with_llm(survey: CodebaseSurvey, client: LLMClient) -> dict[str, str]:
    system_prompt = prompts.load("bootstrapper")
    user_payload = (
        "Produce a JSON object with exactly these keys (each value is the full "
        "Markdown body of that file):\n"
        f"{', '.join(BRAIN_FILES)}\n\n"
        "Codebase survey follows.\n\n" + survey.to_prompt()
    )
    response = client.complete(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_payload},
        ],
        json_mode=True,
    )
    return _parse_brain_payload(response.text)


def bootstrap_brain(
    project_root: Path,
    template: Optional[str] = None,
    *,
    client: Optional[LLMClient] = None,
) -> BrainManager:
    """Generate initial brain files for a project.

    If `template` is given, install that template's files. Otherwise survey the
    codebase and ask the LLM to draft ARCHITECTURE/CONVENTIONS/DECISIONS/MEMORY.
    """
    config = TeakConfig.for_project(project_root)
    config.brain_dir.mkdir(parents=True, exist_ok=True)
    config.templates_dir.mkdir(parents=True, exist_ok=True)

    manager = BrainManager(config)

    if template is not None:
        loaded = load_template(template)
        loaded.install_into(config.brain_dir)
        return manager

    if client is None:
        client = LLMClient(default_model=config.planner_model)

    survey = survey_codebase(project_root)
    contents = _draft_with_llm(survey, client)
    manager.apply_updates(contents)
    return manager

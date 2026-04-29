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


_PYTHON_CLI = BrainTemplate(
    name="python-cli",
    description="Typer/Click-based Python CLI with pytest.",
    files={
        "ARCHITECTURE.md": (
            "# Architecture\n\n"
            "- Entry point: `src/<pkg>/cli.py` (Typer app).\n"
            "- Subcommands live as `@app.command()` functions.\n"
            "- Side-effectful logic moves into modules under `src/<pkg>/`; the\n"
            "  CLI layer is a thin shell.\n"
            "- Configuration loaded from environment + optional dotfile.\n"
        ),
        "CONVENTIONS.md": (
            "# Conventions\n\n"
            "- Type-annotate every public function. `from __future__ import annotations`.\n"
            "- Prefer `pathlib.Path` over `str` for paths.\n"
            "- Tests use `pytest`, fixtures via `tmp_path` for filesystem work.\n"
            "- No prints inside library code; CLI uses `rich.console.Console`.\n"
        ),
        "DECISIONS.md": (
            "# Decisions\n\n"
            "- Typer over argparse: better ergonomics, free `--help`.\n"
            "- `src/` layout: prevents accidental imports of the working tree.\n"
        ),
        "MEMORY.md": (
            "# Memory\n\n"
            "- Open questions: (none yet — fill in as the project grows).\n"
        ),
    },
)


_DJANGO_REST = BrainTemplate(
    name="django-rest",
    description="Django + Django REST Framework backend.",
    files={
        "ARCHITECTURE.md": (
            "# Architecture\n\n"
            "- Django apps under `apps/<feature>/` — models, serializers, views.\n"
            "- DRF ViewSets + routers in each app's `urls.py`.\n"
            "- Background work via Celery (broker: Redis).\n"
            "- Settings split: `base.py`, `dev.py`, `prod.py` under `config/settings/`.\n"
        ),
        "CONVENTIONS.md": (
            "# Conventions\n\n"
            "- Repository pattern: views call services, services own ORM access.\n"
            "- Serializers do validation only; no side effects.\n"
            "- Migrations are reviewed; never edit a merged migration.\n"
            "- Avoid `select_related` / `prefetch_related` cargo-culting — measure first.\n"
        ),
        "DECISIONS.md": (
            "# Decisions\n\n"
            "- DRF over plain Django views: schema generation + auth come for free.\n"
            "- Celery over RQ: matured tooling, mature monitoring story.\n"
        ),
        "MEMORY.md": (
            "# Memory\n\n"
            "- Open questions: (none yet).\n"
        ),
    },
)


_NEXT_MONOREPO = BrainTemplate(
    name="next-monorepo",
    description="Turborepo with Next.js apps + shared packages.",
    files={
        "ARCHITECTURE.md": (
            "# Architecture\n\n"
            "- Turborepo at the root; `apps/*` for runnable apps, `packages/*` for libs.\n"
            "- Next.js (App Router) per app. Server components by default.\n"
            "- Shared UI in `packages/ui`; shared config in `packages/config`.\n"
        ),
        "CONVENTIONS.md": (
            "# Conventions\n\n"
            "- TS strict mode everywhere; no `any` without a comment.\n"
            "- Server components for data fetching; client components only when needed.\n"
            "- Tailwind for styling; tokens live in `packages/ui/tokens.ts`.\n"
        ),
        "DECISIONS.md": (
            "# Decisions\n\n"
            "- Turborepo over Nx: lighter, fits a small team.\n"
            "- App Router over Pages: streaming + RSC are core to our UX.\n"
        ),
        "MEMORY.md": (
            "# Memory\n\n"
            "- Open questions: (none yet).\n"
        ),
    },
)


_BUILTINS: dict[str, BrainTemplate] = {
    t.name: t for t in (_PYTHON_CLI, _DJANGO_REST, _NEXT_MONOREPO)
}


def list_templates() -> list[BrainTemplate]:
    """Return all built-in templates."""
    return list(_BUILTINS.values())


def load_template(name: str) -> BrainTemplate:
    """Load a single template by name."""
    try:
        return _BUILTINS[name]
    except KeyError:
        available = ", ".join(sorted(_BUILTINS))
        raise KeyError(f"unknown brain template {name!r}; available: {available}") from None

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from teak.brain.manager import BRAIN_FILES


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


_GO_MICROSERVICE = BrainTemplate(
    name="go-microservice",
    description="Go HTTP microservice with chi router + sqlx.",
    files={
        "ARCHITECTURE.md": (
            "# Architecture\n\n"
            "- `cmd/<service>/main.go` is the entry; it wires deps and starts the server.\n"
            "- HTTP layer in `internal/http/`: chi router, middleware, handlers.\n"
            "- Domain logic in `internal/<feature>/`: services, repositories, types.\n"
            "- Persistence via sqlx; SQL lives next to its repository in `*.sql.go`.\n"
            "- Observability: structured logs via `slog`, metrics via Prometheus.\n"
        ),
        "CONVENTIONS.md": (
            "# Conventions\n\n"
            "- One package per directory; package name matches the directory.\n"
            "- Errors: wrap with `fmt.Errorf(\"...: %w\", err)`; never swallow.\n"
            "- Context-first: every blocking call takes `ctx context.Context`.\n"
            "- No global state. Pass dependencies through constructors.\n"
            "- Tests are table-driven; integration tests use `testcontainers`.\n"
        ),
        "DECISIONS.md": (
            "# Decisions\n\n"
            "- chi over gin: smaller surface, stdlib-friendly middleware.\n"
            "- sqlx over GORM: explicit SQL, predictable performance.\n"
            "- slog over zap: now in stdlib; one fewer dep.\n"
        ),
        "MEMORY.md": (
            "# Memory\n\n"
            "- Open questions: (none yet).\n"
        ),
    },
)


_BUILTINS: dict[str, BrainTemplate] = {
    t.name: t for t in (_PYTHON_CLI, _DJANGO_REST, _NEXT_MONOREPO, _GO_MICROSERVICE)
}


def user_template_dir() -> Path:
    """Where Teak looks for community/user-installed templates."""
    return Path.home() / ".teak" / "templates"


def list_templates() -> list[BrainTemplate]:
    """Built-in templates plus anything under `~/.teak/templates/`.

    A user-installed template with the same name as a built-in shadows the
    built-in (the user wins).
    """
    catalog: dict[str, BrainTemplate] = dict(_BUILTINS)
    for tpl in _iter_filesystem_templates(user_template_dir()):
        catalog[tpl.name] = tpl
    return sorted(catalog.values(), key=lambda t: t.name)


def load_template(name: str) -> BrainTemplate:
    """Load a single template by name. User dir wins over built-ins."""
    user_dir = user_template_dir() / name
    if user_dir.is_dir():
        loaded = _read_filesystem_template(user_dir)
        if loaded is not None:
            return loaded
    if name in _BUILTINS:
        return _BUILTINS[name]
    available = ", ".join(sorted(set(_BUILTINS) | _user_template_names()))
    raise KeyError(f"unknown brain template {name!r}; available: {available}")


# ---- filesystem template helpers -------------------------------------------


def _iter_filesystem_templates(root: Path):
    if not root.is_dir():
        return
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        loaded = _read_filesystem_template(entry)
        if loaded is not None:
            yield loaded


def _user_template_names() -> set[str]:
    root = user_template_dir()
    if not root.is_dir():
        return set()
    return {p.name for p in root.iterdir() if p.is_dir()}


def _read_filesystem_template(path: Path) -> Optional[BrainTemplate]:
    """Load a single on-disk template directory.

    Layout:
      <name>/template.json   # optional metadata: {"name", "description"}
      <name>/ARCHITECTURE.md
      <name>/CONVENTIONS.md
      <name>/DECISIONS.md
      <name>/MEMORY.md

    Missing brain files default to a one-line stub so the template still
    installs cleanly.
    """
    name = path.name
    description = ""
    meta_path = path / "template.json"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            name = str(meta.get("name", name))
            description = str(meta.get("description", ""))
        except (OSError, json.JSONDecodeError):
            pass

    files: dict[str, str] = {}
    has_any = False
    for filename in BRAIN_FILES:
        f = path / filename
        if f.is_file():
            try:
                files[filename] = f.read_text(encoding="utf-8")
                has_any = True
                continue
            except OSError:
                pass
        files[filename] = f"# {filename[:-3]}\n\n_(empty)_\n"

    if not has_any:
        return None
    return BrainTemplate(name=name, description=description, files=files)

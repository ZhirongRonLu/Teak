# Teak Desktop

Phase 6 desktop shell for Teak.

The window is split into two resizable halves:

- Left: chat-style task composer for sending work to Teak.
- Right: embedded terminal running in the selected project directory.

Review mode sends `teak plan "<task>"` into the terminal so the existing CLI
approval prompts remain the source of truth. Auto mode appends `--auto`.
Before sending a task, the desktop shell checks `git status --short`; if the
working tree is dirty, it stops and shows commit/stash options because Teak's
rollback model requires a clean git state.

If the dirty list contains `.DS_Store`, add it to a project or global
`.gitignore`. If it contains `?? .teak/`, commit `.teak/.gitignore` and
`.teak/brain/`; `.teak/teak.db` is local runtime state. If it contains
`M .teak/teak.db`, that database is already tracked and must be removed from
the index with `git rm --cached --ignore-unmatch .teak/teak.db .teak/.DS_Store`
before committing the cleanup.

## Run

Prerequisites:

- Node.js + npm.
- Rust + Cargo, required by Tauri.
- Teak available either from this repo's `.venv/bin/teak`, `PYTHONPATH=src
  python -m teak`, or a global install.

On macOS with Homebrew:

```bash
brew install rust
```

```bash
cd desktop
npm install
npm run tauri
```

The desktop bridge automatically adds this repo's `src/` to `PYTHONPATH` and
prepends `.venv/bin` to `PATH` when it can find the Teak source root.

## Build

```bash
cd desktop
npm run tauri:build
```

# Teak Desktop

Phase 6 desktop shell for Teak.

The window is split into two resizable halves:

- Left: chat-style task composer for sending work to Teak.
- Right: embedded terminal running in the selected project directory.

Review mode sends `teak plan "<task>"` into the terminal so the existing CLI
approval prompts remain the source of truth. Auto mode appends `--auto`.

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

# Using Teak (Phase 5)

Phase 5 polishes the CLI MVP into something publishable:

- **Convention Violation Detection** — after the planner emits a plan but
  before approval, Teak checks each step against `CONVENTIONS.md` /
  `DECISIONS.md` and flags conflicts in red. The check is a prompt-cached
  LLM call routed to the cheap planner model.
- **Brain Templates** — the four built-ins (`python-cli`, `django-rest`,
  `next-monorepo`, `go-microservice`) plus filesystem loading from
  `~/.teak/templates/`. Drop a directory there with the four MD files (and
  optionally a `template.json` for `name`/`description`) and it appears in
  `teak init --list-templates`. User templates shadow built-ins of the same
  name.
- **Ollama / air-gapped path** — set `OLLAMA_HOST=http://localhost:11434`
  and `teak --model ollama/llama3` works end-to-end with no cloud
  dependency. Embeddings auto-route to `ollama/nomic-embed-text`. Override
  with `TEAK_EMBEDDING_MODEL=<id>` and (optionally) `TEAK_EMBEDDING_DIM`.

Phase 4 still applies:

- **Anthropic prompt caching** on the Project Brain prefix — full price the
  first call, ~10% input price for the next ~5 minutes. Brain content is
  shipped exactly once per cache window even though every node sees it.
- **Hard token budget** with pre-flight estimation (`litellm.token_counter`
  + `litellm.cost_per_token`) and an auto-downshift to the planner model at
  95% spend. 80%-spend warning fires once per session.
- **Model routing** by task kind: planner / handoff / brain updates use
  `--planner-model` (cheap), the executor uses `--model` (heavy). Override
  per-call still works.
- **Live dashboard** in `teak status`: total tokens/cost, cache hit ratio,
  last session pointer.
- **Benchmark harness** (`teak bench`) for the launch number.

Phases 0–3 still apply.

## Install

Teak is a CLI; install it globally with [pipx](https://pipx.pypa.io) so it
works from any project directory.

```bash
brew install pipx
pipx ensurepath        # one-time PATH setup; open a new terminal afterwards
pipx install /path/to/TeakIDE
```

Verify:

```bash
teak --version
```

> If `teak` isn't found after `pipx install`, your shell hasn't picked up
> `~/.local/bin` yet. Either open a new terminal or run
> `export PATH="$HOME/.local/bin:$PATH"`.

## Configure

Teak reads its API key from the environment via LiteLLM. For Anthropic:

```bash
export ANTHROPIC_API_KEY=sk-ant-api03-...
```

Verify the key + your model access before running Teak:

```bash
curl -s https://api.anthropic.com/v1/messages \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{"model":"claude-haiku-4-5","max_tokens":10,"messages":[{"role":"user","content":"hi"}]}'
```

A response containing `"content":[...]` means the key works and your account
has access to that model. The default model in `src/teak/config.py` is
`anthropic/claude-haiku-4-5`; override with `--model` if your account uses a
different one.

## Run

### One-time: bootstrap the brain

```bash
cd <your-project>
teak init                  # surveys the codebase, drafts brain in ~30s
teak init --template python-cli   # or seed from a built-in starter
teak init --list-templates        # see available starters
teak brain                 # review the drafts
teak brain --edit          # open all four files in $EDITOR
```

The brain lives at `.teak/brain/` (ARCHITECTURE.md, CONVENTIONS.md,
DECISIONS.md, MEMORY.md). Commit it — it's part of the project.

### Coding loop

```bash
cd <your-project>          # must be a git repo with a clean working tree
teak plan "add a /health endpoint that returns 200 ok"
```

What happens:

1. **Session branch.** Teak creates `teak/session-<timestamp>` from current HEAD.
2. **Plan.** The planner emits a short list of steps; each step names target files.
3. **Approve.** Teak shows the plan in the terminal and asks `Approve plan? (a/r)`.
4. **Execute.** For each approved step, the executor reads target files, asks
   the LLM for the new file content, writes it, and commits with
   `teak: <step title>`.
5. **Per-step review.** After each commit, Teak shows the diff and asks
   accept/reject. Reject = `git reset --hard HEAD~1` on the session branch.
6. **Verify (opt-in).** With `--verify` or `--auto-verify`, Teak runs the
   command and re-runs the executor on failure (up to `--max-retries`).
7. **Brain update (if a brain exists).** Teak proposes minimal updates to
   ARCHITECTURE/CONVENTIONS/DECISIONS/MEMORY based on what changed; you
   approve per file and the changes are committed to the session branch.
8. **Handoff.** Teak generates a one-paragraph summary (with pending /
   decisions) and persists it to `.teak/teak.db`. The next `teak plan` run
   auto-prepends it to the planner — pick up where you left off.

Review and merge:

```bash
git log <session-branch>
git diff main..<session-branch>
git checkout main
git merge <session-branch>     # or cherry-pick the commits you want
```

Reject a session entirely by deleting the branch — your working branch is
untouched because every change lives only on the session branch.

## CLI reference (Phase 5)

| Command | Status |
|---|---|
| `teak init [path]` | Working — survey + LLM draft, or `--template <name>` |
| `teak init --list-templates` | Working — built-ins + `~/.teak/templates/*` |
| `teak brain [--edit]` | Working — render or edit brain files |
| `teak index [--force]` | Working — build/refresh the context index |
| `teak status` | Working — brain + index + token dashboard |
| `teak session` | Working — show last handoff |
| `teak bench tasks.json` | Working — token-efficiency benchmark harness |
| `teak plan "<task>" […]` | Working — full visible flow (per-step + verify + handoff) |
| `teak --version` | Working |
| `teak chat` | Stub (future — QuickMode) |

### Context index

`teak plan` automatically bootstraps the Tree-sitter + sqlite-vec index on
first run (and is incremental thereafter — only changed files are re-parsed
and re-embedded). To pre-warm or refresh manually:

```bash
teak index            # build/update; skips files whose hashes match
teak index --force    # re-embed everything (after changing embedder model)
teak status           # files / symbols / call edges / imports counts
```

### Embedder selection

| Setting | Embedder used |
|---|---|
| `TEAK_EMBEDDING_MODEL=<id>` | LiteLLM with that exact model id (with optional `TEAK_EMBEDDING_DIM`) |
| `OLLAMA_HOST` set, no overrides | `ollama/nomic-embed-text` (768-dim) |
| `OPENAI_API_KEY` | `text-embedding-3-small` (1536-dim) |
| `VOYAGE_API_KEY` | `voyage/voyage-3` (1024-dim) |
| _none of the above_ | local hash embedder (256-dim, no network, low quality) |

Switching embedders changes the vector dimension; the index drops the vec
table and rebuilds it on the next `teak index` run.

### Air-gapped / offline workflow

```bash
ollama pull llama3
ollama pull nomic-embed-text
export OLLAMA_HOST=http://localhost:11434

cd <project>
teak init --template python-cli                            # zero LLM calls
teak index                                                  # uses ollama embeddings
teak plan "fix flaky test in tests/test_login.py" \
   --model ollama/llama3 --planner-model ollama/llama3
```

No API keys are read; no traffic leaves the machine. Cache stats stay zero
because Ollama doesn't implement Anthropic-style prompt caching, but the
brain prefix is still authoritative for every node.

### Custom brain templates

Drop a directory under `~/.teak/templates/<name>/` with the four
`ARCHITECTURE.md` / `CONVENTIONS.md` / `DECISIONS.md` / `MEMORY.md` files
plus an optional `template.json` (`{"name": "...", "description": "..."}`).
Use it with `teak init --template <name>`. A user template with the same
name as a built-in shadows the built-in.

Flags on `teak plan`:
- `--model anthropic/<id>` — override the default model.
- `--budget 0.50` — soft per-session budget in USD (tracked but not enforced
  until Phase 4).
- `--no-context` — skip subgraph RAG retrieval. Faster start, no project
  context injected into the planner/executor user messages.
- `--verify "<cmd>"` — run `<cmd>` in the project root after each accepted
  step. On non-zero exit, the executor is re-invoked with the failure tail
  attached, up to `--max-retries` times.
- `--auto-verify` — autodetect a verifier from `pyproject.toml` /
  `package.json` / `Cargo.toml` / `go.mod`. Equivalent to passing the
  detected command via `--verify`.
- `--max-retries N` — verifier retries per step before prompting (default 2).
- `--planner-model anthropic/<id>` — cheap model for planning, summarization
  and brain updates. Defaults to `config.planner_model` (haiku).
- `--auto` — auto-approve plan + every step. Used by `teak bench`; not
  intended for routine human-driven sessions.

### Benchmark

```bash
teak bench bench-tasks.example.json --modes teak,naive --output results.csv
```

The harness:
- Resets each project's working tree to `base_ref` between modes.
- Runs `teak` mode in `--auto` (no human prompts) and records tokens / cost
  / cache hit stats from the session.
- Runs `naive` mode by concatenating every supported source file (up to
  ~200 KB) into a single LLM call and recording its tokens / cost.
- Emits CSV with one row per (task, mode).

Sample task file: `bench-tasks.example.json`. Replace `project_path` with
absolute paths to clean git checkouts before running.

## Troubleshooting

**`zsh: command not found: teak`** — `pipx` installs to `~/.local/bin`, which
isn't always on PATH. Either open a new terminal after `pipx ensurepath`, or
add `export PATH="$HOME/.local/bin:$PATH"` to your shell config.

**`AuthenticationError: invalid x-api-key`** — the key isn't valid.
- Anthropic keys look like `sk-ant-api03-<long-string>`. Anything else won't
  work.
- If you rotated a leaked key, the old key is permanently revoked — make sure
  you're exporting the *new* one (`echo $ANTHROPIC_API_KEY` to confirm).

**`not_found_error: model: <id>`** — your account doesn't have access to that
model. Run the curl test above against the model you actually want, or pass
`--model anthropic/<id-that-works>` to `teak plan`.

**`DirtyWorkingTree`** — Teak refuses to start with uncommitted changes
(otherwise rollback semantics get confusing). Commit or stash first.

**`ModuleNotFoundError: No module named 'teak'` in a venv** — known to happen
when the venv was created from a conda-supplied Python; conda's `site.py`
doesn't always process editable-install `.pth` files at startup. Use `pipx`
instead of a manual venv, or recreate the venv with a non-conda Python (e.g.
`pyenv` or python.org).

## Updating Teak

When the source in `src/teak/` changes:

```bash
pipx reinstall teak
```

This is *not* an editable install — code edits don't take effect until you
reinstall. (An editable install would be nicer for development but conflicts
with the conda-Python issue above; we'll revisit once the toolchain settles.)

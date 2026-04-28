# Using Teak (Phase 0)

Phase 0 implements the minimum coding loop: **plan → approve → execute**. The
Project Brain, Tree-sitter RAG, prompt caching, and hard budgets land in later
phases (see `README.md` §7). What works today is `teak plan "<task>"` against
any git repo.

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
5. **Summary.** Teak prints token usage, cost, and the session branch name.

Review and merge:

```bash
git log <session-branch>
git diff main..<session-branch>
git checkout main
git merge <session-branch>     # or cherry-pick the commits you want
```

Reject a session entirely by deleting the branch — your working branch is
untouched because every change lives only on the session branch.

## CLI reference (Phase 0)

| Command | Status |
|---|---|
| `teak plan "<task>"` | Working — full plan/approve/execute loop |
| `teak --version` | Working |
| `teak chat` | Stub (Phase 3 — QuickMode) |
| `teak init` | Stub (Phase 1 — Brain bootstrap) |
| `teak brain` | Stub (Phase 1) |
| `teak session` | Stub (Phase 3 — handoff summary) |
| `teak status` | Stub (Phase 4 — token dashboard) |

Flags on `teak plan`:
- `--model anthropic/<id>` — override the default model.
- `--budget 0.50` — soft per-session budget in USD (tracked but not enforced
  until Phase 4).

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

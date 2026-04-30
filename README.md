# Teak – Project Specification & Collaboration Guide
**Version**: 2.1 (April 30, 2026)
**Purpose**: Single source of truth for all teammates (developers, designers, testers).

## 1. Project Vision

Teak is a lightweight AI-native coding companion that turns the AI into a **true disciplined teammate** instead of a chatty intern.

It solves two core problems that still exist in 2026 tools (Cursor, Aider, Claude Code, etc.):
1. **Token waste** – most sessions still burn far more tokens than necessary.
2. **The re-explaining tax** – the #1 pain point: constantly re-explaining architecture, decisions, and conventions across sessions and projects.

The result feels **continuous, predictable, review-first, and cost-transparent** — like pair-programming with someone who never forgets anything and respects your time and wallet.

**Primary target user:** Freelancers and contractors who work across multiple client codebases. They feel the re-explaining tax hardest — jumping between projects daily, each with different conventions, stack decisions, and history. No current tool is built for this workflow.

The name "Teak" comes from its strong, durable tree-like architecture (Tree-sitter knowledge graph + persistent brain), symbolizing a solid, long-lasting coding partner.

## 2. Key Differentiators (Why We Exist)

| Area | Cursor / Aider / Claude Code | Teak (our edge) |
|---|---|---|
| Persistent Architecture Memory | Static rules + community hacks | Bidirectional **Project Brain** that AI actively maintains |
| Multi-project workflow | Designed for one codebase | Per-project brain — switch projects, context switches instantly |
| Token Efficiency | Good indexing | Subgraph RAG + prompt caching + hard budgets + live dashboard |
| Collaboration Flow | Optional plans / chat-heavy | Enforced **Visible Plan → Approve → Incremental Execute** |
| Session Continuity | Partial | Zero re-explaining tax across days and projects |
| Form Factor | Full IDE fork or pure terminal | CLI-first with optional split-pane desktop shell |

## 3. Product Form Factor

**CLI-first.** Install with `pip install teak` or `brew install teak`. No GUI required to get value.

```
teak init          # bootstrap brain for this project
teak chat          # start a session
teak plan "task"   # generate + approve a plan before executing
teak brain         # view/edit brain files interactively
teak session       # show session summary / handoff
teak status        # token usage, budget remaining, brain health
```

The terminal UI uses `rich` for formatted output and `textual` for interactive approve/reject flows. Runs fully self-contained — no separate server process.

Works with **any** editor (VS Code, Neovim, Zed, etc.). Teak watches the project folder and applies changes via git branches and patches.

**Phase 6 desktop shell.** The optional Tauri app lives in `desktop/`. It keeps the CLI as the source of truth while giving Teak a native split-pane workflow:

- Left pane: chat-style task composer.
- Right pane: embedded terminal running in the selected project.
- Draggable divider between panes.
- Review mode sends `teak plan "<task>"` into the terminal.
- Auto mode sends `teak plan "<task>" --auto`.

Run locally:

```bash
cd desktop
npm install
npm run tauri
```

Tauri requires Rust/Cargo. On macOS with Homebrew:

```bash
brew install rust
```

## 4. Core Pillars & Features (MVP)

### Pillar 1 – Project Brain (kills the re-explaining tax)

Git-tracked folder per project: `.teak/brain/`

Files (human-readable Markdown):
- `ARCHITECTURE.md` — system design, major components, data flow
- `CONVENTIONS.md` — naming, patterns, what to avoid
- `DECISIONS.md` — why things are the way they are (ADRs)
- `MEMORY.md` — cross-session notes, open questions, context

Behavior:
- On `teak init`: **Brain Bootstrapper** analyzes the existing codebase with Tree-sitter + LLM and generates draft brain files in ~30 seconds. User reviews and approves. No cold-start problem.
- On every session start: agent auto-reads brain files (prompt-cached — pays full price once, ~10% on subsequent calls).
- After meaningful changes: agent proposes concise brain updates; user approves/rejects per change.
- **Convention Violation Detection**: when a proposed change conflicts with documented conventions, Teak flags it before executing. (e.g., brain says "use repository pattern" → agent proposes direct DB call → flagged.)
- **Brain Templates**: community-shareable starter brains for common stacks (Django REST, Next.js monorepo, Go microservice, etc.). Reduces cold start on new projects to seconds.

### Pillar 2 – Context Brain (token savings)

- **Tree-sitter** (lightweight syntax parsing — not full compiler AST) builds a knowledge graph: functions, classes, imports, call dependencies.
- **Incremental indexing**: `watchdog` detects file changes; only re-indexes changed files. File hashes stored in SQLite to detect staleness. Runs in background, never blocks the UI.
- **Subgraph RAG**: only the relevant code subgraph is sent to the LLM — not the whole repo.
- **Prompt caching**: brain files are structured as a cached system prompt prefix. Free token savings on every call after the first in a session.
- **Hard token budgets**: set a per-session budget (e.g., `--budget $0.50`). Teak automatically routes to cheaper models, compresses context, or warns before breach. Not just a dashboard — an enforced limit.
- **Live token dashboard**: `teak status` shows cost so far, budget remaining, estimated cost of next action.
- **Model routing**: cheap model for planning and summarization; heavy model only for code generation.

### Pillar 3 – Visible Flow (smooth collaboration)

Default workflow for any non-trivial task:
1. User describes task (`teak plan "add OAuth login"`).
2. Agent outputs an editable step-by-step plan.
3. User reviews, edits, and approves (interactive `textual` prompt).
4. Agent implements **one file/logical change at a time** with inline diff + explanation.
5. User accepts or rejects each block. Rejection = `git reset HEAD~1` on the session branch.
6. Tests run automatically after each step; failures loop back to the executor.
7. After session: agent proposes brain file updates for approval.

**Session Handoff**: at the end of every session, Teak generates a one-paragraph summary (what was done, what's pending, decisions made). This auto-prepends to the next session as context — zero re-explaining tax even across days.

Additional modes: quick inline chat, full agentic (no approval gates).

## 5. Technical Architecture

### Stack

| Layer | Technology | Notes |
|---|---|---|
| CLI + TUI | Python 3.12, `typer`, `rich`, `textual` | Self-contained, no separate server |
| Desktop shell | Tauri 2, Vite, TypeScript, xterm, `portable-pty` | Optional split-pane GUI over the existing CLI |
| Orchestration | LangGraph | State machine for agent loop |
| LLM routing | LiteLLM | OpenAI, Anthropic, Grok, Ollama (local/offline) |
| Prompt caching | Anthropic cache-control headers | Brain files cached per session |
| Parsing | `tree-sitter` + language grammars | Python, TS/JS, Rust, Go at launch |
| File watching | `watchdog` | Incremental re-indexing only |
| Storage | SQLite + `sqlite-vec` | Vectors, history, file hashes — one `.db` file per project |
| File editing | `python-patch`, `difflib`, direct writes | No Codex CLI dependency |
| Git integration | `GitPython` | Branching, commits, reset for rollback |

### LangGraph Agent Graph

```
Router
  ├── QuickMode (inline chat, no plan)
  └── PlanMode
        Planner → HumanApproval ⟲ (edit/approve/reject)
                       ↓
                   Executor (one file/change at a time → git commit)
                       ↓
                   Verifier (run tests/linter → loop back if failing)
                       ↓
                   BrainUpdater (propose brain file updates → human approval)
```

- **Router**: classifies task complexity; trivial tasks skip straight to QuickMode.
- **Planner**: reads brain files (cached), generates structured step-by-step plan.
- **HumanApproval**: LangGraph interrupt — waits for user to approve, edit, or reject the plan.
- **Executor**: applies one logical change, commits to `teak/session-{timestamp}` branch.
- **Verifier**: runs project tests/linter; feeds failure back to Executor for self-correction.
- **BrainUpdater**: after session, proposes minimal updates to brain files.

### Storage Layout

```
.teak/
  brain/
    ARCHITECTURE.md
    CONVENTIONS.md
    DECISIONS.md
    MEMORY.md
  teak.db          # SQLite: vectors, history, file hashes, session log
  templates/       # community brain templates
```

### Rollback Model

Every execution step is a git commit on a dedicated session branch. Rejecting a step = `git reset HEAD~1`. Approving the full session = user merges or cherry-picks onto their working branch. Full audit trail, no proprietary undo state.

### Offline / Air-Gapped Support

LiteLLM + Ollama path is fully supported. `teak --model ollama/llama3` works with no cloud dependency. All storage is local. This is a first-class path, not an afterthought.

## 6. Open Source Inspiration

- **OpenAI Symphony** → agent execution patterns: isolated runs, structured verification steps, rollback on failure. Borrow the patterns and verification design, not the code.
- **Aider** → reference implementation for CLI-first AI coding tools; study its file editing and git workflows.
- **OpenAI Codex CLI** → reference for sandboxed shell execution patterns (used as inspiration; we implement our own in Python via `GitPython` + `difflib`).

## 7. Phased Development Plan

(Assuming 20–40 hrs/week + heavy use of AI coding agents)

| Phase | Focus | Duration | Deliverable |
|---|---|---|---|
| 1 | Foundation + Project Brain + Brain Bootstrapper | 1–1.5 weeks | `teak init`, `teak brain`, bidirectional brain loop |
| 2 | Context Brain: Tree-sitter + SQLite-vec RAG + incremental indexing | 2–3 weeks | Token-efficient retrieval, background indexing |
| 3 | Visible Flow: LangGraph graph + Session Handoff | 1.5–2 weeks | Full Plan → Approve → Execute loop, handoff summary |
| 4 | Token efficiency: prompt caching + hard budgets + model routing | 1 week | Measurable token reduction with benchmark |
| 5 | Polish: Convention Violation Detection + Brain Templates + Ollama path | 1–2 weeks | Publishable CLI MVP |
| 6 | Tauri desktop UI | TBD | Validated split-pane shell: chat left, terminal right |

**Total CLI MVP**: 6.5–9.5 weeks.

Publish a **token efficiency benchmark** at the end of Phase 4: measure tokens used with and without Teak on 10 real-world tasks. If the reduction is ≥ 40%, that's the launch blog post.

## 8. Go-To-Market

- **Build in public from day one.** Post the spec, post weekly progress, share the benchmark results.
- **Launch on HN/Reddit with the freelancer angle**: "The AI coding tool built for developers who work on more than one codebase."
- **Brain Templates as a community asset**: a GitHub-hosted collection of starter brains that drives ongoing traffic and contributions.
- **Monetization (post-OSS traction)**: hosted brain sync across machines, team brain sharing, priority support. Core tool stays free and open source.

## 9. Non-Goals (MVP)

- Full IDE replacement; the desktop shell remains a thin optional layer over the CLI.
- Cloud hosting or team collaboration features.
- Advanced multi-agent orchestration.
- Support for every language at launch (Python, TS/JS, Rust, Go only).
- Full IDE replacement.

## 10. Next Immediate Steps

1. Keep the CLI workflow stable; it remains the authoritative execution path.
2. Harden the Phase 6 desktop shell around the split-pane chat + terminal loop.
3. Refactor approval/review gates into programmatic interrupts if the desktop UI should own approvals directly instead of delegating to the terminal.
4. Package the Tauri app once the desktop workflow has been exercised across real projects.

**Let's build the tool that finally makes AI collaboration feel natural — for every codebase you work on.**

April 30, 2026

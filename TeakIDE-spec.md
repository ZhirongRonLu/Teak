# Teak – Project Specification & Collaboration Guide
**Version**: 1.0 (April 27, 2026)  
**Purpose**: This document gives every teammate (developers, designers, testers) a single source of truth so we can move fast and stay aligned.

## 1. Project Vision
Teak is a lightweight AI-native coding companion that turns the AI into a **true disciplined teammate** instead of a chatty intern.

It solves two core problems that still exist in 2026 tools (Cursor, Aider, Claude Code, etc.):
1. **Token waste** – most sessions still burn far more tokens than necessary.
2. **“Weird” disjointed collaboration** – especially the #1 pain point: constantly re-explaining architecture, decisions, conventions, and “why” across sessions.

The result is an experience that finally feels **continuous, predictable, review-first, and cost-transparent** — like pair-programming with someone who never forgets anything and respects your time and wallet.

The name “Teak” comes from its strong, durable tree-like architecture (Tree-sitter knowledge graph + persistent brain), symbolizing a solid, long-lasting coding partner.

## 2. Key Differentiators (Why We Exist)

| Area                        | Cursor / Aider / Claude Code                  | Teak (our edge)                                              |
|-----------------------------|-----------------------------------------------|--------------------------------------------------------------|
| Persistent Architecture Memory | Static rules + community hacks                | Bidirectional **Project Brain** that AI actively maintains   |
| Token Efficiency            | Good indexing                                 | Context Brain + live dashboard + subgraph RAG + auto-optimization |
| Collaboration Flow          | Optional plans / chat-heavy                   | Enforced **Visible Plan → Approve → Incremental Execute**    |
| Session Continuity          | Partial                                       | Zero re-explaining tax across days/tools                    |
| Form Factor                 | Full IDE fork or pure terminal                | Minimal Tauri app (works alongside any editor)               |

## 3. Product Form Factor (MVP)
- **Desktop app** built with **Tauri 2** (Rust backend + lightweight frontend — not Electron).
- Single clean window with resizable split:
  - Left/main pane (70%): Chat + Plan canvas (tabbed inside the pane).
  - Right pane (30%): Always-visible terminal (xterm.js).
- Top-level tabs across the whole window:
  1. Chat + Plan
  2. Project Brain (editable Markdown files)
  3. Knowledge Graph (visual)
  4. Token Dashboard
  5. Code Explorer (embedded Monaco editor + file tree)
- Works with **any** editor the user already loves (VS Code, Neovim, Zed, etc.). We watch the project folder and apply changes via git or direct patches.

## 4. Core Pillars & Features (MVP)

### Pillar 1 – Project Brain (kills re-explaining architecture)
- Git-tracked folder: `.teak/brain/`
- Files (human-readable Markdown):
  - `ARCHITECTURE.md`
  - `CONVENTIONS.md`
  - `DECISIONS.md`
  - `MEMORY.md`
- Behavior:
  - Agent auto-reads relevant parts on every session/start.
  - After meaningful changes, agent proposes concise updates (you approve/reject with one click).
  - You can edit any file anytime; agent instantly respects it.
  - Agent always references the brain explicitly in plans.

### Pillar 2 – Context Brain (token savings)
- Tree-sitter (lightweight syntax parsing — **not** full compiler AST).
- Builds simple knowledge graph (functions, classes, imports, call dependencies).
- Subgraph RAG retrieval → only send relevant code chunks.
- Live Token Dashboard (shows cost **before** every action + one-click “Optimize”).
- Automatic prompt compression, history summarization, model routing (cheap model for planning, heavy only for generation).

### Pillar 3 – Visible Flow (smooth collaboration)
Default workflow for any non-trivial task:
1. User describes task.
2. Agent outputs editable step-by-step plan in Plan tab.
3. User reviews/edits/approves.
4. Agent implements **one file/logical change at a time** with inline diff + explanation + auto-tests.
5. User accepts/rejects each block.
6. Changes auto-committed to clean git branch (optional).

Additional modes: Quick autocomplete, inline chat, full agentic.

## 5. Technical Architecture (Backend-First)
- **Language**: Python 3.12 + FastAPI (recommended) or TypeScript/Node.
- **Orchestration**: LangGraph (state machine for Plan → Approve → Execute).
- **LLM Layer**: LiteLLM (multi-provider: OpenAI, Anthropic, Grok, local Ollama).
- **Parsing**: Tree-sitter + grammars for major languages.
- **Vector DB**: Chroma or LanceDB (local-first).
- **Execution**: Reuse code from **OpenAI Codex CLI** (Rust) for file editing, patching, git integration.
- **Design patterns**: Borrow Symphony’s SPEC.md for isolated runs and verification.
- **Storage**: All brains and indexes are local by default; git-tracked where possible.

## 6. Phased Development Plan & Realistic Timeline
(Assuming 20–40 hrs/week dedicated work + heavy use of Claude Code / Cursor agents)

| Phase | Focus                                      | Duration     | Deliverable |
|-------|--------------------------------------------|--------------|-------------|
| 1     | Foundation + Project Brain                 | 1–1.5 weeks | Working bidirectional brain + basic agent loop |
| 2     | Context Brain (Tree-sitter + subgraph RAG) | 2–3 weeks   | Token-efficient retrieval + dashboard |
| 3     | Visible Flow (LangGraph state machine)     | 1–1.5 weeks | Full Plan → Approve → Execute loop |
| 4     | Polish + Integration + Codex reuse         | 1–2 weeks   | Git, tests, token optimization, CLI version |

**Total backend MVP**: 5–8 weeks (4–6 weeks if we reuse Codex CLI heavily).  
Frontend (Tauri UI) is Phase 5 and can start in parallel once backend API is stable.

## 7. Open Source Reuse (encouraged)
- **OpenAI Codex CLI** (Rust) → execution engine, diff/patch logic, git tools.
- **OpenAI Symphony** → SPEC.md and verification patterns.
- Continue.dev / Aider pieces where they overlap (but we will not fork the whole thing).

## 8. Non-Goals (MVP)
- Full IDE replacement (we embed Monaco only for quick edits).
- Cloud hosting / team collaboration features.
- Advanced multi-agent orchestration.
- Support for every language on day one (start with Python, TS/JS, Rust, Go).

## 10. Next Immediate Steps
1. Create GitHub repo and copy this spec into `TEAK-SPEC.md` + `README.md`.
2. Decide backend language (Python recommended) and set up skeleton.
3. Start **Phase 1** (Project Brain).

**Let’s build the tool that finally makes AI collaboration feel natural.**

April 27, 2026

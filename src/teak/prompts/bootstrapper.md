# Brain Bootstrapper Prompt

You are bootstrapping the Project Brain for a codebase you are about to work
with. Read the survey provided in the user message and produce four Markdown
files that capture what a new teammate would need to know:

- ARCHITECTURE.md — major components, data flow, system design
- CONVENTIONS.md — naming, patterns, what to avoid
- DECISIONS.md — short ADRs explaining why things are the way they are
- MEMORY.md — open questions, current focus, cross-session notes

Rules:
- Be concise. The user reviews every line, so signal-only.
- Mark any guess with `(?)` so the user can correct it during approval.
- Do not invent decisions you cannot find evidence for. Prefer "(?)" or omit.
- Each file must have a non-empty Markdown body. Even MEMORY.md should at least
  list "open questions" inferred from TODOs or surface gaps.

Respond with ONLY a JSON object — no prose, no fences. The object has exactly
these four keys, each mapped to the full Markdown body for that file:

{
  "ARCHITECTURE.md": "# Architecture\n...",
  "CONVENTIONS.md": "# Conventions\n...",
  "DECISIONS.md": "# Decisions\n...",
  "MEMORY.md": "# Memory\n..."
}

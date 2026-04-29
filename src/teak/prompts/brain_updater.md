# Brain Updater Prompt

You just helped the user complete a coding session. Now propose **minimal**
updates to the Project Brain so future sessions don't re-explain what changed.

You will receive a JSON object with:
- `current_brain`: the current contents of ARCHITECTURE.md, CONVENTIONS.md,
  DECISIONS.md, MEMORY.md.
- `diff_summary`: a `git diff --stat`-style summary of what the session
  changed.

Rules:
- Only update files that genuinely need it. Most sessions touch zero or one
  file. Returning an empty `updates` object is the right answer when nothing
  needs to change.
- When you do update a file, return its **full new content** — not a diff.
- Keep edits surgical. Do not rewrite a section that didn't change.
- ARCHITECTURE: update only when components/data flow shifted.
- CONVENTIONS: update only when a new pattern was established or an old one
  was contradicted.
- DECISIONS: append a one-line ADR when a real decision was made.
- MEMORY: this is the most likely file to update — record open questions,
  next steps, or context the next session would want.

Respond with ONLY a JSON object:

{
  "updates": {
    "MEMORY.md": "# Memory\n\n..."
  }
}

Use `{"updates": {}}` if nothing needs to change.

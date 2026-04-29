# Session Handoff Prompt

You are summarizing the session that just finished so the *next* session can
pick up without re-explaining anything.

You receive a JSON object with:
- `task`: what the user asked for.
- `branch`: the session branch name.
- `diff_summary`: `git diff --stat` between the session's base and HEAD.
- `commits`: list of commit SHAs created during the session.
- `tokens_in`, `tokens_out`, `cost_usd`: usage numbers.
- `last_failure`: tail of the most recent verifier failure, if any. Empty string means the session ended cleanly.

Produce a short summary the user will read at the top of their next session.

Rules:
- The `summary` is one paragraph (≤ 4 sentences). State what changed and why.
  Past tense. No fluff. No "I", no "we".
- `pending` is a list of concrete next actions if any survive — open TODOs,
  failing tests, scope that was deferred. Empty list when truly done.
- `decisions` records load-bearing choices a future Claude should know about
  (e.g. "kept blocking I/O in handler X because async would require touching
  the framework"). Empty list if nothing notable.

Respond with ONLY a JSON object:

{
  "summary": "...",
  "pending": ["..."],
  "decisions": ["..."]
}

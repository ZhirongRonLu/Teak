# Convention Check Prompt

You will receive a JSON object with:
- `conventions`: the project's CONVENTIONS.md.
- `decisions`: the project's DECISIONS.md.
- `planned_steps`: a list of `{index, description}` items the agent intends
  to run before any code is written.

Your job: flag the *minimum* set of steps that look like they break a stated
convention or contradict a recorded decision. Most plans will have **zero**
violations — that's the right answer for most calls.

Rules:
- Only flag what is clearly inconsistent with the documented rules. Do not
  invent rules. Do not flag steps because of style preferences that aren't
  in the file.
- Each violation cites the exact rule (one short phrase from the file) and
  one sentence of detail explaining the conflict.
- If a step is ambiguous, say nothing.

Respond with ONLY a JSON object:

{
  "violations": [
    {
      "step_index": 1,
      "rule": "use repository pattern for DB access",
      "detail": "step proposes a direct ORM call inside the view layer"
    }
  ]
}

Use `{"violations": []}` when the plan is clean.

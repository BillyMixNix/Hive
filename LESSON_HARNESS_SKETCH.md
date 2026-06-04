# Seed→Reuse Harness — sketch for measuring cross-case learning

_Goal: replace the deterministic A/B (which cannot move) with a harness that can actually show
whether lesson memory improves Hive over time. This measures the one claim the project is built
on: "each run begins warmer than the last."_

## Why the current A/B can't work (recap)

`benchmark_harness.run_case()` does two things that make lessons inert:

1. **Fresh empty `lessons.jsonl` per case** (`_create_session()` makes a new temp dir each call), so
   nothing accumulates across cases.
2. **`patch("coder.ask_hive", return_value=case["coder_response"])`** — the model output is a
   constant that ignores any guidance injected into the prompt.

To measure learning we must reverse both: **one shared lesson store** across an ordered sequence,
and a coder whose output **reacts** to whether lesson guidance is present.

## Design

### A. Share one lesson store across the sequence
Create the session **once**, run an ordered list of cases against it, and do **not** wipe the
lesson store between cases. Sketch:

```python
def run_sequence(self, cases, lessons_enabled=True):
    session = self._create_session(lessons_enabled=lessons_enabled)  # ONE store for the run
    results = []
    try:
        for case in cases:                # ordered: seed(s) first, reuse case last
            results.append(self._run_one(session, case))
    finally:
        self._cleanup_session(session)
    return results
```

`_run_one` is `run_case`'s body minus the `_create_session` call — so the coder, planner, and
crucially `coder.lesson_memory` persist. Lessons recorded while handling the seed cases are now
visible (via `find_relevant_lessons` / `get_retry_lessons`) when the reuse case runs.

### B. Make the coder respond to guidance
The mock must return a *bad* patch on a cold attempt and a *good* patch once the retry prompt
contains lesson guidance. Two options, weakest→strongest:

**Option 1 — guidance-sensitive mock (fast, no model, deterministic, CI-safe).**
Key the fake response on whether the composed prompt contains the lesson text. The real injection
path runs through `coder._compose_retry_lesson_text(...)` → `format_lessons_for_prompt(...)`, so a
marker substring from a recorded lesson will appear in the retry prompt only when lessons are live.

```python
def guidance_sensitive_response(prompt, *args, **kwargs):
    # 'GUIDANCE_MARKER' is a token the seed lesson's retry_instruction carries
    if "GUIDANCE_MARKER" in prompt:
        return case["good_patch"]      # well-formed, passes the gate
    return case["bad_patch"]           # e.g. missing_diff_headers -> recorded as a lesson
patch("coder.ask_hive", side_effect=guidance_sensitive_response)
```

This proves the *plumbing*: lessons are retrieved, injected, and change behavior. It does not prove
the LLM itself benefits — but it's the right first milestone and belongs in CI.

**Option 2 — real Ollama (slow, non-deterministic, the real claim).**
Drop the mock, point at the live `qwen2.5-coder:7b`, run each case N times, average. This is the
only configuration that proves lessons help a *real* model. Keep it out of CI (needs the endpoint),
run it for the report. Use `--n 5` and report mean ± noise band like `validation/ab_run.py` already
does.

### C. Case set: a seed→reuse pair, not 40 independent cases
The unit of measurement is a **pair**, not a case:

- **Seed case(s):** designed to fail on a cold attempt with a *specific, recordable* failure code
  (e.g. `missing_diff_headers`, `mixed_scope_patch`). Hive records a lesson.
- **Reuse case:** *similar but not identical* (same failure family, different file/symbol), so the
  win must come from a **generalized** lesson, not exact-match memorization. `HiveLessonMemory`
  already distinguishes `lesson_level == "generalized"` vs `"exact"` and has a promotion path —
  exercise it: the reuse case should only benefit from a promoted/generalized lesson.

Build 5–10 such pairs across the existing bands (`comment_docstring`, `narrow_logic_edits`,
`architectural_in_place_rewrites`, `route_flow_state`).

### D. Metrics that can actually move
Compare the **reuse case** under lessons-on vs lessons-off (with the shared store seeded in the
on-arm only):

| Metric | lessons OFF | lessons ON | learning signal |
|---|---|---|---|
| first-attempt success rate | low | higher | primary |
| retries to success (`retry_count`) | high | lower | primary |
| `success_after_use` on the seeded lesson | 0 | ≥1 | proves reuse, not luck |
| `guidance_changed` flag | n/a | true | proves injection fired |
| true regressions | 0 | 0 | safety guard (must stay 0) |

`run_case` already returns `retry_count` and `retry_succeeded`; `record_lesson_outcome` /
`record_lesson_use` already track `success_after_use` and `guidance_changed`. So most of the
instrumentation exists — it just isn't wired into a sequence that lets it fire.

### E. Honest reporting
- If first-attempt rate rises and `retry_count` falls with regressions still 0 → **the thesis holds**,
  and you have the number to put in the ReadMe.
- If there's no movement even with a shared store and a guidance-sensitive coder → the lesson
  retrieval/injection path has a real bug (check `find_relevant_lessons` matching and promotion
  thresholds). That's a more important finding than a green benchmark.

## Suggested build order
1. Add `run_sequence()` + `_run_one()` (refactor of `run_case`) — shared store, no per-case wipe.
2. Add 1 seed→reuse pair and the Option-1 guidance-sensitive mock; assert `retry_count` drops and
   `success_after_use >= 1`. Land this as a unit test in CI.
3. Expand to 5–10 pairs across bands; add the lessons-off control arm; emit a delta report next to
   `HIVE_RELIABILITY_REPORT.md`.
4. Add the Option-2 real-Ollama runner (`--n 5`, out of CI) for the headline number.

## Validity checklist (so the result survives scrutiny)
- Reuse case must differ from seed (no exact-match shortcut) — force reliance on a generalized lesson.
- Lessons-off arm must use a genuinely empty store (the current `lessons_enabled=False` path is fine).
- Run real-Ollama arm N≥5 and report the noise band; a single run proves nothing.
- Regressions must stay 0 in both arms — a learning gain that introduces regressions is not a win.

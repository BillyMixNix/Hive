# Lesson-reuse harness + live efficacy study

Against branch `claude/phases-1-3-4Jshu`. Two layers:

1. **Plumbing proof (CI, deterministic)** — shared-store sequence runner + seed→reuse test that
   makes cross-case learning measurable. Described below.
2. **Hypothesis proof (live model, runs on your machine)** — a statistical study that tests whether
   lessons actually make a real model better at new tasks. See **`LESSON_STUDY.md`** and
   `validation/lesson_study*.py`. Start there for the "big enough test".

The deterministic injection mechanic for all 8 study pairs is already verified here; only the
live solve-rate measurement needs your Ollama. Read LESSON_STUDY.md's "reactive effect" section
before running — the metric is retries-to-solve, not first-attempt success, for a real reason.

---

## Layer 1 — shared-store sequence runner (this section)

Implements step 1 of `LESSON_HARNESS_SKETCH.md`:
a shared-store sequence runner plus a seed→reuse CI test that makes cross-case learning
**measurable** — the thing the original A/B benchmark structurally could not show.

## What changed

**`benchmark_harness.py`**
- Refactored `run_case()` into a thin wrapper around a new `_run_one(session, case)` that runs a
  case against an *existing* session (no per-case store creation/teardown).
- Added `run_sequence(cases, lessons_enabled=True)` — runs an ordered list of cases against **one
  shared session/lesson store**, so a lesson recorded on an earlier case is visible to later ones.
- `_run_one` now accepts a **callable** `coder_response`, so a case's coder output can react to
  whether lesson guidance is present in the prompt (needed to observe a behavior change without a
  live model).

**`coder.py`** (real bug fix)
- The harness set `coder._lessons_enabled` but the coder **never read it** — so the "lessons OFF"
  arm never actually disabled lessons. Added `self._lessons_enabled = True` default and gated the
  two lesson-fetch chokepoints (`_get_retry_lessons`, `_get_pilot_guardrails`) to return nothing
  when it's False. This makes a genuine lessons-off baseline possible.

**`tests/test_lesson_reuse_sequence.py`** (new)
- Seed case fails with `missing_diff_headers` (records a lesson). Reuse case (same family) uses a
  guidance-sensitive coder that returns a good patch only when the seeded lesson reaches its prompt.
- Three assertions: lessons ON → reuse succeeds first try (0 retries); lessons OFF → no guidance on
  first attempt; ON beats OFF on retry count.

## Measured signal (identical inputs, mocked coder — deterministic, CI-safe)

| | seed | reuse final | reuse retries | first attempt saw guidance |
|---|---|---|---|---|
| lessons **ON**  | blocked | proposed | **0** | yes |
| lessons **OFF** | blocked | proposed | **1** | no |

The lesson removes one failed attempt. That's the payoff, expressed as a retry-count delta the old
40/40-vs-40/40 benchmark could never produce.

## Apply / run

```bash
git checkout claude/phases-1-3-4Jshu
git apply hive_lesson_reuse_patch/lesson_reuse_harness.patch
python -m pytest tests/test_lesson_reuse_sequence.py -q
```

(Copies of the full modified `benchmark_harness.py`, `coder.py`, and the new test are in this
folder too, if you prefer to diff/drop them in manually.)

## Caveats / honest scope
- This is **Option 1** from the sketch: a deterministic mock that proves the *plumbing* — lessons
  are recorded, retrieved, injected into a later case's prompt, and change behavior. It does **not**
  prove a real LLM benefits; that's Option 2 (live Ollama, N≥5), still to do.
- Seed and reuse share the same file/symbol (exact-match retrieval). The stronger generalization
  test — reuse on a *different* file forcing a promoted/generalized lesson — is the next step.
- Verified: existing harness tests still pass (`test_reliability_benchmark_harness` etc.), so the
  `run_pack`/`run_pack_ab` consumers are unaffected by the refactor.

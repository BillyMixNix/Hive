# Lesson-efficacy study — the "big enough test to prove the hypothesis"

This is the experiment that actually tests Hive's central claim:

> Accumulated failure lessons make Hive better at **new** tasks.

It runs the **live** coder (Ollama / `qwen2.5-coder:7b`), so the result reflects a
real model — not a mock. You run it on your machine; it cannot run in the sandbox
the rest of this review was built in.

## Files

- `validation/lesson_study.py` — the runner: seeding, live A/B, statistics, preflight, report.
- `validation/lesson_study_cases.py` — 8 generalization pairs (2 per band).
- depends on the live-coder mode added to `benchmark_harness.py` (`_run_one(..., live_coder=True)`).

## The one thing you must understand first: the effect is **reactive**

I verified this against the code, not by assumption:

- On a task's **first** attempt, `failure_code` is `None`, so
  `LessonMemory.get_retry_lessons` skips `find_relevant_lessons`
  (`HiveLessonMemory.py` ~line 510) and only `get_recent_lessons(file=...)` runs —
  which filters by **exact file**.
- A cross-file **generalized** lesson (`file=None`) is therefore **never** surfaced
  on attempt 1. It is injected only on attempt **2+**, once the task has failed once
  and produced a `failure_code` that **matches** the lesson's family.

Consequences that shape the whole study:

1. **The metric is retries-to-solve / solve-rate-within-budget, not first-attempt
   success.** Measuring first-attempt success would show nothing and misframe the
   mechanism. Same-file *exact* lessons do help on attempt 1; cross-file
   *generalized* lessons help by cutting retries. This study targets the harder,
   more meaningful cross-file case.
2. **The lesson only helps when the new task fails in the lesson's family.** Every
   seeded lesson here is the `missing_diff_headers` family ("emit a valid unified
   diff"), because that failure is the most reliably triggered and — verified
   deterministically — injects across all 8 file pairs. The hypothesis under test
   is precisely: *given a task that would otherwise fail with a malformed diff, does
   possessing a generalized "emit a valid diff" lesson cut the retries needed to
   solve it?*

## Design

For each of 8 pairs (seed file ≠ reuse file, spanning all 4 bands):

- **Lessons ON arm:** seed a trusted *generalized* lesson (`file=None`) into the
  store, then run the reuse task live, N times.
- **Lessons OFF arm:** empty store (the real `_lessons_enabled=False` path — see the
  bug fix in `coder.py`), run the same reuse task live, N times.

We pool retries and solve flags across pairs and report:

- mean retries OFF vs ON, and the reduction (OFF − ON) with a **bootstrap 95% CI**;
- **Mann-Whitney U** p-value on the retry distributions;
- solve-rate OFF vs ON with a **two-proportion z-test**.

**Verdict = "lessons help" only if the retry-reduction CI excludes 0** (or solve-rate
lift is significant). A null result with good headroom is itself a real finding
(the lesson loop isn't transferring) — report it honestly rather than burying it.

## Why seeded (not organically grown) lessons

The store is seeded with a directly-crafted *trusted generalized* lesson. This
isolates the variable to **presence vs absence** of a relevant lesson — the cleanest
test of *transfer*. It deliberately does **not** test the organic promotion
threshold (how many failures it takes to mint a generalized lesson); that's a
separate experiment. Stated as a caveat in the output.

## How to run

```bash
# 0) start Ollama with the model in hive_llm.DEFAULT_MODEL (qwen2.5-coder:7b)

# 1) PREFLIGHT — mandatory. Small N. Confirms two things per pair:
#    - injection FIRES (seeded lesson reaches the reuse prompt across files)
#    - HEADROOM exists (OFF-arm solve rate strictly between 0.0 and 1.0)
python -m validation.lesson_study --preflight --n 4

# 2) FULL STUDY — the proof. Expect this to take a while (8 pairs x 2 arms x N live runs).
python -m validation.lesson_study --n 20 --budget 3 --out results/lesson_study.json
```

Outputs `results/lesson_study.json` and a human-readable `results/lesson_study.md`.

## Reading the preflight (calibration)

Difficulty was authored **without** access to the live model, so calibration is
required. For each pair the preflight prints `off_solve`, `on_solve`, `headroom`,
`injection`:

- `injection=FAIL` → the lesson never reached the prompt; the pair is invalid. (All
  8 pass the deterministic injection check already, but verify under the live path.)
- `headroom=NONE` (OFF solve 0.00 or 1.00) → no room to measure an effect:
  - OFF solve **1.00**: task is too easy, model never fails → make the task harder
    (edit a trickier symbol, tighten the completion cue).
  - OFF solve **0.00**: task is too hard / impossible even with the lesson → make it
    easier, or raise `--budget`.
- Keep only pairs with `0 < off_solve < 1`. That's where lessons can show an effect.

## Statistical notes / honest limits

- N=20 per arm per pair (160 reuse runs per arm) is a reasonable default; bump N for
  tighter CIs. The bootstrap and Mann-Whitney are non-parametric (retry counts are
  small integers, not normal).
- This proves transfer of a *seeded* lesson, in *one* failure family, on *this*
  model. It does not claim a universal "Hive always improves" — it claims, with
  numbers and CIs, whether a relevant generalized lesson reduces retries on new
  files. That is the honest, defensible version of the hypothesis.
- If you want the stronger organic claim, the next experiment is: let Hive *earn*
  the generalized lesson through repeated live failures (exercise
  `_promote_generalized_lesson_from_evidence`) instead of seeding it, then measure
  the same retry delta.
```

# Hive — Independent Review (branch `claude/phases-1-3-4Jshu`)

_Date: 2026-06-01 (review). Reviewer: Claude. Method: read CODEX.md, ReadMe.txt, RETROSPECTIVE.md,
HIVE_REPORT.md, HIVE_RELIABILITY_REPORT.md, core source, and the benchmark JSON under `results/`;
grepped real dependency usage; inspected `validation/`._

## Verdict in one line
The engineering and the safety/reliability story are strong and unusually self-aware. But the
project's **headline claim — that lesson memory makes Hive better — is not supported by Hive's own
A/B benchmark**, and three docs now contradict each other about what Hive even is. Fix those two
things before showing this to anyone who matters.

---

## 1. The A/B benchmark is structurally incapable of measuring learning (highest priority)

`results/benchmark_ab.json` is the file meant to prove the central thesis. Its own verdict:

```
"verdict": "no difference"
"delta": { passed_cases: 0, successful_patch_cases_passed: 0,
           expected_failure_cases_passed: 0, true_regressions: 0 }
```

`with_lessons` and `without_lessons` are **identical** — 40/40 in both arms, same bands, same
failure classes. This is not "lessons were tested and found useless." Reading
`benchmark_harness.py`, the benchmark **cannot** show a lesson effect, for two independent reasons:

**(a) Every case gets a fresh, empty lesson store.** `run_case()` → `_create_session()` creates a
brand-new temp dir with an empty `lessons.jsonl` *per case*:

```python
def run_case(self, case, lessons_enabled=True):
    session = self._create_session(lessons_enabled=lessons_enabled)   # new empty store every call
...
def _create_session(self, lessons_enabled=True):
    temp_root = self.repo_root / "tests" / f"_tmp_reliability_{uuid.uuid4().hex}"
    lesson_path = str(temp_root / "lessons.jsonl") if lessons_enabled else None
    coder.lesson_memory = LessonMemory(path=lesson_path or ..., max_entries=200)
```

A lesson recorded in case 1 is gone before case 2 runs. The `with_lessons` arm has lessons
*enabled but empty*. Cross-case learning — "each run begins warmer than the last" — is never
exercised.

**(b) The coder output is mocked to a constant.** Inside `run_case`:

```python
coder_patch = patch("coder.ask_hive", return_value=case["coder_response"])
```

Lessons work by injecting retry guidance into the prompt so the *next generation* differs. But the
generation here is a hardcoded string that ignores the prompt. Even within one case's retries,
lessons cannot change the output. Both arms are therefore deterministic and identical by
construction → 40/40 = 40/40 → "no difference."

Net: the benchmark measures the **deterministic validation gate**, not the lesson loop. The claims
in ReadMe.txt ("every failure is converted into a behavioral contract that shapes every subsequent
attempt") and RETROSPECTIVE.md ("each run begins warmer than the last") are **not just unevidenced —
they are untestable by this harness.** Consistent with this, sampled lessons in `hive_lessons.jsonl`
show `times_used: 0, success_after_use: 0`.

(There is also a ceiling problem — both arms score 1.0, and `validation/ab_run.py` even carries a
`ceiling_warning` / `use_challenge_pack` flag — but the two issues above are the binding constraint.)

**What to do:** build a seed→reuse harness that (1) shares **one** lesson store across an ordered
sequence of cases, and (2) lets the coder output **respond** to injected guidance (real Ollama, or a
mock keyed on whether lesson guidance is present). Then measure a learning signal — first-attempt
success rate, or retry count — on a *second* case similar to a *seeded* failure. A concrete sketch
is in `LESSON_HARNESS_SKETCH.md`. This is the single most valuable experiment left to run.

---

## 2. Three documents disagree about what Hive is

- **CODEX.md:** "Hive must never act autonomously in the real world"; keeps "humans in the loop for
  promotion and deployment." Describes an *interpretive ensemble* of reasoning heads.
- **RETROSPECTIVE.md:** "Hive operates **without a human in the loop**… it writes patches against
  itself, validates… and records lessons" — fully autonomous self-modification.
- **ReadMe.txt:** "No cloud. No API dependency. Yours completely." But `hive_llm.py` has a live
  Anthropic/Claude route (`CLAUDE_MODEL = "claude-opus-4-7"`, `CreditsExhaustedError`,
  `import anthropic`), so there *is* an optional cloud-API path.

These aren't nuance differences; they're opposite claims about autonomy, human oversight, and cloud
dependence sitting in the same repo. Pick the real story and make all three docs agree. The
Codex appears to describe a retired earlier vision — either archive it or add a header explaining
it's superseded.

---

## 3. Corrections to my own earlier review

In an earlier pass (on the v0.6 zip) I guessed two things that turned out to be **wrong** once I
actually grepped usage on this branch. Recording them so they don't propagate:

- **`torch` is NOT just a dummy vector.** `HiveAgent.py` uses real `torch.nn` / `optim` (attention
  fusion, weight mutation, feedback training); `HiveMemoryAgent.py` stores real tensors. It's a
  legitimate dependency. Keep it.
- **`anthropic` is NOT an unused leftover.** It's a live optional model route in `hive_llm.py`.
  Keep it in requirements — but reconcile it with the ReadMe's "no API dependency" claim (see #2).

So: do **not** trim these deps. The dependency-cleanup idea I floated earlier was based on a bad
assumption; verification overturned it.

---

## 4. What this branch got right (credit where due)

- Reproducibility now exists: `requirements.txt`, `requirements-dev.txt`, `Dockerfile`.
- The reliability evidence I asked for now exists and is rigorous: `HIVE_RELIABILITY_REPORT.md`
  reports 100/100 adversarial rejection, 100/100 safe acceptance, plus a Tier-2 suite with
  per-case logs.
- **Intellectual honesty is the standout.** The report names its own blind spot: the
  `correct_context_wrong_intent` case, 100/100 *accepted* — the executor enforces structural safety
  but cannot catch intent/logic regressions. Stating that with numbers is more convincing than any
  marketing line.
- A real validation gate (`validation/gate.py`, `scoring.py`, `variant.py`, `ab_run.py`),
  `success_memory.py` (learning from wins, not only failures), and a conversational layer.
- The git log shows deliberate CI-hardening — fixing the exact red tests and module collisions
  flagged earlier.

---

## 5. Lower-priority cleanup

- **Remove the 6.5 MB `hive_v05/` duplicate tree.** It's a near-complete copy of the old version
  nested inside the new one, and it already caused a CI "module collision between root and
  hive_v05 test suites" that had to be patched around. The old version is in git history; it
  doesn't need to ship in the working tree.
- **Surface the A/B comparison in a human-readable report.** The data (baseline, with-lessons,
  delta, verdict) is in `benchmark_ab.json` but isn't written up anywhere — put it next to the
  reliability report so a reader sees the delta at a glance.
- **Don't commit `__pycache__/` and `backups/*.bak`** — add a `.gitignore`.
- **Tone down absolute claims** ("Proven", "doesn't drift") until the lesson-benefit delta is
  shown on a non-ceilinged pack.
- **Independently re-run the gate cold** before quoting the 100%s externally — clean 100/100s are
  either real or a too-lenient grader; eyeball a few `tmp_stress/*.jsonl` rows to confirm the
  rejections fire for the right reasons. (I did not execute the suite here — it needs a live Ollama
  endpoint plus torch.)

---

## Priority order
1. Build the seed→reuse harness (shared lesson store + guidance-sensitive coder); measure a real learning signal. _(proves or disproves the thesis — see LESSON_HARNESS_SKETCH.md)_
2. Reconcile CODEX vs RETROSPECTIVE vs ReadMe into one consistent story. _(credibility)_
3. Delete the `hive_v05/` duplicate; add `.gitignore`. _(hygiene)_
4. Write the baseline-vs-lessons comparison into a report. _(presentation)_

# Hive lesson-system study — findings log

## Bugs fixed in the live codebase (surfaced by running the study)
These were real latent crashes on core paths, invisible until exercised:

1. `planner.py` `_extract_explicit_file_from_text` — `exact_matches` used before assignment (NameError). Fixed via `fix_planner.py`.
2. `executor.py` `parse_patch` — a dead, misplaced `actions`/gate block referencing undefined `target`/`verification`, iterating the wrong key-set (KeyError), and requiring BOTH additions and removals (would reject pure-addition patches). Deleted; `apply_patch` already gates correctly.
3. `executor.py` line ~659 — `except Exception:` calling `logger.error(str(e))` with neither `logger` nor `e` defined. Removed.
4. `planner.py` `_infer_change_intent` — referenced undefined `text` and built a dict with boolean keys (silent collapse). Rewrote as an if-chain. Called during planning, so it was a live crash.
5. (env) Mount write artifact: file writes get padded with trailing NUL bytes; strip with `rstrip(b'\x00')` if a `null bytes` / `unterminated string` SyntaxError appears.

## Mechanism bounds (verified against the code, no model needed)
- **Reactive, not proactive.** On a task's first attempt `failure_code` is None, so `get_retry_lessons` skips `find_relevant_lessons`; only `get_recent_lessons(file=...)` runs (exact-file filter). Cross-file generalized lessons are injected only on attempt 2+, after a matching failure. So lessons can cut RETRIES, not lift first-attempt success.
- **Cross-file transfer requires a *generalized* lesson** (`file=None`). Exact lessons are hard-filtered to their origin file.
- **Family must match.** A lesson only fires when the new task's failure_code matches the lesson's family.

## Empirical results (live qwen2.5-coder:7b)
### Round 1 (comment/architectural/route tasks, seeded `missing_diff_headers`)
- 6/8 pairs saturated (off_solve=1.00) — no headroom. Lesson family did NOT match the model's real failures (`missing_patch_section`, `symbol_anchor_drift`, `non_diff_commentary`).
- Pooled: no significant effect; slight NEGATIVE retry lean (irrelevant lesson = prompt noise).
- Bound learned: easy tasks saturate → lesson value 0; carrying an irrelevant lesson can mildly hurt.

### Round 2 (anchor-constrained logic edits, seeded `symbol_anchor_drift`, matched family)
- Calibration succeeded: real spread (off_solve 0.00–1.00, pooled ~0.70) — headroom finally exists.
- n=4 preflight: pairs split opposite directions (pair_4 helped 0.75→1.00; pair_3 hurt 0.50→0.25) = pure noise at n=4. pair_5 (`merge_anchor_with_span`) 0/0 = too hard, dropped.
- Pooled: still no significant effect (retry reduction CI [-0.54, +0.46], p~0.84).
- **This is the first rig that CAN measure an effect.** Full run: `--n 25 --budget 3`.

## Open question the full run answers
Does text-injected lesson guidance actually steer the model off an *anchoring* mistake — or is anchor-drift a "learning" problem (baked into attention) that a retrieved note cannot fix? A flat/negative N=25 result, with this much headroom and verified injection, would be a concrete, defensible bound: the retrieval-lesson approach fixes format/contract errors but not behavioral/attention errors.

## Reusable tooling built
- `benchmark_harness.run_sequence()` + `_run_one()` — shared-store sequence runner.
- `_run_one(..., live_coder=True)` — live-model mode (wraps real ask_hive).
- `coder._lessons_enabled` now actually honored (was set but never read — a 2nd reason the original A/B showed "no difference").
- `tests/test_lesson_reuse_sequence.py` — deterministic CI proof of the plumbing.
- `validation/lesson_study.py` + `lesson_study_cases.py` — live statistical study (bootstrap CI, Mann-Whitney, two-proportion z, mandatory headroom/injection preflight).

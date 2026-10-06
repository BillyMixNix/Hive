# HIVE-FACTORIAL-003R1 — Repaired Controller Replication

**Classification: REPAIRED_HIVE_VERIFIED_SUCCESSES_OBSERVED**

## 1. Experimental question

Did the frozen repaired Hive produce verified software across the same task/model/replicate cells that previously yielded 0/16? This study ran 16 of 16 cells; verified successes: **2/16**. Semantic review and promotion are separate dimensions. No candidate was promoted.

## 2. Historical baseline

FACTORIAL-002 remains 0/16 Hive and 0/16 single, with 37/29 model calls and 98.7/149.5 trial-minutes respectively. Fourteen Hive trials stopped during planning and two reached workers/edit preflight; none reached frozen acceptance or full verification. FACTORIAL-003 remains permanently EXPERIMENT_INVALID (zero valid completed cells, one compromised cell, fifteen unstarted). No historical cell is rescored or reused.

| Study / condition | Verified successes | Trials | Rate |
|---|---|---|---|
| FACTORIAL-002 Hive | 0 | 16 | 0% |
| FACTORIAL-002 single | 0 | 16 | 0% |
| HIVE-FACTORIAL-003R1 repaired Hive | 2 | 16 | 12.50% |

## 3. Frozen controller identity

Source tree hash: `f495206de7fecfe5950f941826a84dfd1d81d2ceac164a1899d5eede5cd04ca7`. The new isolated copy is byte-identical to final NFRT-ATTESTATION-002 source. [FREEZE.json](HIVE-FACTORIAL-003R1/FREEZE.json), [source inventory](HIVE-FACTORIAL-003R1/evidence/source-inventory.json), and [production inventory](HIVE-FACTORIAL-003R1/evidence/production-inventory.json) record all bytes, pinned tool/runtime identities and configuration. Freeze timestamp: `2026-10-06T03:19:22.635819+00:00`. Ollama version: `0.34.0`. Both local model digests match FACTORIAL-002.

## 4. Repairs included

Scope/correction feedback, complete context with truncation disabled, single-file exclusive ownership generation, original-task propagation, bounded legitimate correction diagnostics, observable verification, attested private NFRT reuse, fresh full compilation, strict reviewer schema, separated deterministic/review/promotion states, plus the qualified observational harness and generalized source-class NFRT attestation. No repair was made during this study.

## 5. Task/model/replicate design

Four unchanged tasks J001–J004 × qwen2.5-coder:14b and qwen3:8b × two replicates = sixteen Hive cells. Baseline, task text, authorized files and hidden acceptance identities are in the freeze. No new single-agent condition was run. The user authorized the sixteen Hive cells.

## 6. Trial order

Historical `random.Random(20261004)` shuffled task/replicate blocks and model/controller cells, then filtered Hive, preserving relative order. Frozen before outcomes:

| Ordinal | Task | Model | Replicate | Historical ordinal |
|---|---|---|---|---|
| 1 | J001 | qwen2.5-coder:14b | 2 | 3 |
| 2 | J001 | qwen3:8b | 2 | 4 |
| 3 | J004 | qwen3:8b | 1 | 6 |
| 4 | J004 | qwen2.5-coder:14b | 1 | 8 |
| 5 | J003 | qwen2.5-coder:14b | 1 | 9 |
| 6 | J003 | qwen3:8b | 1 | 12 |
| 7 | J003 | qwen2.5-coder:14b | 2 | 14 |
| 8 | J003 | qwen3:8b | 2 | 16 |
| 9 | J002 | qwen3:8b | 2 | 19 |
| 10 | J002 | qwen2.5-coder:14b | 2 | 20 |
| 11 | J004 | qwen2.5-coder:14b | 2 | 21 |
| 12 | J004 | qwen3:8b | 2 | 24 |
| 13 | J001 | qwen3:8b | 1 | 26 |
| 14 | J001 | qwen2.5-coder:14b | 1 | 27 |
| 15 | J002 | qwen3:8b | 1 | 30 |
| 16 | J002 | qwen2.5-coder:14b | 1 | 32 |

## 7. Runtime policy

One bounded non-task readiness request per model, then serial trials. Residency unmanaged consistently: no manual loading/unloading, warmups, GPU tuning, parameter changes or replacement cells. `num_ctx=12288`, `truncate=false`, temperature 0.1; output caps planner 2048, workers 6000, reviewer 1536. Existing two-attempt provider policy, 900-second generation setting, normal corrections, historical aggregate reservation/decision budgets remain frozen. Targeted/full outer/full inner deadlines remain 240/660/600 seconds. Exact provider wire bodies and terminal accounting are preserved per attempt.

| Readiness model | Result | Seconds | Scope |
|---|---|---|---|
| qwen2.5-coder:14b | completed | 55.548 | Short non-task diagnostic only |
| qwen3:8b | completed | 42.467 | Short non-task diagnostic only |

## 8. Integrity controls

The qualified recorder/candidate wrapper was copied byte-for-byte. All 52 assembled harness tests passed before freezing, including a scripted normal cell, exactly-once invocation, result/exception preservation, missing-field measurement errors and rollback. An initial test command failed because its temporary parent directory did not exist; its setup-error log/XML remain preserved. No inference occurred in those tests. Every cell started from a fresh baseline-derived candidate, with frozen tests held outside model-visible roots and private verifier caches. Scope, ownership, candidate hashes, frozen artifacts and source integrity remain host-enforced.

## 9. Per-trial results

| # | Task | Model | Rep | Software outcome | Review | Software frontier | Calls | Minutes |
|---|---|---|---|---|---|---|---|---|
| 1 | J001 | qwen2.5-coder:14b | 2 | VERIFIED SOFTWARE SUCCESS | approved | full_gate_passed | 3 | 15.79 |
| 2 | J001 | qwen3:8b | 2 | FROZEN_ACCEPTANCE_FAILURE | rejected | worker_correction | 5 | 30.09 |
| 3 | J004 | qwen3:8b | 1 | LOCAL_RUNTIME_FAILURE | rejected | worker | 3 | 22.37 |
| 4 | J004 | qwen2.5-coder:14b | 1 | PLANNER_FAILURE | not_run | planner_call | 2 | 7.84 |
| 5 | J003 | qwen2.5-coder:14b | 1 | FROZEN_ACCEPTANCE_FAILURE | rejected | revised_edit | 4 | 17.81 |
| 6 | J003 | qwen3:8b | 1 | LOCAL_RUNTIME_FAILURE | rejected | worker | 3 | 20.82 |
| 7 | J003 | qwen2.5-coder:14b | 2 | FROZEN_ACCEPTANCE_FAILURE | rejected | revised_edit | 4 | 18.67 |
| 8 | J003 | qwen3:8b | 2 | LOCAL_RUNTIME_FAILURE | rejected | worker | 3 | 22.01 |
| 9 | J002 | qwen3:8b | 2 | LOCAL_RUNTIME_FAILURE | rejected | worker | 3 | 18.69 |
| 10 | J002 | qwen2.5-coder:14b | 2 | FROZEN_ACCEPTANCE_FAILURE | rejected | worker_correction | 4 | 13.28 |
| 11 | J004 | qwen2.5-coder:14b | 2 | PLANNER_FAILURE | not_run | planner_call | 2 | 7.78 |
| 12 | J004 | qwen3:8b | 2 | LOCAL_RUNTIME_FAILURE | rejected | worker | 3 | 21.21 |
| 13 | J001 | qwen3:8b | 1 | EDIT_PREFLIGHT_FAILURE | rejected | worker_response | 4 | 29.47 |
| 14 | J001 | qwen2.5-coder:14b | 1 | VERIFIED SOFTWARE SUCCESS | approved | full_gate_passed | 3 | 14.65 |
| 15 | J002 | qwen3:8b | 1 | LOCAL_RUNTIME_FAILURE | rejected | worker_correction | 4 | 42.22 |
| 16 | J002 | qwen2.5-coder:14b | 1 | FROZEN_ACCEPTANCE_FAILURE | rejected | revised_edit | 4 | 19.24 |

[Raw aggregate](HIVE-FACTORIAL-003R1/evidence/raw-results.json) and [complete per-trial analysis](HIVE-FACTORIAL-003R1/evidence/per-trial-analysis.json) link run IDs, requests, outputs, plans, ownership, edits, corrections, review and resource observations. Transient applied-source snapshots and derived diffs survive rollback. A failure is not replaced.

## 10. Verified success results

Success requires a model-generated scoped candidate, fresh frozen acceptance, required full gate and identity/integrity. Reviewer unavailable/rejected cannot erase a deterministic success; neither confers promotion authorization.

| Grouping | Value | Successes | Trials | Rate |
|---|---|---|---|---|
| controller | hive | 2 | 16 | 12.50% |
| model | qwen2.5-coder:14b | 2 | 8 | 25.00% |
| model | qwen3:8b | 0 | 8 | 0.00% |
| task_id | J001 | 2 | 4 | 50.00% |
| task_id | J002 | 0 | 4 | 0.00% |
| task_id | J003 | 0 | 4 | 0.00% |
| task_id | J004 | 0 | 4 | 0.00% |
| replicate | 1 | 1 | 8 | 12.50% |
| replicate | 2 | 1 | 8 | 12.50% |

| Ordinal | Run ID | Verified source-manifest SHA-256 |
|---|---|---|
| 1 | bc33f077e5b9 | 3b42c99c278972943f70d47fce005cacea6d21b9e46dc4bb602a6a07a2282991 |
| 14 | 958e03c51a2a | 3b42c99c278972943f70d47fce005cacea6d21b9e46dc4bb602a6a07a2282991 |

The two successful cells independently produced the same candidate source identity. Each received a fresh baseline and independently passed fresh verification; this is two successful trials and one unique successful implementation. Both successes were J001/qwen2.5-coder:14b, one per replicate. They required no worker correction. Their full gates each passed 154 JUnit cases, 26 game tests and 3 quest game tests; exact commands, completion markers and results remain in per-trial verification evidence and the reachability audit.

## 11. Transition reachability

| Transition | FACTORIAL-002 Hive | HIVE-FACTORIAL-003R1 repaired Hive |
|---|---|---|
| Valid plan | 2/16 | 14/16 |
| Worker reached | 2/16 | 14/16 |
| Executable edit | 0/16 | 8/16 |
| Targeted verification attempt | 0/16 | 8/16 |
| Frozen acceptance | 0/16 | 2/16 |
| Full gate executed | 0/16 | 2/16 |
| Full gate passed | 0/16 | 2/16 |
| Verified software success | 0/16 | 2/16 |

Full-verification entry and actual full-gate execution are distinct; 2 entered full verification, 2 reached a `full_gradle_check` result. Semantic review was invoked in 14/16. External-candidate presentation restrictions remain in force. [Reachability audit](HIVE-FACTORIAL-003R1/evidence/reachability-audit.json).

## 12. Failure taxonomy

| Primary outcome | Trials |
|---|---|
| VERIFIED SOFTWARE SUCCESS | 2 |
| FROZEN_ACCEPTANCE_FAILURE | 5 |
| LOCAL_RUNTIME_FAILURE | 6 |
| PLANNER_FAILURE | 2 |
| EDIT_PREFLIGHT_FAILURE | 1 |

The table above preserves the frozen collector's native labels. The following diagnostic refinement separates duplicate ownership from other planner rejection and pre-test compilation failures from executed frozen-test failures. It changes no trial score or historical record.

| Observed class | Trials |
|---|---|
| VERIFIED SOFTWARE SUCCESS | 2 |
| TARGETED_VERIFICATION_FAILURE: COMPILATION | 3 |
| LOCAL_RUNTIME_FAILURE | 6 |
| OWNERSHIP_FAILURE | 2 |
| FROZEN_ACCEPTANCE_FAILURE | 2 |
| EDIT_PREFLIGHT_FAILURE | 1 |

[Per-cell taxonomy with native labels](HIVE-FACTORIAL-003R1/evidence/descriptive-taxonomy.json).

Exact native errors and verifier results are retained. Primary software outcome, reviewer disposition and runtime events are reported separately. Planner corrections: 2; structural worker corrections: 1; targeted corrections: 6; repeated-proposal trials: 2.

The frozen analysis found 0 malformed-response trials in terminal controller errors, but that measure omits successfully repaired reviewer parse failures. The separate review-protocol audit records 1 affected trial(s): cell 2 returned an empty initial review and the normal evidence-preserving JSON repair returned a valid rejection. [Reviewer protocol audit](HIVE-FACTORIAL-003R1/evidence/reviewer-protocol-audit.json).

The frozen collector's broad `FROZEN_ACCEPTANCE_FAILURE` label can include compilation failure because the native acceptance check also fails when no fresh test report exists. It does **not** establish that frozen assertions executed. The observed substage below preserves that distinction without changing any PASS/FAIL score or native record.

| Ordinal | Verifier mode | Observed substage | Fresh cases | Failures |
|---|---|---|---|---|
| 1 | targeted | PASS | 3 | 0 |
| 1 | full | PASS | 3 | 0 |
| 2 | targeted | COMPILATION_FAILURE_BEFORE_FROZEN_TESTS | 0 | 0 |
| 5 | targeted | COMPILATION_FAILURE_BEFORE_FROZEN_TESTS | 0 | 0 |
| 5 | targeted | COMPILATION_FAILURE_BEFORE_FROZEN_TESTS | 0 | 0 |
| 7 | targeted | COMPILATION_FAILURE_BEFORE_FROZEN_TESTS | 0 | 0 |
| 7 | targeted | COMPILATION_FAILURE_BEFORE_FROZEN_TESTS | 0 | 0 |
| 10 | targeted | FROZEN_TEST_FAILURE | 3 | 2 |
| 14 | targeted | PASS | 3 | 0 |
| 14 | full | PASS | 3 | 0 |
| 15 | targeted | FROZEN_TEST_FAILURE | 3 | 2 |
| 16 | targeted | FROZEN_TEST_FAILURE | 3 | 2 |
| 16 | targeted | FROZEN_TEST_FAILURE | 3 | 2 |

## 13. Semantic review

| Disposition | Trials |
|---|---|
| approved | 2 |
| rejected | 12 |
| not_run | 2 |

No review disposition is interpreted as human approval. Every row has `promotion_authorization=not_authorized`; native external-policy blocks remain recorded independently.

## 14. Runtime failures and resources

Trials with exhausted logical model calls, including reviewer-only failures: 6. Trials with any HTTP/provider-attempt error: 6; errored attempts: 6. Verifier runtime-failure trials: 0. These categories may overlap and are not summed as software failures.

All six runtime failures were qwen3:8b backend calls that exceeded the 900-second total generation limit. Cells 3, 6, 8, 9 and 12 failed before a worker response/edit. Cell 15 first produced an executable edit with two frozen-test failures, then timed out during targeted correction. The latter retains both its behavioral failure and runtime event. No reviewer call failed at the provider layer. The existing total-deadline policy ended these calls after one HTTP attempt; no manual retry was added.

| Ordinal | Pre host free GiB | Post host free GiB | Sampled minimum GiB | Pre GPU free MiB | Post GPU free MiB |
|---|---|---|---|---|---|
| 1 | 5.731 | 0.555 | 0.366 | 1176 | 1334 |
| 2 | 0.619 | 2.248 | 0.619 | 1334 | 1162 |
| 3 | 2.235 | 0.693 | 0.639 | 1158 | 1154 |
| 4 | 0.709 | 0.674 | 0.663 | 1154 | 1314 |
| 5 | 0.687 | 0.67 | 0.215 | 1318 | 1310 |
| 6 | 0.675 | 3.867 | 0.675 | 1310 | 1158 |
| 7 | 3.862 | 0.939 | 0.152 | 1154 | 1314 |
| 8 | 0.946 | 4.02 | 0.946 | 1314 | 1158 |
| 9 | 4.037 | 2.467 | 2.446 | 1158 | 1158 |
| 10 | 2.454 | 3.531 | 0.161 | 1158 | 1316 |
| 11 | 3.503 | 2.46 | 2.242 | 1316 | 1316 |
| 12 | 2.471 | 3.826 | 2.471 | 1316 | 1154 |
| 13 | 3.812 | 1.689 | 1.459 | 1154 | 1150 |
| 14 | 1.672 | 0.884 | 0.291 | 1150 | 1326 |
| 15 | 0.886 | 2.211 | 0.886 | 1326 | 1148 |
| 16 | 2.199 | 0.475 | 0.161 | 1148 | 1316 |

Virtual memory, residency, Docker/process state and asynchronous sampling timestamps are in per-trial runtime artifacts. Sampled minima are not continuous measurements. Resource pressure was observed without runtime tuning.

## 15. Model/token/time usage

| Metric | Observed |
|---|---|
| model_calls | 54 |
| provider_attempts | 54 |
| input_tokens_known | 210095 |
| output_tokens_known | 29216 |
| model_seconds | 16506.108138199983 |
| verification_seconds | 2464.2432551000093 |
| wall_seconds | 19317.999521399994 |
| successes_per_model_call | 0.037037037037037035 |
| successes_per_trial_hour | 0.3727093994398344 |

Token interpretation: Known completed logical-call token counts; not full attempted-generation totals when any attempt lacks final accounting. All-attempt accounting complete: False. Readiness is excluded from task-call and trial-efficiency totals. Faster failure is not superior efficiency.

Total trial time was 321.97 minutes (5.366 hours), versus historical Hive's 98.7 trial-minutes. Model time was 275.10 minutes and verifier time 41.07 minutes. These longer runs reached more stages; time alone is not a success comparison.

## 16. Comparison with FACTORIAL-002

Historical Hive 0/16 versus current 2/16; observed absolute rate difference 12.50 percentage points. The transition table separates candidate production from acceptance. Results occurred at different times with intentional changes to multiple controller/infrastructure mechanisms; no single-repair causal attribution is claimed.

## 17. Current single-agent comparison

Not run. Historical single remains 0/16 and is not represented as a contemporaneous control. Task/model/replicate-matched historical Hive records are preserved in the analysis artifact.

## 18. Statistical analysis

New rate 12.50%; two-sided 95% Clopper–Pearson interval **1.55%–38.35%**. Two-sided Fisher exact p-value for historical 0/16 versus current 2/16: **0.483871**. All planned trials completed. This observed increase is not statistically significant at 0.05 under the requested exact comparison. Small repeated cells, temporal differences and shared hardware limit generalization; this result does not establish reliability or broad superiority.

## 19. Candidate/evidence integrity

Final audit passed: **True**. [Final integrity](HIVE-FACTORIAL-003R1/evidence/final-integrity.json) includes controller, original source, prior evidence, baseline, all tests, cache/attestation/image, each candidate origin/stage, exact order, provider configuration and hidden-source absence checks. [Reporting integrity](HIVE-FACTORIAL-003R1/evidence/reporting-integrity.json) additionally rehashes the freeze lock and every frozen harness file. No apply/promotion call is authorized or executed. Each model receives only its own legitimate task/source/normal verification feedback.

Exact original task text is present in 21/21 captured worker/correction wire requests. Candidate source identities and transient diffs are retained; no earlier candidate was used to seed another cell.

## 20. Future investigation

Native observed failures are listed in [future-investigation.json](HIVE-FACTORIAL-003R1/evidence/future-investigation.json). They were not repaired, used as manual hints or fed into later cells. This file records evidence for later diagnosis rather than asserting unsupported root causes.

Observed frontiers worth separate investigation are multi-file ownership conflicts (cells 4/11), worker generation deadlines, nonmatching replacement anchors (cell 13), pre-test compilation failures (cells 2/5/7), repeated failed proposals (cells 2/10), and J002 corrections that either timed out (cell 15) or changed the proposal but still failed the same two emitted cases (cell 16). No causal diagnosis or repair of these frontiers was performed in this study. [Postprocessing notes](HIVE-FACTORIAL-003R1/evidence/reporting-notes.md) disclose reporting-only corrections; the frozen execution files remained unchanged.

## 21. Limitations

Sixteen cells, two local models, four bounded tasks, one workstation. Historical and current conditions intentionally differ. Both observed successes concern the same task/model and produce the same implementation; they do not demonstrate success across the task suite. Exact binomial/Fisher calculations describe the requested comparison, but repeated task/model cells are not evidence of independent draws from a broad software-task population. Short readiness cannot establish full-workload reliability. Missing attempt token counts are not zero usage. Reviewer concerns remain distinct from test correctness. No candidate promotion is part of autonomous success. A new study would require separate authorization and identity.

## 22. Final classification

**REPAIRED_HIVE_VERIFIED_SUCCESSES_OBSERVED** — 2 verified software successes across 16 completed cells. The measured result is retained. No extra trial, repair or promotion follows this report.

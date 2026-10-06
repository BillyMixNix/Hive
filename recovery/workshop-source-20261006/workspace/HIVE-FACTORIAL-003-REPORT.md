# HIVE-FACTORIAL-003 — Repaired Controller Replication

**Classification: EXPERIMENT_INVALID**

**The study cannot answer whether repaired Hive improved on 0/16.** A defect in the new measurement harness—not a Hive production defect—prevented actual targeted verification of the first generated edit. The same exception changed the controller's subsequent behavior. Execution stopped before cell 2. There are **zero valid completed cells, one compromised cell, and 15 unstarted cells**. The compromised cell is not scored as a model/software failure, and the unstarted cells are not counted as failures.

## 1. Experimental question

Compare autonomous verified software-task success under the final repaired controller against immutable HIVE-FACTORIAL-002 Hive 0/16. Success requires a current scoped model-generated candidate, current frozen acceptance and full-gate passes, and matching candidate identity. Review disposition is separate. No human approval or promotion is part of the metric.

## 2. Historical FACTORIAL-002 baseline

The historical result remains Hive 0/16 and single-agent 0/16. Hive used 37 model calls and 98.7 trial-minutes; single-agent used 29 calls and 149.5 trial-minutes. Fourteen Hive cells stopped in planning; two reached workers/edit preflight. Neither condition reached frozen acceptance or the full gate. Two single-agent cells were local-runtime failures. No historical record was rescored.

| Study / condition | Verified successes | Trials | Rate |
|---|---:|---|---:|
| FACTORIAL-002 Hive | 0 | 16 | 0% |
| FACTORIAL-002 single | 0 | 16 | 0% |
| FACTORIAL-003 repaired Hive | Not estimable | 0 valid; 1 compromised of 16 planned | Not estimable |
| FACTORIAL-003 single | Not run | 0 | Not applicable |

## 3. Frozen repaired Hive identity

The isolated controller is a byte-identical copy of `HIVE-REVIEWER-POLICY-001/repaired-workshop`: **162 files** in the complete inventory and **144** in the source inventory excluding runtime/cache directories.

Complete tree hash: `433d575ac0dfebab27e43d46c75a9e73ad66adb69dda196ba3455ed64ea9cd4b`.

Source-only tree hash: `e14049f0340d90eaff7a2ad2760367d1c0eea884e2814deb3bfc3d29a082b6e9`.

The tree-hash encoding, every file hash and all configuration identities are recorded in [FREEZE.json](HIVE-FACTORIAL-003/FREEZE.json). The original freeze SHA-256 remains `005584acfe5936b4bf55f3f9958d2ed1b7c24c7a6d0b356f1e88fdbfda0e7561`. No Hive production file changed.

## 4. Repairs included in the frozen controller

The source includes TRANSITION-001 scope/ownership feedback; TRANSITION-002 complete context transport; TRANSITION-003 bounded exclusive ownership generation; TRANSITION-004 durable verifier diagnostics; TRANSITION-004C attested private NFRT seeding and fresh compilation; TRANSITION-005 original-task propagation and bounded verification diagnostics; and REVIEWER-POLICY-001 strict review validation and separate deterministic, review and authorization states. The inherited completed regression evidence is 552 passed, 6 skipped; this measurement study did not modify production or rerun the suite.

## 5. Task/model/replicate design

Planned: J001–J004 × two models × two replicates = 16 Hive cells. Exact requests, write files and all four acceptance-test hashes are copied by identity from FACTORIAL-002 in the freeze. Baseline tree hash: `230340980b85d60b7a59d3aa338dffc4447c1bb7d8df90bff4d0dbe89afe5388`.

Both exact local digests match the historical study:

| Model | Digest |
|---|---|
| qwen2.5-coder:14b | `9ec8897f747e246e970bc5cfdda85d22f1123dc2e3d34978a010a75968716849` |
| qwen3:8b | `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41` |

## 6. Trial order

The historical `random.Random(20261004)` block procedure was reproduced and checked against its complete 32-cell order, then filtered to Hive without reordering. No outcome-driven ordering occurred.

| New ordinal | Historical ordinal | Task | Model | Replicate | Result |
|---:|---:|---|---|---:|---|
| 1 | 3 | J001 | qwen2.5-coder:14b | 2 | Compromised by harness; unscored |
| 2 | 4 | J001 | qwen3:8b | 2 | Not started |
| 3 | 6 | J004 | qwen3:8b | 1 | Not started |
| 4 | 8 | J004 | qwen2.5-coder:14b | 1 | Not started |
| 5 | 9 | J003 | qwen2.5-coder:14b | 1 | Not started |
| 6 | 12 | J003 | qwen3:8b | 1 | Not started |
| 7 | 14 | J003 | qwen2.5-coder:14b | 2 | Not started |
| 8 | 16 | J003 | qwen3:8b | 2 | Not started |
| 9 | 19 | J002 | qwen3:8b | 2 | Not started |
| 10 | 20 | J002 | qwen2.5-coder:14b | 2 | Not started |
| 11 | 21 | J004 | qwen2.5-coder:14b | 2 | Not started |
| 12 | 24 | J004 | qwen3:8b | 2 | Not started |
| 13 | 26 | J001 | qwen3:8b | 1 | Not started |
| 14 | 27 | J001 | qwen2.5-coder:14b | 1 | Not started |
| 15 | 30 | J002 | qwen3:8b | 1 | Not started |
| 16 | 32 | J002 | qwen2.5-coder:14b | 1 | Not started |

## 7. Runtime policy

Ollama 0.34.0; loopback `/api/chat`; `num_ctx=12288`; `truncate=false`; temperature 0.1; streaming; output caps planner 2048, workers 6000, reviewer 1536. These role caps match the final production app and FACTORIAL-002. The earlier runtime-replacement diagnostic's special all-role 2048 override was not inherited.

Existing provider policy: at most two attempts under its retry predicate, 900-second per-attempt generation limit. Existing controller budgets: one planner correction, one structural correction and one targeted correction per worker, one replan per worker, six observations; historical aggregate token reservation 250000 and model-decision wall ceiling 3600 seconds. Targeted deadline 240 seconds; full outer/inner deadlines 660/600 seconds.

The pinned image remains `sha256:b71e6beae584a3bba27e6fe782a27ef971b481b1dff7226bc57f28626843ad26`, with Temurin Java 21.0.12.1 and Gradle 9.2.1. Offline execution, `--rerun-tasks`, `--no-build-cache`, private dependency caches, fresh candidate compilation and all frozen gates were retained.

Actual residency was observed with no explicit model load/unload, keep-alive, GPU, context or memory tuning. One synthetic readiness request per model ran before task inference. Both returned the requested JSON in one attempt: 14B provider time 47.726 seconds; 8B 38.770 seconds. Readiness is not task-success evidence and was not repeated.

At resumed trial entry, observed free host RAM was **9.076 GiB**, free virtual memory **8.862 GiB**, and free GPU memory **5361 MiB**, with no resident model. Post-run values were 0.527 GiB / 1.005 GiB / 1322 MiB. Sampled minima were 0.325 GiB / 0.777 GiB / 1167 MiB. These are sampled observations, not causal explanations or continuous extrema. Hardware: RTX 2060 6144 MiB; driver 610.47; full host inventory is frozen.

## 8. Integrity controls and stop

Preflight initially detected an inherited cloud credential. Its value was never recorded; it was removed only from the local study subprocess environment before freeze/inference. No cloud call occurred.

The new harness then made an incorrect call to `freeze_junit_tests` during first-cell setup, before any task model request. [HARNESS-AMENDMENT-001.json](HIVE-FACTORIAL-003/HARNESS-AMENDMENT-001.json) preserves the original freeze, original executor, exact amendment and all-four-task staging validation. A separate executor used the historical two-step freeze/store API and profile metadata, continuing the same first run ID and byte-identical baseline candidate. No readiness or task-model sample was repeated. This setup deviation is disclosed, not hidden.

After inference began, a second harness defect compromised measurement. In `execute.py:record_verifier`, the call `event("verifier_started", ..., kind=kind, ...)` supplies `kind` twice to `common.py:event(kind, **data)`. It raises **before `original_target(...)` is called**. Hive sees that instrumentation exception as failed targeted verification, restores the stage and skips the full gate. The incomplete recorder row later causes `KeyError: 'host_elapsed_seconds'` during result collection, so the process exits before cell 2. The later explicit stop check found it already exited; no process was killed.

This satisfies the study's integrity-failure stop condition. The verifier-recorder bug was **not repaired after discovery**, and no replacement cell or model trial was launched.

## 9. Per-trial results

Only cell 1 was instantiated: J001 / qwen2.5-coder:14b / replicate 2 / run `236362654866`.

The planner's first response was valid. Backend solely owned the authorized file; UI/tests were inactive. The worker received the exact original host task, produced a scoped replacement, and passed edit preflight. The edit was applied transiently and copied by the recorder before its exception. There was no current targeted test decision. The normal exception path rolled the edit back. The unchanged candidate-origin and final stage both match baseline.

[Raw run](HIVE-FACTORIAL-003/evidence/trials/01-J001-r2-qwen2.5-coder_14b/run.json), [unscored cell record](HIVE-FACTORIAL-003/evidence/invalid-cell.json), [transient diff](HIVE-FACTORIAL-003/evidence/trials/01-J001-r2-qwen2.5-coder_14b/verifications/01-targeted/candidate.diff), and all exact request/stream bytes are preserved. The native run status is `rejected`; the study classification is **invalid measurement**, not a model failure.

## 10. Verified success results

No current candidate completed deterministic verification. A 0/16 success rate would be false: 15 cells never started and the first was compromised. Prior PASS records cannot substitute for the missing current acceptance and full-gate evidence.

## 11. Transition reachability

The partial trajectory is unscored and cannot estimate 16-cell reachability.

| Transition | FACTORIAL-002 Hive | FACTORIAL-003 repaired Hive |
|---|---:|---|
| Valid plan | 2/16 | Observed in 1 compromised cell; rate unavailable |
| Worker reached | 2/16 | Observed in 1 compromised cell; rate unavailable |
| Executable edit | 0/16 | Observed transiently in 1 compromised cell |
| Actual targeted verifier invocation | 0/16 | None; recorder raised before invocation |
| Frozen acceptance | 0/16 | Not run |
| Full gate | 0/16 | Not run |
| Verified software success | 0/16 | Not estimable |

## 12. Failure taxonomy

The study failure is **measurement-harness interference**. The first setup error was an API-wiring error; the live error was an event-argument collision followed by missing timing data. Neither is attributed to Hive's planner, worker implementation, frozen acceptance, or production verifier. The worker's correctness remains undetermined under this run's gates.

Observed runtime event: the first planner provider attempt returned HTTP 500 with CUDA shared-object initialization failure and process status `0xc0000409`. Its existing retry completed. There was no exhausted logical model call in the partial cell.

## 13. Semantic-review dispositions

The reviewer completed with `rejected`, confidence 0, explaining that the diff was empty. Its input was the empty post-rollback diff and the harness-caused error. This is not evidence of a semantic defect in the transient candidate. The disposition is preserved separately from the invalid software measurement. Study authorization remains `not_authorized`; the external-root policy remains `blocked` and no candidate was applied.

## 14. Runtime failures

Task inference made four HTTP attempts across three logical calls. One attempt failed; the normal retry succeeded. No inference timeout or exhausted retry occurred. Actual targeted/full verifier invocations: **zero**. The recorder exception is not labeled a Gradle/Docker timeout. No runtime parameter was changed in response to the failed attempt.

## 15. Model/token/time usage

These costs belong to the compromised partial execution and are not comparative efficiency metrics.

| Role | Provider attempts | Known input tokens | Known output tokens | Provider-call seconds | Result |
|---|---:|---:|---:|---:|---|
| planner | 2 | 3834 | 209 | 225.192 | Completed |
| backend | 1 | 5606 | 199 | 164.071 | Completed |
| reviewer | 1 | 1402 | 92 | 35.691 | Completed |
| Total | 4 | 10842 | 500 | 424.954 | Unscored |

The failed allocation attempt has no terminal token accounting. Known totals cover completed logical responses, not every attempted token. Readiness added two separate calls/two attempts, excluded above.

The resumed execution through executor exit took approximately **451.741 seconds**. The complete first-cell setup-to-stop span was **1748.949 seconds**, including the disclosed pre-inference setup interruption. No real verifier wall time exists. Planner corrections: 0; structural worker corrections: 0; targeted worker corrections: 0; repeated proposals: 0. The exception path ended worker verification before a normal behavioral correction could occur. Successes per call/hour are not estimated.

## 16. Comparison with FACTORIAL-002

The historical result is unchanged. No numerical improvement, regression or unchanged-success conclusion is supported by this invalid attempt. A complete repaired-controller replication remains unperformed.

## 17. Current single-agent comparison

Not run. The historical single-agent adapter invokes `hive.run_build`; reusing it with the repaired implementation would violate the requested independent-control boundary. A new independent adapter would be a separate design change, so the planned study retained only the permitted 16-cell Hive replication.

## 18. Statistical analysis

Preregistered methods were a two-sided 95% Clopper–Pearson interval and two-sided Fisher exact test for historical 0/16 versus new X/16. Their implementation was checked over all possible 0–16 success counts, but **no interval, difference or p-value is reported for this invalid study**. There is no valid new denominator. Even a completed historical comparison would span different times and multiple intentional repairs, with no attribution to one repair.

## 19. Candidate/evidence integrity

Final audit checked **33,430 prior files**: **0 changed**. The isolated controller and original reviewer-policy source match the initial inventory; baseline, all four frozen tests, pinned verifier identity, approved cache and NFRT seed attestation remain unchanged. Artifact integrity passes; experimental measurement validity does not.

Transient candidate tree: `05b66d7852034a79920793935517234336b7e126c7882016f6a10859b7c6ca7e`.

Transient authorized file hash: `b8a17817ccbf0846cfb4e765f5b530b4790e8c5dcdf6fef16a02d19a0f35a4d3`.

The transient edit is retained only as evidence. Candidate-origin and rolled-back stage hashes are `230340980b85d60b7a59d3aa338dffc4447c1bb7d8df90bff4d0dbe89afe5388`. No verified-stage identity was issued. There was no promotion, apply, cross-trial candidate reuse, source change, hidden-test-source injection, or reuse of a prior acceptance decision. Exact checks are in [final-integrity.json](HIVE-FACTORIAL-003/evidence/final-integrity.json).

## 20. Future-investigation observations

The new recorder requires deterministic execution-path testing before any separately authorized future study: specifically prove it reaches the wrapped verifier, returns the identical result, preserves exceptions without introducing new ones, and records timing on every path. This repair was not made here.

The already-frozen NFRT attestation permits independent changes only to SnapshotFormatter.java. Other task candidates could be blocked by its fail-closed compatibility policy. This was disclosed before inference and not expanded; its predicted impact on J002–J004 was not measured because those cells never ran. See [future-investigation.md](HIVE-FACTORIAL-003/future-investigation.md).

## 21. Limitations

The primary limitation is decisive: instrumentation altered the sole instantiated task trajectory. Readiness does not establish complete-workload reliability. First-cell setup interruption affects wall time and natural residency. Resource samples are approximate; Docker-state polling may affect engine warmth, which was not independently quantified. Matching digests do not remove runtime/resource differences across dates. The approved NFRT reuse scope is narrower than the task matrix. No result here supports autonomous reliability or its absence.

## 22. Final classification

**EXPERIMENT_INVALID.** Stopped at an integrity-compromising harness failure with one compromised cell and 15 unstarted cells. No retry, replacement, production repair, gate weakening, historical rescore or promotion followed. The requested repaired-controller success comparison remains unanswered.

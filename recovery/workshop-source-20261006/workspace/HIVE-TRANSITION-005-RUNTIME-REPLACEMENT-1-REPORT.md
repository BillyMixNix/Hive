# HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1

**Final classification: LOCAL_RUNTIME_FAILURE**

Run `4574db69cea0` produced one autonomous scoped candidate that passed frozen J001 acceptance and the unchanged full Gradle gate. The subsequent reviewer model call failed both existing provider attempts. Hive finished `rejected`, with no promotion. The classification follows the instruction to classify any exhausted model-runtime failure accordingly; it does not erase the completed deterministic passes.

Exactly one replacement trial ran. There were three logical model calls and four HTTP attempts: planner 1, backend 1, reviewer 2. No production source changed, no additional trial ran, and no parameter was adjusted in response to resource pressure.

## 1. Why the replacement was justified

The original TRANSITION-005 live run (`272595f790fd`) failed before a planner response, plan, worker, or candidate existed. Its behavioral experiment therefore remained uninstantiated. The user authorized exactly one replacement after an independent short runtime check. This report concerns that replacement, not a new transition experiment.

## 2. Immutable prior result

The original TRANSITION-005 result remains `LOCAL_RUNTIME_FAILURE`. The HIVE-FACTORIAL-002 result remains Hive 0/16 and control 0/16 verified successes. No previous result was rescored. The postflight audit checked all 11,572 sealed pre-existing workspace files without finding a change; the external frozen baseline, frozen test, attestation and seed also retained their identities. [Integrity audit](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/evidence/postflight.json)

## 3. Independent readiness evidence

The prior non-task request completed in 134.107 seconds with one provider attempt and no errors, using Qwen 14b, context 12,288, output cap 2,048, temperature 0.1 and `truncate=false`. Residency changed from absent to present; free host RAM changed from 7.95 to 0.46 GiB, and free GPU memory from 3,650 to 327 MiB. This established short-request readiness only. Its evidence was read and sealed, not rerun or modified. [Readiness result](HIVE-MODEL-RUNTIME-READINESS-001/evidence/result.json)

## 4. Pre-run resource state

At 2026-10-05 19:56:04.991 UTC, immediately before this trial, Qwen was **not resident**. Free host physical RAM was **7.819 GiB**, available virtual memory was **5.332 GiB**, and GPU free memory was **3,649 MiB**. The GPU was an NVIDIA RTX 2060, 6,144 MiB total, driver 610.47; Ollama reported version 0.34.0. Ollama server PID 3116 and Docker backend processes were recorded. No model was manually unloaded, loaded, warmed, or restarted. [Actual pre-run snapshot](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/evidence/runtime/pre-run.json)

## 5. Exact configuration

| Setting | Value |
|---|---|
| Source | Byte-identical isolated copy of final TRANSITION-005 repaired Hive |
| Task/controller/model | Frozen J001 / Hive / `qwen2.5-coder:14b` |
| Endpoint | `http://127.0.0.1:11434/api/chat`, streaming |
| Context/output/sampling | `num_ctx=12288`, `num_predict=2048`, `temperature=0.1`, `truncate=false` |
| Planner corrections | 1 maximum; 0 used |
| Worker structural/targeted corrections | 1 each maximum; 0 used |
| Provider policy | Existing retry policy, at most 2 HTTP attempts per logical call |
| Provider generation/read limits | 900 seconds / 900 seconds; unchanged implementation |
| Targeted deadline | 240 seconds, unchanged |
| Full verifier limits | Existing outer 660 seconds / inner full Gradle 600 seconds |
| Common harness ceilings | Existing 250,000-token reservation ceiling and 3,600-second model-decision wall ceiling |
| Authorized write file | `src/main/java/dev/atmcompanion/state/SnapshotFormatter.java` |
| Promotion/cloud | Disabled / local only |

The latest instruction explicitly required a 2,048-token cap. It was applied to **all roles** in this replacement harness. The historical T005 harness used 2,048 for planner, 6,000 for workers, and 1,536 for reviewer. This is disclosed rather than described as historical per-role equivalence. Both completed responses ended with `done_reason=stop`, at 209 and 208 output tokens; neither reached the cap.

All other provider options that were previously unspecified remained unspecified, including seed, stop sequences, keep-alive and GPU offload settings. The unchanged provider applies its 900-second generation limit inside each `_ollama_chat_once`; its existing retry loop was preserved. Each actual logical call received `total_timeout=900.0`. There were no manual retries.

The first planner wire request was byte-for-byte identical to the original T005 planner request: SHA-256 `1a46010f1868b5f337cc11f5ff8dd3c3908526b02c6a8b06eb1d45dc28cf6cde`, 28,075 bytes. [Configuration](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/evidence/configuration.json), [request audit](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/evidence/initial-request-audit.json), [frozen replacement manifest](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/FREEZE.json)

## 6. Integrity checks

Preflight verified the final T005 source against both the delivered source and its successful 501-passed/6-skipped regression manifest. It also verified the prior delivery seal, existing verifier-readiness evidence, model digest, exact J001 task/test identity, baseline, image, downloaded dependency inventory, NFRT compatibility and every attested seed file. No new regression or verifier control run was substituted for the requested live trial.

| Identity | SHA-256 |
|---|---|
| Frozen M3.2 baseline tree | `230340980b85d60b7a59d3aa338dffc4447c1bb7d8df90bff4d0dbe89afe5388` |
| Frozen J001 test | `80c1ced02955971cc827aed4e983d9407b919f47cc3af20f457f3a0f0098f159` |
| Approved NFRT attestation | `8c6df7a0c494053f083b4e97a24647b6a066ae024d6402b8ff2c89d0df781b04` |
| Pinned verifier image | `b71e6beae584a3bba27e6fe782a27ef971b481b1dff7226bc57f28626843ad26` |
| Qwen model digest | `9ec8897f747e246e970bc5cfdda85d22f1123dc2e3d34978a010a75968716849` |

The approved seed remained 22 files / 163,178,447 bytes, privately copied by the unchanged verifier. Postflight found no changes in the 153 isolated Hive files or the original T005 source, baseline, frozen test, attestation, or seed. [Preflight](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/evidence/live-diagnostic/preflight.json), [postflight](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/evidence/postflight.json)

## 7. Complete observed trajectory

| Transition | Observation |
|---|---|
| TASK → PLANNER CALL | Exact frozen task sent at 19:56:21 UTC |
| PLAN → VALIDATION → OWNERSHIP | First response accepted; no planner correction |
| WORKER DISPATCH | Backend request at 20:11:07 UTC; UI/tests inactive |
| WORKER RESPONSE → EDIT PREFLIGHT | Complete implementation response; one valid exact replacement |
| EXECUTABLE EDIT | Applied to isolated stage at approximately 20:21:27 UTC |
| TARGETED VERIFICATION → RESULT | Frozen 3/3 pass, returned at 20:24:56 UTC |
| WORKER CORRECTION / REVISED EDIT | Not needed; no second proposal |
| FROZEN ACCEPTANCE → FULL GATE | Fresh acceptance recheck and full Gradle gate passed |
| REVIEWER | Two HTTP 500 attempts; logical runtime failure at 20:32:45 UTC |
| Final state | `rejected`, `applied=false`, no promotion |

The UI/tests stage events are controller bookkeeping for inactive roles, not model dispatches. No timestamps are invented for standalone ownership/preflight checks that lack separate events; acceptance and the subsequent normal calls establish those transitions. [Complete run](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/evidence/live-diagnostic/runs/4574db69cea0/run.json), [derived trajectory](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/evidence/trajectory.json)

## 8. Planner result

The raw plan assigned the sole authorized file to backend. UI/tests used canonical `no change needed` goals with empty file and acceptance lists. Interface contracts and provider changes were empty. Normal schema/normalization, ownership and scope validation accepted the first attempt. The normalized plan retains the controller's empty intent-envelope metadata; no manual requirements or plan edits were injected. [Raw response](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/evidence/runtime/calls/01-planner/response.txt), [actual normalized plan](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/evidence/normalized-plan.json)

## 9. Semantic-fidelity check

The worker's outbound request contained the **exact complete original task**, explicitly labeled host-authoritative, alongside the planner-local contract and the complete owned baseline source. The original-task block also states that task context grants no additional write authority.

| Task requirement | Planner-derived text | Actual worker request |
|---|---|---|
| R1: preserve complete UTF-16 pairs during truncation | Present | Present explicitly |
| R2: preserve control-character sanitization | Absent | Present explicitly |
| R3: preserve section-sign sanitization | Absent | Present explicitly |
| R4: retain `...` when truncation is needed | Absent | Present explicitly |
| R5: preserve ordinary ASCII behavior | Absent | Present explicitly |
| R6: never introduce an unpaired surrogate | Present | Present explicitly |
| R7: never exceed the bound | Present | Present explicitly |

The planner-local acceptance was: “SnapshotFormatter.boundLine correctly handles UTF-16 surrogate pairs without introducing unpaired surrogates or exceeding MAX_LINE_CHARS.” Planner omissions therefore still occurred, but the repaired independent channel preserved the omitted semantics for the worker. This demonstrates delivered context, not inspection of internal model reasoning. Ollama completed the worker request with 5,606 reported input tokens and truncation disabled. [Semantic check](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/evidence/semantic-fidelity.json), [exact worker wire request](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/evidence/runtime/calls/02-backend/attempt-01/wire-request.json)

## 10. Initial worker result

The worker returned valid `status: implemented` JSON with one `replace` operation in the authorized file and no reported risks. Hive matched the exact `find` text, accepted the scoped replacement, and executed it in the isolated stage. No observation request, structural correction, manual code adjustment or additional worker attempt occurred. [Raw worker response](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/evidence/runtime/calls/02-backend/response.txt), [parsed operation](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/evidence/initial-worker-operation.json)

## 11. Initial candidate diff and identity

The model replaced the existing final truncation expression with a length guard, a boundary index that backs away from a high surrogate, and the existing ellipsis suffix. The sanitization statement was unchanged. The exact model-generated formatting is preserved; no cleanup or manual repair was applied. [Exact diff](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/evidence/initial-candidate.diff)

| Artifact | SHA-256 |
|---|---|
| Baseline authorized file | `5322a76cc496bdef8c6c5fb3d70ccd11004b076d6246cb7202874ca261255b98` |
| Verified staged file | `b8a17817ccbf0846cfb4e765f5b530b4790e8c5dcdf6fef16a02d19a0f35a4d3` |
| Verified staged candidate tree | `05b66d7852034a79920793935517234336b7e126c7882016f6a10859b7c6ca7e` |

The verified candidate lives under `evidence/live-diagnostic/runs/4574db69cea0/stage`. The separate unpromoted external candidate root remains baseline-identical. Consequently, the harness's final `candidate_sha256` is the baseline hash; it must not be confused with the verified stage hash above. [Candidate integrity](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/evidence/candidate-integrity.json)

## 12. Targeted verification result

**PASS: 3 cases, 0 failures, 0 errors, 0 skipped.** Both `frozen_junit_acceptance` and `source_immutability` passed. The unchanged 240-second outer budget was retained. The observable launch-request-to-process-exit interval was **153.637 seconds**; the Gradle test subprocess took **66.310 seconds**; the complete host wrapper, including integrity work, took **208.499 seconds**. No timeout fired. [Targeted result](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/evidence/live-diagnostic/verifications/targeted-01/result.json)

## 13. Correction diagnostic

No targeted failure occurred, so Hive supplied no worker correction diagnostic. Failure names, assertions, expected/actual values and case counts were not supplied as repair hints. The bounded correction transport was not exercised by this live trial. No artificial failure or extra call was introduced to test it.

## 14. Revised worker behavior

No revised worker response exists. The requested classifications `BYTE_IDENTICAL`, `SEMANTICALLY_EQUIVALENT` and `MATERIALLY_DIFFERENT` are **not applicable** because there was only one proposal. Repeated-proposal rejection was neither loosened nor triggered.

## 15. Revised candidate result

Not applicable. No revised edit or targeted reverification after correction occurred. The full verifier's normal fresh acceptance recheck used the same candidate, not a revised proposal.

## 16. Frozen acceptance

The unchanged frozen cases all passed on the first candidate:

- `truncationNeverSplitsAPair`
- `fullPairAtExactBoundRemainsIntact`
- `asciiAndSanitizationStayCompatible`

The full verifier independently repeated the same frozen 3-case acceptance and passed it again. These are new live-candidate results. They do not alter the historical baseline or TRANSITION-003 candidate failures. No hidden test source, preserved candidate, Astra implementation or post-hoc failure hint was supplied to generation.

## 17. Full-gate result

**PASS**, return code 0, no timeout. The exact Gradle invocation was:

```text
/opt/java/openjdk/bin/java -Djava.io.tmpdir=/work/tmp -classpath gradle/wrapper/gradle-wrapper.jar org.gradle.wrapper.GradleWrapperMain --no-daemon --offline --console=plain --max-workers=2 --rerun-tasks --no-build-cache -Dorg.gradle.jvmargs=-Xmx768m clean build runGameTestServer runQuestTestServer packTestJar
```

The full Gradle subprocess took **130.231 seconds**. The full isolated invocation, including fresh acceptance, took **361.467 seconds** from launch request to process exit; the complete host wrapper took **403.198 seconds**, within its unchanged outer 660-second limit. The full JUnit report contains **154 cases across 27 classes, 0 failures, 0 errors, 0 skipped**. Recorded game-server completion messages report **26 game tests** and **3 quest tests**, with the required tests passing. Source immutability passed and the temporary input directories were removed. The candidate was not promoted. [Full result](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/evidence/live-diagnostic/full-gate.json), [commands and phase evidence](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/evidence/verification-summary.json)

## 18. Model/runtime timing and errors

All timestamps below are UTC on 2026-10-05. Each actual request used the exact model and options in section 5.

| Logical call | Start → end | Elapsed s | Input/output tokens | Attempts | Result |
|---|---|---:|---:|---:|---|
| Planner | 19:56:21.198 → 20:11:03.314 | 882.116 | 3,834 / 209 | 1 | Complete; `done_reason=stop` |
| Backend | 20:11:07.783 → 20:21:27.044 | 619.260 | 5,606 / 208 | 1 | Complete; `done_reason=stop` |
| Reviewer | 20:31:40.062 → 20:32:45.883 | 65.821 | Unavailable | 2 | Provider failure; no review response |

Provider terminal metadata splits planner time into load **53.645 s**, prompt evaluation **419.710 s**, generation **407.274 s**; backend time into load **0.015 s**, prompt evaluation **448.306 s**, generation **169.709 s**. Backend reported seven cached prompt tokens. These are provider measurements, not inferred wall-time phases.

| HTTP attempt | Start → end | Elapsed s | HTTP | Request SHA-256 prefix |
|---|---|---:|---:|---|
| Planner 1 | 19:56:21.972 → 20:11:03.307 | 881.335 | 200 | `1a46010f1868` |
| Backend 1 | 20:11:08.474 → 20:21:27.040 | 618.566 | 200 | `0e1bd3b1cbe3` |
| Reviewer 1 | 20:31:40.523 → 20:32:38.109 | 57.586 | 500 | `9c1881f840a5` |
| Reviewer 2 | 20:32:38.612 → 20:32:45.881 | 7.269 | 500 | `9c1881f840a5` |

Reviewer attempt 1 reported a terminated `llama-server`, exit status `0xc0000409`, and `CUDA error: shared object initialization failed`. Attempt 2 reported exit status 1 and failure to allocate a **5,843,582,976-byte CUDA_Host buffer** while loading the model. The existing provider retry was exhausted. No further inference occurred. These are reported runtime failures, not reviewer reasoning failures or a model rejection of the code.

The trial took **2,200.777 seconds** overall. Known completed usage is 9,440 input and 417 output tokens; aggregate usage is unknown because reviewer attempts did not return usage. No unavailable count is treated as zero. Every attempt's exact request bytes, stream, timestamps and transport record are retained. [Runtime summary](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/evidence/model-runtime-summary.json), [raw call records](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/evidence/runtime/calls.json)

## 19. Host/GPU memory and residency

| Sample near boundary | Free host GiB | Free GPU MiB | Qwen resident |
|---|---:|---:|---|
| Pre-run | 7.819 | 3,649 | No |
| Planner attempt start | 7.654 | 3,641 | No |
| Planner attempt end | 1.648 | 319 | Yes |
| Backend attempt start | 0.916 | 321 | Yes |
| Backend attempt end | 0.785 | 1,535 | Yes |
| Reviewer attempt 1 start | 3.340 | 5,322 | No |
| Reviewer attempt 1 end | 8.926 | 5,330 | No |
| Reviewer attempt 2 start | 8.978 | 5,255 | No |
| Reviewer attempt 2 end | 8.973 | 5,330 | No |
| Post-run | 8.928 | 5,330 | No |

There are 78 timestamped resource snapshots, including boundary and approximately 30-second samples. The minimum observed free host RAM was **0.428 GiB**, minimum available virtual memory **0.512 GiB**, and minimum free GPU memory **315 MiB**. These minima need not coincide and are not continuous extrema. API residency includes observed context 12,288, model digest, allocation sizes and expiration. Related process command lines, PIDs, parent PIDs, memory and CPU counters are preserved where available.

Sampling is asynchronous: each snapshot has start/end timestamps, and its RAM, GPU and API readings are not simultaneous. Resource availability after a failed allocation is not a measurement of the precise allocation instant. No unload/reload, process closure, timeout change, GPU tuning or memory normalization was performed. The error causes beyond the provider's messages remain undiagnosed. [Resource timeline](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/evidence/resource-summary.json)

## 20. Final classification

**LOCAL_RUNTIME_FAILURE**, specifically the **reviewer model-runtime stage after successful deterministic verification**. The controller's actual final status is `rejected`; review approval is false because the provider call failed. The fully verified candidate is preserved separately from this failed end-to-end controller outcome. No acceptance result was converted into promotion or a historical rescore.

## 21. Furthest verified transition and comparison

**Furthest verified transition: FULL GATE.** A subsequent reviewer call failed before any reviewer response existed.

| Run | Result | Furthest transition |
|---|---|---|
| TRANSITION-005 original live trial | LOCAL_RUNTIME_FAILURE | Before PLAN |
| Runtime readiness check | PASS for short diagnostic only | Completed model response |
| TRANSITION-005-RUNTIME-REPLACEMENT-1 | LOCAL_RUNTIME_FAILURE at reviewer; candidate passed frozen/full gates | FULL GATE → reviewer runtime failure |

This replacement instantiated planning, semantic propagation, worker implementation and deterministic verification. The initial implementation satisfied the required gates. It did **not** instantiate behavioral correction or revision, and did not complete Hive reviewer approval.

## 22. Unchanged safety properties

No Hive production file was edited. The final T005 scope, context, exclusive ownership, original-task and correction-transport repairs remained byte-identical. Frozen assertions/selectors, exact one-file scope, attested private dependency seeding, fresh full compilation, `--rerun-tasks`, `--no-build-cache`, offline container isolation and source-integrity checks were preserved. No candidate classes, tests, reports or prior acceptance decisions were seeded.

The diagnostic harness only created an isolated copy/evidence destination, recorded exact requests/streams and resource state, applied the explicitly requested all-role output cap, and guarded against further logical inference after runtime failure. That guard did not block a requested later call: reviewer failure was the final normal call. No prompt edits, hidden-source hints, manual implementation, extra corrections or extra trials occurred. Normal failure containment left `applied=false` and `promotion_allowed=false`. [Source/evidence audit](HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/evidence/postflight.json)

## 23. Remaining uncertainties

- The reviewer initialization failures were preserved, not diagnosed or repaired. Memory snapshots alone do not establish their complete causal explanation.
- Worker repair behavior remains untested because the first proposal passed. No claim is made that the worker learned from a failed test or can reliably revise an implementation.
- Exact serialized input, disabled truncation and completed token accounting support delivered semantic fidelity; they do not expose internal model attention or reasoning.
- Read-only observation has some runtime overhead; its counterfactual effect was not measured, and no additional trial was run to estimate it.
- One candidate passing all required gates establishes this candidate's frozen/full-gate result, not reliability or universal correctness beyond those gates.
- The output-cap distinction from historical worker/reviewer limits is explicit. No assertion of identical historical per-role configuration is made.
- The 0/16 factorial and original T005 runtime failure remain unchanged. This experiment ended after its one authorized replacement.

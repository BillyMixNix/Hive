# HIVE-TRANSITION-004 — Targeted Verification Observability and Timeout

Classification: **PARTIAL_DIAGNOSIS**

The timeout was reproduced without a model and localized to **shared setup and Minecraft artifact reconstruction, before candidate compilation or frozen test execution**. Durable phase/output capture is repaired. The evidence does not identify a specific underlying runtime defect that justifies a performance change, and the historical missing phase trace cannot be recovered. The targeted limit remains **240 seconds**.

## 1. Prior experimental state

FACTORIAL-002 remains Hive 0/16 and control 0/16 verified success, with 14 Hive planning failures and two reaching workers/edit preflight. TRANSITION-001 repaired scope feedback/ownership validation; TRANSITION-002 repaired silent input truncation; TRANSITION-003 structurally constrained single-file ownership. Its live run `45ad10e6dd49` reached an executable scoped edit, timed out in targeted verification, rolled back, rejected an identical correction and skipped the full gate. No historical outcome is rescored.

All work here is in the new isolated [TRANSITION-004 area](HIVE-TRANSITION-004). Prior study trees, factorial results, frozen baseline and historical accepted-candidate evidence are read-only.

## 2. Exact TRANSITION-003 reconstruction

[Reconstruction](HIVE-TRANSITION-004/reconstruction.md) covers the 18 requested invocation dimensions and distinguishes recorded facts from code-derived behavior. [Exact applied diff](HIVE-TRANSITION-004/evidence/transition-003/applied-stage/first-applied.patch), [applied file](HIVE-TRANSITION-004/evidence/transition-003/applied-stage/first-applied-SnapshotFormatter.java), and [original observation](HIVE-TRANSITION-004/evidence/transition-003/applied-stage/observation.json).

[Source links](HIVE-TRANSITION-004/reconstruction-sources.md) identify the preserved host adapter, orchestration, byte-verified image entrypoint and JVM runner.

Applied file SHA-256: `a3219f4e0b65847123f6cebc150dbe1a026690bf9887062c25c2941747fef242`. Container: `hive-verify-4993c0baef72`. It was observed alive with the edit at 14:57:47.3258675Z. About 291 seconds separate completion of the initial worker call from the next correction, including work outside the 240-second Docker deadline. Historical launch/phase timestamps, exact temporary mount path and inherited Docker-client environment were not captured.

The frozen image ID is `sha256:b71e6beae584a3bba27e6fe782a27ef971b481b1dff7226bc57f28626843ad26`. Read-only inspection confirmed its runner source matches the preserved executable source and its runtime is Temurin 21.0.12.1+1. Gradle is 9.2.1. The fixed command is offline/no-daemon/rerun/no-build-cache `test --tests dev.atmcompanion.state.SnapshotFormatterUnicodeAcceptanceTest`, requiring exactly three nonfailed, nonskipped cases. Java cwd is `/work/candidate`; caches are approved/read-only and private writes go to tmpfs. Exact flags, mounts and constructed environment are recorded in the reconstruction.

## 3. Verifier call graph

[Complete call graph](HIVE-TRANSITION-004/verifier-path.md): worker preflight/snapshot/edit → `hive.targeted_verify` → external verification guard → `targeted_verify_isolated` → `run_isolated` → Docker runner → `run_jvm_profile` → Java version detection → Gradle frozen JUnit selector → XML/case/immutability checks.

The outer 240 seconds includes container startup, project/wrapper/native-input materialization and Gradle. Gradle's own 240-second subprocess timer starts later. Host source/cache validation and post-timeout cleanup are outside the outer timer. This nested-budget fact is not itself proof that the budget must increase.

## 4. Observability changes

[Design and limits](HIVE-TRANSITION-004/observability.md). New durable `verification-events.jsonl` records monotonic/wall time, run ID, phase, elapsed milliseconds, container and process identifiers/status where observable. It covers host preparation, source/cache copying, Java discovery, Gradle invocation/return, output markers, process exit/timeout, removal and cleanup. Container source timestamps remain distinct from host receipt timestamps.

`> Task` and `> Configure` lines are labeled observations, not invented exact task starts/completions. A fixed host-reviewed runner overlay is mounted read-only into the unchanged pinned runtime image, and its hash is recorded. This apparatus change is explicit; candidate code cannot supply it. No Gradle task listener, test change or runtime tuning is injected.

## 5. Partial output survives timeout

Docker stdout/stderr go to durable files. Inner Java output is streamed in bounded `process_output` events and materialized as child-stdout.log/child-stderr.log. The diagnostic stream has an explicit two-million-byte cap; none of these short measured logs reached it. Timeout still returns failure and never parses partial JSON as acceptance. Tests include a partial `passed:true` JSON followed by timeout, which remains rejected.

The previous code caught `TimeoutExpired` without retaining the exception, while inner Gradle logs remained buffered until a final report. Both losses are addressed. [Production patch](HIVE-TRANSITION-004/repair.patch) and [new tests](HIVE-TRANSITION-004/repaired-workshop/tests/test_verifier_observability.py).

## 6. Frozen-baseline verifier-only result

The initial unchanged baseline timed out at **240.051 seconds from launch request**. It spent **149.348 seconds before Gradle**, including **98.599 seconds copying native inputs**. Gradle then had about **90.703 seconds** before the outer deadline. Last observed task: `createMinecraftArtifacts`; no compile or test marker was reached.

[Baseline result](HIVE-TRANSITION-004/evidence/verifier-replays/measured-baseline/result.json), [events](HIVE-TRANSITION-004/evidence/verifier-replays/measured-baseline/diagnostics/verification-events.jsonl), [partial child output](HIVE-TRANSITION-004/evidence/verifier-replays/measured-baseline/diagnostics/child-stdout.log). This is an unchanged control timing result, not a passing baseline or a failing JUnit assertion.

## 7. Preserved-candidate verifier-only result

The exact TRANSITION-003 applied file was copied onto a fresh frozen baseline, with its hash checked. The initial replay timed out at **240.105 seconds**: **96.140 seconds before Gradle**, including **78.480 seconds native-input copy**, then **143.965 seconds of Gradle exposure**. It reached the `binaryWithNeoForge` substep of `createMinecraftArtifacts`, before any observed compile/test task.

[Preserved-candidate result](HIVE-TRANSITION-004/evidence/verifier-replays/measured-preserved/result.json) is labeled **POST_HOC_CANDIDATE_VERIFICATION** and contains no acceptance pass. No candidate implementation was altered. TRANSITION-003 remains its original failure.

## 8. Phase timing comparison

The compatible Astra candidate was used only as a verifier control, never as model context or a Hive implementation. Its historical hash and sealed acceptance/full-gate evidence were checked. It also timed out: **140.482 seconds before Gradle**, including **115.700 seconds native-input copy**, leaving about **99.594 seconds** for Gradle. It remained in shared artifact construction.

[Timing comparison](HIVE-TRANSITION-004/timing-comparison.md) separates launch, materialization, wrapper/native copies, Gradle exposure and cleanup; [machine data](HIVE-TRANSITION-004/evidence/timing-comparison.json) retains exact observations. These are sequential fresh-container measurements, not randomized performance estimates. Initial launch/cache warmth and ambient host load vary.

## 9. Process-state evidence

[Read-only /proc sample](HIVE-TRANSITION-004/evidence/verifier-replays/measured-baseline/diagnostics/proc-153432.json) caught verifier Python in `p9_client_rpc`, with an approved asset open for reading and its tmpfs copy open for writing. Only verifier Python was present then. This directly observes filesystem waiting during materialization; it does not prove a broken filesystem.

Later inspect/top/stats records show wrapper JVM, single-use Gradle daemon and active NeoForm tool descendants, advancing output and CPU activity. Samples report no OOM kill or external network I/O. Container removal succeeds, subsequent inspect reports no such object, and sanitized-source cleanup is confirmed. [Real synthetic descendant teardown test](HIVE-TRANSITION-004/evidence/regression-container-timeout/verification-events.jsonl) independently exercises the same adapter with an observed sleeping child; its test-only substituted command is preserved.

[Host snapshot](HIVE-TRANSITION-004/evidence/environment-observation.json) records limited free RAM, Docker/WSL resources and relevant processes. It is a snapshot, not a causal resource-pressure experiment. No user process was stopped, cache purged, daemon setting changed or invasive JVM profiler attached.

## 10. Pre-repair timeout diagnosis

[Sealed diagnosis](HIVE-TRANSITION-004/diagnosis.md): **INSUFFICIENT_EVIDENCE** for a specific underlying runtime defect or intrinsically invalid budget. The [seal](HIVE-TRANSITION-004/evidence/pre-replay-diagnosis-seal.json) precedes post-regression replay.

What is established: setup consumes a large variable portion of the outer budget, and the deadline is exhausted during shared artifact reconstruction in all three initial controls. The edit is not necessary to reproduce the timeout, and its code/tests were not executing at the observed boundary. What is not established: why current filesystem/runtime latency has these values, which safe minimal performance repair would remove it, or the original run's exact unrecorded internal phase.

No wrong cwd/selector, dependency network loop, pipe deadlock or leaked container was demonstrated. Previous accepted evidence reports a 161.382-second inner Gradle run, but does not establish today's setup-plus-Gradle duration. Budget inadequacy is not concluded merely from exceeding 240 seconds.

## 11. Production changes

Delivered changes are limited to `workshop/verifier_trace.py`, `workshop/hive_verifier.py`, diagnostic metadata retention in `hive.targeted_verify`, and event emission/stream visibility in `verification/jvm_runner.py`. Three test files add coverage/adapt exact mount and removal assertions. [File hashes](HIVE-TRANSITION-004/repair-manifest.json).

There is **no behavioral runtime/performance repair**. The patch applies cleanly against the isolated final TRANSITION-003 source. No previous source tree is updated in place. The JVM gate algorithm is AST-identical after removing event-emission statements; frozen assertions, selectors, source checks and case counts are unchanged. [Safety audit](HIVE-TRANSITION-004/evidence/safety-audit.json).

## 12. Regression results

**453 passed, 6 skipped**, complete available repository suite. All six skips concern unavailable Windows symlink privileges. [Command/result](HIVE-TRANSITION-004/evidence/regression.json), [full log](HIVE-TRANSITION-004/evidence/regression.log).

Coverage includes successful/failing output capture, both timeout streams, failure despite partial PASS JSON, exit codes, timestamp ordering, exact-container cleanup and observed descendants, plus existing rollback/frozen-gate checks and TRANSITION-001/002/003 protections. The new real-container lifecycle test uses synthetic sleeping processes and does not claim J001 acceptance. Early harness/test setup failures and their corrections are preserved in the [execution journal](HIVE-TRANSITION-004/experiment-journal.md) and regression-attempt-1; an unrelated legacy non-JVM Python staging error was not repaired in this JVM study.

## 13. Post-regression verifier replay

Both fixed-count repeats also timed out before compilation/tests. [Repeated baseline](HIVE-TRANSITION-004/evidence/verifier-replays/post-regression-baseline/result.json): 101.566 seconds before Gradle and 138.477 seconds of Gradle exposure, outer timeout 240.043 seconds. [Repeated preserved candidate](HIVE-TRANSITION-004/evidence/verifier-replays/post-regression-preserved/result.json): 125.471 seconds before Gradle and 114.594 seconds of Gradle exposure, outer timeout 240.065 seconds.

The instrumentation remained fixed; there was no speculative performance patch between measurements. All **five** verifier-only controls timed out in `createMinecraftArtifacts`. All candidate, baseline and historical-source integrity checks passed. The preserved-candidate records retain their POST_HOC_CANDIDATE_VERIFICATION label; no frozen acceptance result or full gate was obtained. [Campaign summary](HIVE-TRANSITION-004/evidence/campaign-summary.json).

## 14. Live diagnostic decision

**No live model trial: zero model calls.** [Condition audit](HIVE-TRANSITION-004/evidence/live-decision.json): observability works and regression passes, but no normal control reaches a meaningful verifier result within the unchanged budget, and a specific remediable timeout root cause remains unestablished. The user-specified live-entry conditions are therefore unmet. No attempt was made to obtain a pass by increasing the deadline, changing the candidate or adding trials.

## 15. Furthest transition reached

| Experiment | Furthest verified transition |
|---|---|
| FACTORIAL-002 | Worker/edit preflight in 2/16; 14/16 planning |
| TRANSITION-001 | Ownership validation |
| TRANSITION-002 | Ownership validation with complete input |
| TRANSITION-003 | Executable edit → targeted verifier timeout |
| TRANSITION-004 | Observable verifier-only setup → shared artifact reconstruction → timeout; no frozen acceptance |

This is improved localization, not an autonomous software-success claim. A post-hoc candidate result cannot rewrite TRANSITION-003, and the historical accepted candidate's current timing failure does not rewrite its earlier sealed acceptance.

## 16. Unchanged safety properties

The 240-second targeted deadline, pinned JDK/image/cache identities, offline/no-network execution, read-only source/cache mounts, finite CPU/RAM/PID limits, frozen JUnit bytes/case counts, full Gradle gate, scope enforcement, exclusive ownership, context-fidelity controls, correction budgets, repeated-proposal rejection and baseline/candidate isolation remain intact. Full-gate eligibility still requires successful prerequisites. No promotion occurs.

Only diagnostic output paths are added outside candidates. The trusted instrumentation mount grants no candidate write authority. Timeout output and event markers never count as a pass. Prior evidence integrity and final source identity are audited separately.

[Integrity result](HIVE-TRANSITION-004/evidence/prior-integrity-after.json): 3,030 TRANSITION-001 files, 891 TRANSITION-002 files, 1,618 TRANSITION-003 files and 18,002 inventoried factorial files are unchanged, with no additions or missing files in their checked inventories. The first three inventories include existing cache files; the legacy factorial inventory excludes Python/pytest caches. Historical accepted-control records and the previously inspected EVAL-009 artifacts are also hash-checked.

## 17. Falsification criteria

Candidate-induced timeout gains support if controls reach meaningful results within budget while the preserved candidate alone stalls in its test execution. The observed pre-compilation timeouts in baseline and accepted controls contradict that pattern.

A proposed runtime repair needs a specific causal observation and a same-input check preserving all gates. A filesystem wait alone is insufficient. A budget diagnosis requires correct expected timing after remediable defects are excluded. Any acceptance from partial output, missing cases, altered assertions, lost scope/context constraints or failed cleanup falsely reported as successful would invalidate this observability repair.

## 18. Remaining uncertainties and deferred frontier

Historical internal timing is unrecoverable. Current setup variability, host memory pressure, cache warmth, model residency and filesystem transport latency were not independently controlled; their individual causal contributions remain unknown. Instrumentation adds small I/O/inspection overhead and cannot expose every internal Gradle phase. The observed timeouts establish no semantic correctness of the preserved edit.

The original “unchanged behavior for ordinary ASCII lines” requirement reached the TRANSITION-003 planner but disappeared from its derived worker contract. That remains a separate **TRANSITION-005 semantic-fidelity hypothesis**. No planner, worker contract or candidate implementation change addresses it here.

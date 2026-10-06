# HIVE-TRANSITION-004C — Verified dependency reuse and compileJava localization

Classification: **VERIFIER_INFRASTRUCTURE_DEFECTS_IDENTIFIED_AND_REPAIRED**

The production seed now attests invariant NFRT intermediates and copies them into each verifier's private cache. The remaining `compileJava` timeout was localized to Gradle classpath analysis and incremental result storage after compilation. Full compilation in the disposable verifier removes that unused bookkeeping while preserving all sources, tasks, assertions and the 240-second subprocess deadline. Final verifier-only outcomes: baseline **FAIL: 3 cases, 1 failure, 0 errors, 0 skipped**; preserved candidate **FAIL: 3 cases, 2 failures, 0 errors, 0 skipped**. No model was invoked.

## 1. Prior state

FACTORIAL-002 remains 0/16 Hive and 0/16 control successes, with 14 Hive planning failures and two worker attempts. TRANSITION-001 repaired scope/ownership diagnostics; 002 repaired context loss; 003 repaired the one-file ownership generation interface and produced the preserved edit in run `45ad10e6dd49`. That run timed out and rolled back. TRANSITION-004 localized the shared timeout to reconstruction; 004B established attested NFRT reuse but still timed out at the compileJava marker. None of those historical outcomes is revised.

## 2. NFRT cache trust boundary

[cache-policy.md](HIVE-TRANSITION-004C/cache-policy.md) was written before production edits. The approved seed contains **22 dependency-intermediate files / 163,178,447 bytes**, representing ten NFRT nodes. No project build directory, application/test classes, task history, JUnit report, verifier JSON or acceptance decision is reused. Dependency JARs contain dependency classes; application package entries are forbidden.

This approval is bounded to a measured immutable build and an explicitly attested independent Java-source scope. It is not universal reuse for arbitrary Gradle projects. The attestation is host-pinned, never planner/worker supplied. The per-study allowed source filename is approval data, not a production-code special case.

## 3. Production seed implementation

`verification/nfrt_seed.py` validates the pinned attestation, sealed priming inventory/provenance, exact file membership, regular-file status, size/hash, NFRT key records and application-package exclusion. `workshop/hive_verifier.py` selects it from host configuration, validates compatibility, mounts source/manifest read-only, passes the attestation digest, and rechecks the shared seed after execution. `verification/jvm_runner.py` revalidates, copies bytes into a fresh private writable intermediate directory and verifies the copy before NFRT runs. No hard links or shared writable cache are introduced.

The full source is in [repaired-workshop](HIVE-TRANSITION-004C/repaired-workshop); [production.patch](HIVE-TRANSITION-004C/production.patch) is the reviewable delta against 004.

## 4. Integrity and compatibility policy

Both `HIVE_NFRT_SEED_MANIFEST` and `HIVE_NFRT_SEED_SHA256` are required to select a seed. With neither configured, existing verified reconstruction remains the explicit policy. Partial, missing, corrupt or incompatible configured seeds fail closed, without fallback.

The attestation binds baseline hash, exact image/JDK identity, wrapper/profile, complete approved module/tool bytes, downloaded-input manifest, sealed priming provenance and complete source/config inventory. Only the reviewed existing independent main-source file may differ. Build scripts, Gradle properties, resources, mappings, access transformers, interface injection and Parchment inputs are fixed; additions/deletions invalidate compatibility. The measured NFRT input object records all 131 artifact identities/hashes, NFRT 2.0.31, ModDevGradle 2.0.147, NeoForge 21.1.251, Java/tool paths and binary/cache options. Changed participating inputs require a new attestation. NFRT cache existence alone never authenticates a seed.

See [approved attestation](HIVE-TRANSITION-004C/evidence/approved-nfrt-seed.json) and [operator policy](HIVE-TRANSITION-004C/repaired-workshop/verification/NFRT-SEED-POLICY.md).

## 5. Cache regressions

Thirty deterministic seed tests cover valid attestation; corrupted, missing, extra and mis-hashed files; build/image/tool/download identity changes; changed build/source/test inventory; application/test/generated-class contamination; prohibited reports/history/source results; private-copy independence; copy-failure cleanup; readonly mounts; absent-seed policy and configured-seed failure. The initial pinned-image integration caught an unsupported Python hashing API; it was replaced with streaming SHA-256 and preserved as an integration failure, not a compile measurement.

## 6. Exact compile path

The targeted graph is `createMinecraftArtifacts -> compileJava -> classes -> compileTestJava -> testClasses -> test`. It compiles **49 main sources**, then **30 test sources** including the frozen test. Main classpath: **88 entries / 95,249,358 bytes**. Runtime task observations show no annotation processors or custom compiler arguments, no compiler fork, and no generated Java in the sampled candidate. Test selection limits execution, not compilation coverage.

The initial controls had `incremental=true` despite fresh project state, `--rerun-tasks` and `--no-build-cache`. [compile-path.md](HIVE-TRANSITION-004C/compile-path.md) records the pinned build/plugin implementation and measured task metadata.

## 7. Compilation observability

Private observation-only Gradle init hooks record settings, projects, graph and JavaCompile action entry/completion with source/classpath/processor/compiler metadata. A task marker and an action-entry event are explicitly distinct from javac entry. Bounded process samples retain command lines, JVM thread dumps, CPU/IO/status, cgroup memory/CPU events and class counts. Existing partial-output capture, timeout failure and container termination remain intact.

At late initial samples the Gradle stack traverses `IncrementalResultStoringCompiler.storeResult`, classpath snapshots, dependency analyzers and ZIP reads. The pinned implementation calls this after its compiler delegate returns. This establishes post-compilation work at those samples, not exact continuous timing for every internal phase. The candidate already had 118 current-run main classes before timeout. No OOM/limit events or network IO were observed. The diagnostic selector's initial self-match was corrected before final replays; see [measurement notes](HIVE-TRANSITION-004C/measurement-notes.md).

The final preserved replay also contains a direct javac stack (`com.sun.tools.javac.file.FSInfo` and compiler classpath setup) in `jvm-state-201274.json`, followed by compile-action completion. Thus compiler entry is now directly observed, separately from the task marker. Final main compile actions take 13.249 / 13.788 seconds; test compile actions take 3.410 / 2.628 seconds (baseline / candidate). These action intervals include javac and its task-local work, not only compiler CPU time.

## 8. Baseline timing

| Control | Download copy s | Private seed s | Gradle starts s | NFRT runtime | Bounded subprocess s | Result |
|---|---:|---:|---:|---|---:|---|
| seeded-baseline-02 | 72.616 | 6.444 | 94.116 | 7.94s | 240.044 | 240 s timeout at compileJava |
| seeded-preserved | 81.735 | 6.866 | 104.867 | 7.68s | 240.055 | 240 s timeout at compileJava |
| final-baseline | 83.720 | 6.431 | 106.128 | 7.68s | 207.605 | FAIL: 3 cases, 1 failure, 0 errors, 0 skipped |
| final-preserved | 80.210 | 6.366 | 104.932 | 6.72s | 201.959 | FAIL: 3 cases, 2 failures, 0 errors, 0 skipped |

Times are relative to Docker subprocess launch. The limit is the unchanged outer subprocess timeout, including container setup/materialization. Host preflight and postflight integrity checks are additional: final baseline `run_isolated` wall time **240.460 s**; final candidate **233.257 s**. The harness also validates the environment before calling the verifier. These totals are disclosed separately; no work was reclassified as acceptance, and no timeout was increased.

## 9. Preserved-candidate timing

Both seed-only controls timed out. Both final controls used the same final production source, pinned image, offline configuration, exact candidate identities, frozen selector and 240-second deadline. Detailed task-action durations, phase events, raw output, invocation and process snapshots are in [timings.json](HIVE-TRANSITION-004C/evidence/timings.json) and [runs](HIVE-TRANSITION-004C/evidence/runs). This is a small causal control comparison, not a throughput benchmark or success-rate estimate.

## 10. Downloaded-input materialization

The original copy still validates and copies 3,895 files / 914,224,273 bytes. Direct mountinfo identifies **readonly 9p/DrvFS -> private tmpfs**. Final group timing separates source inventory, six 89 MB artifacts and 3,889 assets totaling 825 MB. Metadata inventory alone consumes about 31 seconds; the large artifact group takes about one second. Hashes are recomputed while copying. File metadata overhead is directly material; exact read/hash/write attribution within a copy group remains unknown.

No optimization of this path was installed. NFRT updates artifact timestamps; a blanket readonly replacement is unsafe. [input-materialization.md](HIVE-TRANSITION-004C/input-materialization.md) records the source analysis and bounded future possibilities. Resource Saver was not disabled; it is not supported as the cause of the late compileJava state.

## 11. Pre-additional-repair diagnosis

[compile-diagnosis.md](HIVE-TRANSITION-004C/compile-diagnosis.md), sealed before the additional performance change, classifies **MIXED_RUNTIME_COST**: substantial filesystem materialization plus unnecessary post-compilation incremental bookkeeping. The baseline and candidate share this work. Gradle makes forward progress and remains below memory limits; neither candidate-method execution nor a deadlocked javac is supported as the timeout cause. Post-work samples and pinned source establish a concrete removable cost, without claiming all 240 seconds had one cause.

## 12. Additional repair

A host-owned private init script sets JavaCompile `options.incremental=false` in fresh isolated verifiers. Gradle's supported full-compilation branch supplies all stable sources to the same toolchain compiler and avoids writing unused incremental analysis. Every compile task, dependency, selector, assertion, output-integrity check and resource limit remains. No candidate output is reused. This is an explicit compilation-mode change, not a claim that the entire build execution is byte-identical.

The real Gradle regression proves valid Java compiles and malformed Java fails, clearing the previous synthetic class. The final controls establish whether this change produces current frozen test results within the original deadline. Pinned source references: [result storage](https://raw.githubusercontent.com/gradle/gradle/v9.2.1/platforms/jvm/language-java/src/main/java/org/gradle/api/internal/tasks/compile/incremental/IncrementalResultStoringCompiler.java) and [full-compilation branch](https://raw.githubusercontent.com/gradle/gradle/v9.2.1/platforms/jvm/language-java/src/main/java/org/gradle/api/tasks/compile/JavaCompile.java).

Files changed in the isolated production checkout:

- `tests/test_fresh_compilation_policy.py`
- `tests/test_nfrt_seed.py`
- `verification/jvm_runner.py`
- `verification/NFRT-SEED-POLICY.md`
- `verification/nfrt_seed.py`
- `workshop/hive_verifier.py`
- `workshop/verifier_trace.py`

## 13. Complete regression

**485 passed, 6 skipped**; skips are existing Windows symlink-privilege limitations. The suite includes scope enforcement, context fidelity, exclusive ownership, rollback, repeated proposals, partial timeout output, actual container/descendant teardown, frozen gate checks, new seed integrity/compatibility tests and an actual pinned-Gradle compiler rejection test. [Complete log](HIVE-TRANSITION-004C/evidence/regression/complete-02/pytest.log). The first suite run's fixture/setup errors are retained under `complete-01`, then fixed; no failure was relabeled as a pass.

## 14. Final baseline replay

**FAIL: 3 cases, 1 failure, 0 errors, 0 skipped**. See [result](HIVE-TRANSITION-004C/evidence/runs/final-baseline/result.json). The original `truncationNeverSplitsAPair` failure is now observable; the other two frozen cases pass. A deterministic rejection of the known unfixed baseline is the meaningful infrastructure result.

## 15. Final preserved-candidate replay

**FAIL: 3 cases, 2 failures, 0 errors, 0 skipped**. See [result](HIVE-TRANSITION-004C/evidence/runs/final-preserved/result.json). `truncationNeverSplitsAPair` fails at frozen assertion line 11 and `fullPairAtExactBoundRemainsIntact` fails at line 27; `asciiAndSanitizationStayCompatible` passes. The preserved SnapshotFormatter SHA-256 remains `a3219f4e0b65847123f6cebc150dbe1a026690bf9887062c25c2941747fef242`. Its implementation was not changed, regenerated or copied from Astra. The next observed failure is candidate behavior under deterministic tests, not another verifier timeout.

## 16. Frozen acceptance

**Frozen acceptance FAIL** for the preserved candidate. This is labeled [POST_HOC_CANDIDATE_VERIFICATION](HIVE-TRANSITION-004C/evidence/POST_HOC_CANDIDATE_VERIFICATION.json). The full Gradle gate was not run by these targeted replays. No autonomous J001 success, retroactive TRANSITION-003 success or previous PASS reuse is claimed.

## 17. Live-model decision and frontier

**No model calls.** The preserved candidate is sufficient to answer this infrastructure experiment. Even if a later live trial becomes justified, it is not automatic and was not run here.

| Experiment | Furthest verified transition |
|---|---|
| FACTORIAL-002 | Mostly planning; worker/edit preflight in 2/16 |
| TRANSITION-001 | Ownership validation |
| TRANSITION-002 | Ownership validation with complete input |
| TRANSITION-003 | Executable edit -> verifier timeout |
| TRANSITION-004 | Timeout localized to shared reconstruction |
| TRANSITION-004B | Reconstruction reused -> compileJava marker |
| TRANSITION-004C | Current main/test compilation -> frozen JUnit decisions in verifier-only replay |

## 18. Unchanged safety properties

The final audit checks **8427 prior files unchanged**, baseline/approved-cache/image identities, unchanged candidate trees, unchanged attestation and tested source, readonly mounts and absent containers after all controls. Scope/context/ownership controller files are byte-identical to 004. Targeted/full command ASTs and frozen-report/source-integrity functions are identical. Downloaded-input validation remains; new seed validation adds checks. Timeout still fails, teardown remains, and the 240-second subprocess budget is unchanged. [Audit](HIVE-TRANSITION-004C/evidence/final-audit.json).

## 19. Falsification criteria and remaining uncertainties

- Seed compatibility depends on a reviewed host attestation and immutable build/tool inputs; unbound reconstruction inputs, application classes in a seed or changed source/config outside the attested independent scope invalidate reuse. No universal auto-discovery claim is made.
- Thread samples are sparse and briefly attach to the JVM. They locate actual phases, not a complete profiler trace. No precise javac-return instant is claimed for initial timeouts.
- Download materialization and pre-compile classpath fingerprinting remain significant; timing varies. A later normal control exceeding 240 seconds would require renewed localization, not automatic budget growth.
- Full compilation must continue rejecting malformed source and preserving all frozen decisions. Missing classes/tests, reused candidate outputs or altered assertions would invalidate the repair even if faster.
- One preserved candidate and two final controls do not establish improved autonomous software success rates. The frozen factorial remains unchanged.
- The missing ordinary-ASCII requirement in the TRANSITION-003 worker contract remains a separate [TRANSITION-005 hypothesis](HIVE-TRANSITION-004C/deferred-transition-005.md). No semantic-fidelity repair is made here.

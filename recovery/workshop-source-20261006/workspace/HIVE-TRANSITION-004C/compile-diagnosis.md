# Pre-additional-repair diagnosis

Classification: **MIXED_RUNTIME_COST**.

This artifact is written after both production-seeded controls and before any performance change beyond attested NFRT reuse.

## Direct evidence

`seeded-baseline-02` and `seeded-preserved` both fail the unchanged 240-second deadline (240.044 / 240.055 seconds from Docker launch). Gradle begins at 94.116 / 104.867 seconds. Verified downloaded-input materialization consumes 72.616 / 81.735 seconds; attested private seed verification/copy consumes 6.444 / 6.866 seconds. The initial Python API integration failure is excluded from this comparison and retained separately.

Both controls hit the NFRT seed and enter `compileJava` actions with the same **49 main sources, 88 classpath entries / 95,249,358 bytes, no annotation processors, no custom compiler arguments, fork=false, incremental=true**, pinned Java 21. The task graph and command/acceptance selector remain unchanged.

Baseline JVM samples at approximately 180 and 225 seconds show `IncrementalResultStoringCompiler.storeResult -> CurrentCompilationAccess.getClasspathSnapshot -> DefaultClassSetAnalyzer`, with cache queue and ZIP read/analysis work. The preserved candidate's 180-second sample is still in Gradle ABI/classpath fingerprinting before compile actions; its 225-second sample shows the same **post-compilation incremental result storage** as the baseline. At 213 seconds its private workspace already contains **118 main .class files / 612,999 bytes**, zero test classes and no generated Java sources. This is current-run output, not reused output.

The exact Gradle 9.2.1 source confirms that `IncrementalResultStoringCompiler.execute` calls the compiler delegate before `storeResult`; `storeResult` analyzes output and dependency classpaths and writes previous-compilation data. Consequently the late samples establish that compilation had returned, while the Gradle task itself had not completed. They do not establish the exact instant javac returned or a continuous profile of every intervening millisecond.

Container observations show no OOM event, no memory-limit event, no swap, no network IO and running, unpaused containers. Late memory is about 1.8 GiB / 4 GiB. Active Gradle CPU and different advancing stacks contradict an idle deadlock. Read-only dependency mounts are **9p/DrvFS**, while private project/cache outputs are **tmpfs** (`runtime-observation-early.json`). Late stacks include ZIP reads over dependency JARs. This supports filesystem overhead as a contributor, not a precise attribution of every second to 9p.

## Supported defect and narrow proposed repair

The disposable verifier requests fresh full work with `--rerun-tasks --no-build-cache`, clears project outputs, and never reuses candidate compilation history. Nevertheless JavaCompile's default incremental=true creates dependency analysis and previous-compilation state after javac. That state has no consumer across verifier instances and is deleted before the full clean gate. Building it on this critical path is unnecessary verifier work.

Set JavaCompile `options.incremental=false` through a host-owned private init script for the isolated verifier. Gradle's supported `performFullCompilation` path still supplies all stable sources to the same toolchain compiler. Keep every source, classpath dependency, test selector, assertion, gate command and resource limit unchanged. Apply to JavaCompile tasks generally, including tests, not a named task or source file. No compiled output or Gradle history is seeded.

Do not change downloaded-input materialization yet. It is material and crosses 9p, but native artifact timestamp writes make a blanket read-only replacement unsafe. Record finer inventory/copy timing in final controls. No timeout change is justified.

## Competing explanations and falsification

- Candidate-induced hang: weakened by baseline timeout and shared late stack. Supported instead if only the candidate stalls after identical infrastructure reaches tests. Neither control ran the candidate method.
- Inherently expensive javac: late stacks are after compiler return; a full-compilation control could falsify the prediction if it spends the deadline inside javac rather than incremental storage.
- Heap/CPU limits or filesystem overhead alone: may contribute, but memory events show no exhaustion and the identified avoidable post-work is concrete. No limits are changed. Remaining latency after removing incremental bookkeeping stays measurable.
- Incorrect NFRT seed: all hashes/provenance checked and all ten nodes hit. A cache-key/input mismatch or candidate namespace in an intermediate falsifies seed validity and must reject verification.
- Proposed repair: falsified as a sufficient improvement if final fresh controls still fail to reach meaningful test results within 240 seconds. Incorrect-source acceptance, changed frozen assertions, missing full compilation, or reused candidate classes would invalidate it, even if faster.

## Sources

`evidence/timings.json`; both controls' `gradle-diagnostics.json`, `diagnostics/jvm-state-*.json` and event logs; `seeded-preserved/runtime-observation-late.json`; pinned [Gradle result storage](https://raw.githubusercontent.com/gradle/gradle/v9.2.1/platforms/jvm/language-java/src/main/java/org/gradle/api/internal/tasks/compile/incremental/IncrementalResultStoringCompiler.java) and [JavaCompile full/incremental branches](https://raw.githubusercontent.com/gradle/gradle/v9.2.1/platforms/jvm/language-java/src/main/java/org/gradle/api/tasks/compile/JavaCompile.java), also saved with SHA-256 under `evidence/upstream/gradle`.

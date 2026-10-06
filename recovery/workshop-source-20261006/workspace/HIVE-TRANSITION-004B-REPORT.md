# HIVE-TRANSITION-004B — Minecraft Artifact Reconstruction

**Finding: avoidable per-candidate reconstruction is demonstrated for the frozen J001 source-edit scope.** Minecraft/NeoForge artifacts are required compilation dependencies. Their expensive reconstruction does not depend on the authorized Java edit. Hive currently discards a reusable intermediate cache before each candidate verification.

This is a diagnostic finding, not a production repair or a J001 success. No model calls were made, the 240-second timeout was unchanged, and no verification assertion or task was removed. The original experiments remain immutable.

## Why the task is on the critical path

The pinned M3.2 build uses ModDevGradle **2.0.147**, NeoForm Runtime **2.0.31**, NeoForge **21.1.251**, Gradle **9.2.1**, and the same Java 21 verifier image as TRANSITION-003/004.

The actual Gradle task-graph probe recorded this dependency path:

```text
createMinecraftArtifacts → compileJava → classes → compileTestJava → test
```

The frozen JUnit selector limits which tests execute. It does not remove the need to compile the project's main source set, whose classpath includes the Minecraft/NeoForge JAR. ModDevGradle attaches the artifact-producing task's outputs to the compilation and runtime configurations. Skipping this task with `-x`, or compiling only the edited source outside the existing gate, would not be the measured remedy.

The two requested artifact outputs are `build/moddev/artifacts/neoforge-21.1.251.jar` and `neoforge-21.1.251-client-extra-aka-minecraft-resources.jar`. They contain dependency classes/resources, not the candidate's compiled mod.

Evidence: [baseline task inputs and graph](HIVE-TRANSITION-004B/evidence/runs/inputs/baseline-inputs.json), [candidate task inputs and graph](HIVE-TRANSITION-004B/evidence/runs/inputs/preserved-inputs.json), and the pinned [ModDevArtifactsWorkflow implementation](HIVE-TRANSITION-004B/evidence/upstream/moddev-gradle/net/neoforged/moddevgradle/internal/ModDevArtifactsWorkflow.java), especially `create` and `addToSourceSet`.

## What changes with this candidate

Two dry-run probes compared the frozen baseline and preserved TRANSITION-003 edit. Both had **identical actual reconstruction properties, 131 artifact-manifest entries and artifact-file hashes, the NFRT executable input, dependency graph, and requested outputs**, after normalizing only their private project-directory names. None of the declared reconstruction inputs was under the project's `src/` tree. Both reported native caching enabled.

The recorded scalar inputs include the NeoForge coordinate, Java executables, mapping options, transform-validation options, and binary-reconstruction flags. Access-transformer, interface-injection, and Parchment inputs can matter for other builds. Here the sole authorized write is an application Java file, and it does not change those inputs.

The probe ran `--dry-run` with a diagnostic init script and executed no build tasks. Its successful exit is **input evidence only**, never an acceptance result. [Comparison](HIVE-TRANSITION-004B/evidence/input-comparison.json), [probe outputs](HIVE-TRANSITION-004B/evidence/runs/inputs/probe-results.json).

## Why Hive reconstructs the same dependencies

The verifier creates a fresh private Gradle home and supplies only the downloaded NeoForm `artifacts` and `assets` trees. `workshop/hive_jvm.py::_external_build_input_profile` explicitly excludes generated `intermediate_results`. The container runner copies the approved downloads, clears project build outputs, and invokes the unchanged `--rerun-tasks --no-build-cache` gate.

There are two distinct cache mechanisms:

| Mechanism | Current behavior |
|---|---|
| Gradle task history/build cache | Fresh project state plus explicit rerun/no-build-cache prevents candidate compilation and test reuse |
| NFRT intermediate cache | Enabled by the pinned plugin, but Hive gives each invocation an empty intermediate directory |

The pinned `CreateMinecraftArtifacts` class is annotated `DisableCachingByDefault` because it implements its own caching. It passes `--disable-cache` to NFRT only when its separate `enableCache` property is false. The probe confirms this property is true. Therefore merely deleting `--no-build-cache` is neither necessary nor the demonstrated fix.

The repeated work observed in TRANSITION-004—strip, merge mappings, merge client/server, rename, binary patch, apply development transforms, and inject NeoForge—is dependency preparation. “Without recompilation” in the plugin log means it uses a binary transformation path for Minecraft; that path still performs substantial work when its intermediate cache is empty.

Sources: [Hive cache profile](HIVE-TRANSITION-004/repaired-workshop/workshop/hive_jvm.py), [unchanged verifier runner](HIVE-TRANSITION-004/repaired-workshop/verification/jvm_runner.py), [CreateMinecraftArtifacts](HIVE-TRANSITION-004B/evidence/upstream/moddev-gradle/net/neoforged/nfrtgradle/CreateMinecraftArtifacts.java), [NeoFormRuntimePlugin](HIVE-TRANSITION-004B/evidence/upstream/moddev-gradle/net/neoforged/nfrtgradle/NeoFormRuntimePlugin.java).

## The reusable material already exists

The approved baseline-priming cache `e5a7c314b902` contains **22 intermediate files totaling 163,178,447 bytes**, representing ten reconstruction nodes. All are already covered by its sealed complete priming inventory. The priming candidate hash equals the frozen baseline hash. Every generated file matched its recorded SHA-256; no cached JAR contained `dev/atmcompanion/` entries.

NFRT derives a node key from input-content and action/tool components. File paths retained as annotations do not enter the key. All ten saved keys were independently recomputed successfully from their recorded components. `CacheManager.restoreOutputsFromCache` locates outputs by node key, and NFRT marks a hit before running the node action. It updates cache-marker timestamps, so a reusable seed must be copied to private writable storage rather than exposed as a shared writable cache or naively mounted read-only in place.

NFRT's existence-based cache restore is **not a security attestation**. The diagnostic separately verified the immutable manifest and every copied file's SHA-256. A production policy must retain that integrity check.

Evidence: [generated inventory](HIVE-TRANSITION-004B/evidence/native-generated-inventory.json), [seed manifest](HIVE-TRANSITION-004B/evidence/seed-manifest.json), [original priming provenance](HIVE-TRANSITION-004B/evidence/priming-provenance.json), [recomputed keys](HIVE-TRANSITION-004B/evidence/cache-key-audit.json), [CacheKey](HIVE-TRANSITION-004B/evidence/upstream/neoform-runtime/net/neoforged/neoform/runtime/cache/CacheKey.java), [CacheManager](HIVE-TRANSITION-004B/evidence/upstream/neoform-runtime/net/neoforged/neoform/runtime/cache/CacheManager.java).

## Bounded diagnostic intervention

A [pre-probe diagnosis](HIVE-TRANSITION-004B/diagnosis-before-probes.md) recorded the hypothesis and falsification conditions before runtime measurements. A diagnostic overlay copied only the attested native intermediates into each fresh verifier's private tmpfs cache. It did not supply project `build/`, Gradle task history, application/test classes, JUnit reports, or previous pass/fail decisions.

The original verifier runner remains unchanged. In the diagnostic copy, the only replaced function is `_copy_external_build_inputs`: it first runs the original downloaded-input validation/copy, then adds the separately hash-checked seed. The task invocation and every gate/report/source-integrity function are unchanged. Each replay retained the same pinned image, network-disabled isolation, CPU/memory/PID limits, frozen class/three-case requirement, source protection, and **240-second outer deadline**. Seed-copy time is inside that deadline.

The bounded campaign comprised one input-probe container and two verifier-only containers. It never ran a model or promoted a candidate. [Diagnostic harness](HIVE-TRANSITION-004B/run_probes.py), [seed hook](HIVE-TRANSITION-004B/seed_hook.py), [preparation identities](HIVE-TRANSITION-004B/evidence/preparation.json).

## Measured result

| Verifier-only replay | Downloaded-input copy | Intermediate-seed copy | Before Gradle | NFRT reported runtime | Outer result | Last observed task |
|---|---:|---:|---:|---:|---|---|
| Frozen baseline, seeded | 72.900s | 2.999s | 89.312s | 6.98s | Timeout at 240.048s | `compileJava` |
| Preserved edit, seeded | 75.023s | 3.525s | 92.014s | 7.51s | Timeout at 240.043s | `compileJava` |

“Before Gradle” already includes both copy columns. NFRT's own runtime is narrower than the whole Gradle task, configuration, or container duration. Both Gradle processes were interrupted by the outer deadline; their final durations and compilation results are unknown. Neither reached an observed `compileTestJava`/`test` marker, frozen acceptance result, or full gate. Both exact containers were removed and independently confirmed absent.

The furthest verified transition in these **post-hoc diagnostic replays** is successful dependency-artifact creation → application compilation attempted. This does not modify TRANSITION-003/004's classifications. The late baseline process sample showed the container running, not paused or OOM-killed, with an active Gradle JVM; it does not localize the remaining time within Java compilation or its preparation.

Raw outputs: [baseline](HIVE-TRANSITION-004B/evidence/runs/baseline/child-stdout-plain.log), [preserved candidate](HIVE-TRANSITION-004B/evidence/runs/preserved/child-stdout-plain.log). Exact commands, phase events, timeout and process-state evidence are in each run's diagnostics directory. [Machine-readable timing comparison](HIVE-TRANSITION-004B/evidence/timings.json).

In both seeded runs, NFRT reused all ten nodes: `stripClient`, `mergeMappings`, `extractServer`, `stripServer`, `merge`, `rename`, `binaryPatch`, `copyUnpatchedClasses`, `applyDevTransforms`, and `binaryWithNeoForge`. It completed in **6.98 seconds for baseline** and **7.51 seconds for the preserved edit**. Candidate compilation was still required afterward.

The prior five unseeded TRANSITION-004 runs timed out while artifact construction was still the last observed Gradle task. Those historical outcomes remain failures. Their exact phase timings and the new diagnostic timings are different kinds of measurement; no general speedup factor is claimed.

An interim read-only integrity scan overlapped the preserved replay's setup. Its recorded interval was at least 16:45:11.624–16:45:28.306 UTC and it hashed the 5,137 approved-cache files. That may perturb I/O and cache warmth, so candidate wall-clock timing is not treated as a clean paired performance estimate. The baseline replay was not overlapped by that scan. Actual identical inputs, attested content, and ten observed cache hits in each run remain direct reuse evidence. No extra replay was added to hide the limitation. [Measurement caveat](HIVE-TRANSITION-004B/evidence/measurement-caveat.json).

## Conclusion and repair boundary

For this frozen source-only scope, **reconstruction is unnecessary per candidate; dependency materialization is necessary**. Hive's conservative cache-transfer policy puts invariant dependency reconstruction on every fresh verifier's critical path. The bounded seed experiment demonstrates that NFRT can avoid those repeated transformations with unchanged rerun/no-build-cache flags and unchanged candidate-verification requirements.

No production caching repair was installed in this task. The smallest supported repair direction is to admit a separately attested, baseline-generated NFRT intermediate seed into each private verifier cache. That policy needs explicit binding to the approved platform/tool/build inputs and regeneration on relevant changes. It must never reuse candidate compilation, test reports, or acceptance results. Changes to build configuration, dependencies, mappings, access transformers, interface injection, or tool versions can legitimately require new reconstruction; this finding is not a blanket license to reuse outputs across arbitrary projects or write scopes.

The intervention demonstrates removal of one repeated dependency workload. It does not establish that the complete verifier can finish under the current budget, and it is not an autonomous software-task success. No timeout increase is supported or made here.

## Integrity and remaining uncertainties

- Prior evidence, frozen baseline, prepared candidate/sanitized source, and all 5,137 approved-cache files were checked for unchanged content. Runtime safety functions in the diagnostic overlay were compared by AST. [Final integrity audit](HIVE-TRANSITION-004B/evidence/integrity-audit.json).
- The first input-probe cleanup check looked for capitalized `No such`; this Docker CLI returned lower-case `no such`. A follow-up inspect confirms the container was absent. The initial conservative result and follow-up are both retained; only diagnostic matching was corrected. [Cleanup follow-up](HIVE-TRANSITION-004B/evidence/runs/inputs/cleanup-followup.json).
- No production regression suite was rerun because production code was not changed. These are runtime probes and integrity checks, not a new claim of 453 passing tests.
- Published source archives were fetched for the exact installed plugin/runtime versions; their URLs and SHA-256 values, alongside the actual cached binary hashes, are preserved in [upstream provenance](HIVE-TRANSITION-004B/evidence/upstream-provenance.json). Verification containers remained offline.
- Identical input snapshots and native hits establish reuse for this build and scope. They do not prove output reproducibility across unpinned Java/platform/tool combinations or validate a general production cache policy.
- The separate planner→worker loss of the ordinary-ASCII requirement remains outside this investigation.

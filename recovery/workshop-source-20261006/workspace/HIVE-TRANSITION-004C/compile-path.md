# Pinned compile path

Before runtime observations, the frozen build establishes the following (later measurement additions are labeled below).

The task graph captured in TRANSITION-004B is `createMinecraftArtifacts -> compileJava -> classes -> compileTestJava -> testClasses -> test`. The frozen selector filters JUnit execution; it does not limit main-source compilation to SnapshotFormatter. `inspect_build.py` records 49 main Java files, 29 pre-existing JUnit-source files, six gametest, three questtest and four packtest files. The injected frozen test adds one JUnit source. These source sets are distinct; the targeted test task does not select the game-server gates.

`build.gradle` applies java-library and ModDevGradle 2.0.147, selects Java 21 and NeoForge 21.1.251, and adds four optional compile-only FTB/Architectury dependencies. It declares no annotation processors, custom Java compiler arguments, generated main-source task or compiler fork. Runtime values must be confirmed by the task-action observation; absence of a build declaration alone does not prove a plugin adds none.

ModDevGradle's pinned `ModDevArtifactsWorkflow.addToSourceSet` extends each compile classpath with `modDevCompileDependencies`. Its `createMinecraftArtifacts` task materializes the game/dependency JARs. NFRT intermediate hits avoid reconstructing those JARs; they do not compile this project's Java classes. A `compileJava` console marker is not proof of compiler entry: dependency resolution, task-input snapshotting and other preparation may occur around that marker.

The unchanged gate uses `--rerun-tasks --no-build-cache`, a fresh project without `.gradle` history or classes, two Gradle workers and `-Xmx768m`. Even if `options.incremental` remains true, no previous candidate compilation state exists to reuse; main compilation starts fresh. No candidate compilation cache is introduced.

Instrumentation writes an observation-only init script into the private Gradle home. It records settings/projects/graph events and JavaCompile doFirst/doLast events with sources, classpath, arguments, processor path, compiler installation and incremental/fork flags. A doFirst event means the task action sequence was entered, not that javac was entered. Bounded `/proc`, cgroup and `jcmd Thread.print` samples identify actual JVM activity. Thread attachment briefly observes a running JVM and is labeled; it changes no task options. Diagnostic data cannot affect acceptance.

Evidence: frozen baseline build.gradle and gradle.properties; `evidence/build-inventory.json`; TRANSITION-004B `evidence/runs/inputs/baseline-inputs.json`; pinned ModDevGradle source in TRANSITION-004B `evidence/upstream/moddev-gradle/net/neoforged/moddevgradle/internal/ModDevArtifactsWorkflow.java`; production `verification/jvm_runner.py:GRADLE_DIAGNOSTICS` and `workshop/verifier_trace.py:JVM_SAMPLE`.

## Measured initial controls

Both production-seeded controls report 49 main-source files, 88 compile-classpath entries totaling 95,249,358 bytes, no annotation processor path, no custom compiler arguments, fork=false, incremental=true and `/opt/java/openjdk` as the compiler installation. A direct private-workspace observation in the preserved-candidate run found 118 compiled main classes and no generated Java sources; no test classes existed yet.

The baseline's late samples and the candidate's final late sample are inside **post-compilation** `IncrementalResultStoringCompiler.storeResult`, traversing the dependency classpath through `DefaultClassSetAnalyzer` and ZIP reads. The candidate's earlier sample additionally exposes Gradle ABI/classpath fingerprinting before task actions. These are distinct from source discovery, javac startup or candidate-method execution. No second NFRT reconstruction was observed inside compilation.

The pinned Gradle source explicitly selects full compilation when `options.incremental` is false, using the same stable sources/toolchain. Its incremental wrapper otherwise records class dependency state after the delegate compiler returns. That state is discarded by this verifier's fresh isolation. The additional repair therefore disables incremental compilation bookkeeping through a host-owned private init script; it does not skip JavaCompile or any test. The real pinned-Gradle regression compiles a valid synthetic class and rejects malformed Java after clearing the previous class (`evidence/regression/complete-02/actual-gradle-result.json`).

See [the pre-repair diagnosis](compile-diagnosis.md) for falsification criteria and source references; final replay action durations and outcomes are recorded in `evidence/timings.json` and the final report. Thread snapshots establish phases at sample times, not exact continuous durations for every internal Gradle operation.

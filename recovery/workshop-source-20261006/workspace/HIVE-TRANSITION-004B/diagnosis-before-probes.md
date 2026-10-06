# Preregistered diagnosis before runtime probes

The current evidence supports avoidable reconstruction for J001's authorized source-only edit, rather than a need to regenerate Minecraft for every candidate. ModDevGradle 2.0.147 creates a compile/runtime dependency before compiling the mod. Its reconstruction inputs are platform/tool coordinates, access transformers, interface-injection data, mapping data and flags. The Java application source is compiled afterward. NFRT 2.0.31 implements its own content-keyed intermediate cache; Gradle's `--no-build-cache` does not disable that cache.

Hive deliberately supplies only native downloaded `artifacts` and `assets`. It constructs a fresh Gradle home, omits `intermediate_results`, removes project build outputs, and reruns tasks. The original approved baseline-priming cache already contains 22 intermediate files (163,178,447 bytes), present in the sealed complete priming inventory. None of its JARs contains the application's package. These facts are sufficient to motivate a bounded diagnostic, not to promote a new production cache policy.

Predictions:

1. A no-execution task-graph/input probe will show identical reconstruction inputs for the frozen baseline and preserved TRANSITION-003 edit, and a dependency from candidate compilation to artifact creation.
2. Seeding only the sealed baseline intermediate cache into each fresh private Gradle home will produce NFRT cache hits despite unchanged `--rerun-tasks --no-build-cache` flags.
3. The seed will contain no candidate classes, Gradle task history, compiled test classes, JUnit reports or prior acceptance verdicts. Candidate compilation and all frozen assertions must still run.

Falsification: source edits alter the actual reconstruction input set; native cache keys differ despite the same platform inputs; the seed contains candidate outputs; or the task still reconstructs the same expensive nodes with matching validated cache entries. A timeout after cache hits does not falsify independence, but would limit a claim that this alone resolves the verifier budget.

Planned maximum: one container with two dry-run input probes, followed by at most two seeded verifier-only replays (baseline and preserved candidate). Each container call retains a 240-second outer bound. No model calls, timeout increase, network-enabled verifier, change to acceptance tests, production edits, or mutation of historical caches. All changes to apparatus are explicit diagnostic overlays in this new directory. The no-seed comparison is the existing TRANSITION-004 measurements.

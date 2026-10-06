# HIVE-NFRT-ATTESTATION-002

**Classification: FACTORIAL_READY**

The isolated controller now supports a host-attested class of independently compiled main Java sources, instead of a one-file exception. All four frozen task scopes are compatible. Qualification remains bounded to the pinned build and the new manifest; it is not permission to reuse dependencies across arbitrary Gradle configurations.

No task model, factorial trial, promotion or historical rescore occurred. HIVE-FACTORIAL-003 remains permanently `EXPERIMENT_INVALID`.

## 1. Prior blocker

The v1 manifest permitted only the source variation measured in TRANSITION-004B. HARNESS-QUALIFICATION-001 therefore accepted J001 but rejected J002–J004 before unsafe reuse. That was a conservative host-policy limitation, not measured dependency sensitivity to those other Java files. The qualified harness and all historical records remain immutable.

## 2. Current attestation policy

[Current-policy reconstruction](HIVE-NFRT-ATTESTATION-002/current-policy.md) was written before production edits. `configured_seed` binds baseline, image/JDK, Gradle profile, downloaded-input manifest, priming provenance, complete module/tool bytes and source/config inventory. `verify_seed` checks membership, type, size/hash, native key components and forbidden application namespaces; `private_copy` validates before and after fresh private copying.

The old failure arose at the source-inventory comparison: every file outside the attested single-file list had to remain byte-identical, and all file membership was fixed. The original v1 manifest is preserved and its semantics remain supported.

## 3. Reconstruction dependency model

[Machine-readable model](HIVE-NFRT-ATTESTATION-002/reconstruction-dependency-model.json) and [readable explanation](HIVE-NFRT-ATTESTATION-002/reconstruction-dependency-model.md) record all ten nodes, dependencies, action identities, input content hashes, options and output hashes. The pinned versions are ModDevGradle 2.0.147, NFRT 2.0.31, NeoForge 21.1.251, Gradle 9.2.1 and the approved Java 21 image.

Every saved key was independently recomputed. Referenced file SHA-1 values and archive-entry component hashes were also recomputed using the pinned `ZipContentHasher` algorithm, alongside whole-file SHA-256 identities. The graph includes `stripClient`, `extractServer`, `stripServer`, `mergeMappings`, `merge`, `rename`, `binaryPatch`, `copyUnpatchedClasses`, `applyDevTransforms`, and `binaryWithNeoForge`.

Some external tool components are coordinates rather than byte hashes. Hive's stronger complete tool/module/download hashing is retained. Native key equality or a cache hit is never used as sole attestation.

The pinned `ModDevArtifactsWorkflow`, `CreateMinecraftArtifacts`, `NeoFormRuntimeTask`, `DataFileCollections`, `RunNeoFormCommand`, `NeoFormEngine` and action/key implementations establish the direction: reconstruction outputs feed application compilation. The approved reconstruction task has no application compilation prerequisite and no application Java source input. Explicit transform/mapping inputs can point to arbitrary files, and main resources can contain an automatically discovered access transformer.

## 4. Source-sensitivity probes

Eighteen fresh baseline-derived cases were measured using offline `--dry-run createMinecraftArtifacts`; no compilation or tests executed during these probes. See [probe table](HIVE-NFRT-ATTESTATION-002/source-sensitivity.md), [raw results](HIVE-NFRT-ATTESTATION-002/evidence/input-probes/results.json), and [analysis](HIVE-NFRT-ATTESTATION-002/evidence/sensitivity-analysis.json).

Main Java changes across all four task scopes, unrelated Java files and a new package/class left measured reconstruction input identity unchanged. Each retained the same 131 artifact identities/hashes, tool executable input, graph, outputs and optional-input collections. Access-transformer addition, interface injection, Parchment configuration/data and a reconstruction output option changed measured inputs. The changed NeoForge version was unavailable offline; its identity is explicitly **unknown/unresolved**, not treated as equal.

The unchanged-input rows' ten-key identities are an inference from fixed inputs and pinned action implementations. Actual fresh ten-node cache hits are separate real-control evidence below. No NFRT execution is claimed for a dry run.

## 5. Safe, unsafe and unknown variation classes

| Input category | Changes NFRT reconstruction identity? | Seed reuse allowed? |
|---|---|---|
| Qualifying main application Java | No in all measured content/package-addition probes; absent from reviewed reconstruction determinants | Yes, only within the host-attested main roots of the fixed build |
| Test Java | No for the harmless probe | No; retained fixed in this minimal policy |
| Resources | Ordinary added resource: no; automatically discovered AT: yes | No; all resource changes remain bound |
| Build configuration | Comment: no; reconstruction option: yes; arbitrary edits unknown | No |
| Dependencies | Probed compile-only addition: no; changed NeoForge unresolved offline; reconstruction dependencies participate in graph/keys | No |
| Mappings/Parchment | Official/NeoForm mappings are key inputs; Parchment probe changes inputs | No |
| Access transformers | Yes, directly measured and keyed in development transforms | No |
| Interface injection | Yes, directly measured and keyed in development transforms | No |
| Tool/runtime identities | Actual bytes affect results; host bindings reject identity/hash changes even where native keys use coordinates | No |

`SAFE_INDEPENDENT_VARIATION` is the reviewed main-source class, including multiple files and membership changes. `RECONSTRUCTION_RELEVANT` covers actual graph/artifact/tool/transform/mapping inputs. `CONSERVATIVELY_UNKNOWN` covers remaining repository changes. A particular no-change probe is not blanket authorization for its whole category.

## 6. Sealed pre-edit diagnosis

[diagnosis.md](HIVE-NFRT-ATTESTATION-002/diagnosis.md) was sealed at `2026-10-06T02:43:45.118240+00:00`, before any production modification. Its hash is `bdc1a6a46409e505a65bd5e2884c78957323dc0e8bee11c5ce248f871b1aae0e`. The [seal](HIVE-NFRT-ATTESTATION-002/evidence/diagnosis-seal.json) binds the diagnosis, dependency model, sensitivity analysis and original source inventory.

The source inventory was demonstrated unchanged at sealing. Declared task inputs alone were not treated as proof: the exact build and pinned plugin implementation were reviewed for undeclared source reads and optional input discovery.

## 7. Generalized policy

The new `hive-nfrt-seed-v2` manifest uses `independent_source_policy.kind = reviewed-main-java-v1`, with roots measured from the main Java source set. For this approved build the root is `src/main/java`. No task ID or benchmark filename selects eligibility.

Only regular `.java` files within those attested roots may change, be added or removed. Every other repository path/hash remains fixed. The host also retains all image/profile/provenance/module/download/seed checks. Reconstruction input overlap with an allegedly independent root is rejected, including Java-named transform inputs. Missing, contradictory or mixed v1/v2 independence evidence fails closed.

The new approved manifest is [approved-nfrt-seed-v2.json](HIVE-NFRT-ATTESTATION-002/evidence/approved-nfrt-seed-v2.json), SHA-256 **`9ec38a4912981e3e34e0ee4bbeb7c8dfa04a6d23beba3b49829a43e5b2a124a3`**. It reuses the same 22 files / 163,178,447 bytes and the same baseline priming identity. It does not regenerate or relax the seed inventory. Host configuration must explicitly select this manifest and digest; existing v1 configuration does not silently acquire broader authority.

## 8. Production implementation

The only production Python change is `verification/nfrt_seed.py` in the new isolated source tree. It adds v2 schema recognition and `independent_source_roots`, then compares inventories after excluding only the reviewed class. Existing v1 file-list semantics remain intact. Duplicate source-inventory paths and ambiguous policies are rejected.

Seed-byte validation and private-copy functions are unchanged. Planner/worker/reviewer/provider code, context settings, write scopes, verification commands, frozen selectors/assertions, source-integrity routines, timeouts, correction budgets and promotion policy are byte-identical to the frozen original. [Patch](HIVE-NFRT-ATTESTATION-002/production-and-tests.patch).

## 9. Adversarial regression tests

The targeted NFRT suites passed **93 tests**. New tests admit existing/unrelated/multiple/new-package source changes and reject resource/config/test/build-source additions, changed tool/profile/download identities, source/input overlaps, missing or contradictory evidence, corrupt/missing/extra seed files, application/test/generated class contamination and build/report/history contamination. Private-copy mutation remains isolated from the approved seed. Source compatibility may accept invalid Java text; fresh compilation must still reject it—compatibility is not correctness.

The four actual benchmark write scopes are additionally tested by separate host preflight, rather than encoded in production authorization. [NFRT JUnit](HIVE-NFRT-ATTESTATION-002/evidence/seed-unit-tests.xml).

## 10. Four-task scope matrix

| Task scope | Compatible after generalized policy? |
|---|---|
| J001 | yes |
| J002 | yes |
| J003 | yes |
| J004 | yes |

[Scope matrix](HIVE-NFRT-ATTESTATION-002/factorial-scope-matrix.md) and [exact isolated preflight records](HIVE-NFRT-ATTESTATION-002/evidence/scope-preflight/matrix.json). Each candidate is a fresh baseline copy with harmless comments in precisely its authorized source files.

## 11. Real verifier controls

All controls use the actual targeted verifier and byte-identical qualified recorder, new isolated stages, the same frozen J001 selector/case requirement, pinned image/JDK, offline configuration, approved downloaded inputs, private seed and unchanged 240-second deadline. No model generated these fixtures.

| Control | Frozen decision | Cases / failures / errors / skipped | NFRT hits | Fresh main/test compile | Native invocations | Host seconds |
|---|---|---|---:|---|---:|---:|
| baseline | FAIL | 3 / 1 / 0 / 0 | 10 | yes | 1 | 169.443 |
| known-good-J001 | PASS | 3 / 0 / 0 / 0 | 10 | yes | 1 | 139.997 |
| outside-and-added-main | FAIL | 3 / 1 / 0 / 0 | 10 | yes | 1 | 140.150 |
| negative-java-plus-access-transformer | preflight rejection | 0 / 0 / 0 / 0 | 0 | not invoked | 0 | 15.343 |

The known-good fixture is the preserved run `4574db69cea0` source; no historical PASS is reused. The outside-source control changes an unrelated main file and adds `qualification.independence.FreshCompilationProbe`. That new file appears in actual compilation observations. Observed source counts: baseline: main=49, test=30; known-good-J001: main=49, test=30; outside-and-added-main: main=50, test=30.

Each positive compatibility control copies exactly 22 attested files into a new private cache, hits all ten NFRT nodes, enters and completes main/test compilation with `incremental=false`, and executes the frozen tests. Commands retain `--rerun-tasks`, `--no-build-cache`, and `--offline`. A task marker alone was not accepted as proof of compilation completion.

All independently observed stage/origin/frozen-test hashes remained unchanged. The known-good control emits an explicit successful native source-immutability row. For the two behavioral FAIL controls, native source-integrity success is **inferred from completed control flow**, not an emitted PASS row: unchanged `verification/jvm_runner.py:683-692` checks protected digests before returning the failed test report and would append a failure on mutation; its positive row exists only on the passing branch at lines 694-700. The analysis records this distinction. An earlier audit incorrectly required that positive row on every result; [the correction and earlier audit](HIVE-NFRT-ATTESTATION-002/evidence/audit-revisions/README.md) are preserved. No verifier result was changed.

The qualified access-transformer negative control also contains a harmless Java edit to trigger the existing JVM targeted route. It returns the unchanged production preflight failure before container launch or seed use. The wrapper still calls the production entry point exactly once. It does not fabricate an outcome. [Control summary](HIVE-NFRT-ATTESTATION-002/evidence/real-controls/summary.json) and [qualified full results](HIVE-NFRT-ATTESTATION-002/evidence/real-controls/qualified-results.json).

One earlier negative fixture changed only the resource AT file. The unchanged `hive.targeted_verify` JVM branch is triggered by `.java`, `.gradle`, `.kts` or `.properties` changes; this `.cfg`-only fixture returned `passed:true, checks:[]` without calling the isolated verifier. This is a routing observation, **not** a successful verification or attestation bypass: no seed was used. It is preserved in [original controls](HIVE-NFRT-ATTESTATION-002/evidence/real-controls/results.json). A separate fresh Java-plus-AT fixture was necessary to measure NFRT rejection. No production routing change was made, and the resource-only observation is not counted as a qualified negative result. All four factorial scopes contain Java edits and take the exercised JVM route.

These are cache-policy controls and post-hoc fixture verification, not autonomous successes. The known-good fixture's fresh acceptance does not rescore its historical run. No full Gradle gate was claimed or required for these targeted cache controls.

## 12. Complete regression result

Final complete repository regression: **615 passed, 6 skipped, 0 failures, 0 errors**. The six skips are the inherited Windows symlink-privilege limitations. [Final JUnit](HIVE-NFRT-ATTESTATION-002/evidence/full-regression-final/pytest.xml), [log](HIVE-NFRT-ATTESTATION-002/evidence/full-regression-final/pytest.log).

The initial complete run is preserved: 603 passed, 6 skipped, 12 failed. Eleven failures were missing experiment-relative archived fixtures in the new isolated area; exact unchanged copies were supplied, with [provenance](HIVE-NFRT-ATTESTATION-002/evidence/regression-fixture-provenance.json). The twelfth was a historical assertion that the entire NFRT policy file could never change. It now retains exact byte checks for all other protected files and AST equality for seed type/digest/path/key/namespace/private-copy functions. Actual frozen acceptance tests were never edited. The regression was then rerun in full; real controls started only after it passed.

The inherited suite also wrote its isolated Workshop database and two demonstration snapshot directories. The final audit detected these mutable runtime artifacts; its first diff-rendering attempt stopped on the binary database rather than silently ignoring it. They were preserved under [regression-runtime-artifacts](HIVE-NFRT-ATTESTATION-002/evidence/regression-runtime-artifacts/preservation.json), the new copy's database was restored from the untouched original, and the audit was rerun. No code or test assertion changed during that cleanup, and no benchmark candidate was applied.

## 13. Harness compatibility

The original qualified `recorder.py` and `cell_harness.py` are imported without file edits. Candidate setup is bound in memory to the new isolated source; all production modules come from that tree. Every real control records exactly one wrapper invocation. The three permitted controls also have exactly one native Docker/Gradle/JUnit invocation each. The denied control has zero native launch because production preflight rejects it. Complete measurement records and candidate/test/source hashes are retained.

No instrumented-versus-uninstrumented semantic change was introduced into the qualified wrapper. Its previous PASS/FAIL/exception/timeout qualification remains unchanged; this experiment re-establishes successful native invocation under the new NFRT policy.

## 14. Factorial-readiness decision

| Criterion | Result |
|---|---|
| original source unchanged | PASS |
| historical evidence unchanged | PASS |
| baseline unchanged | PASS |
| frozen tests unchanged | PASS |
| approved environment unchanged | PASS |
| prior attestation unchanged | PASS |
| seed bytes inventory provenance unchanged | PASS |
| bounded production changes only | PASS |
| no benchmark policy logic | PASS |
| pre edit diagnosis seal valid | PASS |
| all four scopes compatible | PASS |
| complete regression passed | PASS |
| real controls qualified | PASS |
| qualified harness exactly once | PASS |
| isolated candidate integrity | PASS |

**FACTORIAL_READY** applies to a future separately identified study using this known isolated source and explicitly pinned v2 manifest. It does not start or resume a factorial. FACTORIAL-003 remains invalid; its compromised cell is not a result. No model/runtime reliability claim follows from these controls.

## 15. Files changed

Only the new `HIVE-NFRT-ATTESTATION-002/` area and this root report were written. Relative changes in the isolated source copy are:

- `tests/test_nfrt_source_policy.py`
- `tests/test_semantic_fidelity.py`
- `verification/NFRT-SEED-POLICY.md`
- `verification/nfrt_seed.py`

Supporting scripts, probes, dependency/source analysis, new attestation, regression fixtures and raw evidence reside in the same new area. The original repaired Hive source remains untouched.

## 16. Integrity audit

Original source: **162 files unchanged**. Prior evidence: **40,759 entries unchanged**. Frozen baseline hash: `230340980b85d60b7a59d3aa338dffc4447c1bb7d8df90bff4d0dbe89afe5388`. All four frozen test hashes, approved cache/provenance, original attestation and pinned image were revalidated after runtime controls.

New source tree hash: **`f495206de7fecfe5950f941826a84dfd1d81d2ceac164a1899d5eede5cd04ca7`**, computed as SHA-256 of canonical sorted JSON mapping path to SHA-256 and byte size. [Final inventory](HIVE-NFRT-ATTESTATION-002/evidence/final-source-inventory.json), [audit](HIVE-NFRT-ATTESTATION-002/evidence/final-audit.json), [host configuration](HIVE-NFRT-ATTESTATION-002/evidence/attestation-configuration.json).

Every control stage/origin and frozen-test artifact was unchanged by observation/verification. No candidate classes, task history, build directory, JUnit reports, verifier results or prior acceptance state entered the seed. No candidate was applied or promoted. Model calls: **0**. Factorial trials: **0**.

## 17. Falsification criteria

A main-source change that alters measured reconstruction inputs or node keys under the exact fixed build would falsify independence. So would an undeclared build/plugin source read, a reconstruction input overlapping the permitted roots, a changed unbound tool/artifact, candidate outputs in the seed, writable shared intermediates, skipped fresh compilation, stale JUnit data, changed frozen assertions or wrapper invocation mismatch. Each requires stopping applicability, not accepting the old cache because it hits.

## 18. Remaining uncertainties

This is a reviewed policy for this pinned build family/identity, not a universal rule for Java, NeoForge or arbitrary Gradle plugins. Finite probes supplement source/graph review; they do not establish a theorem about all builds. Other source sets, test Java, resources and arbitrary configuration edits remain conservative invalidations. Changed NeoForge resolution was intentionally left offline/unresolved. Native hits establish reuse, not general performance improvement or behavioral reliability.

Six symlink tests could not run on this Windows privilege configuration; existing link/type validation was not altered. Resource-only targeted routing returned no checks in the separate observation above; any broader routing investigation belongs to a separate task, and no complete-candidate acceptance/promotion claim is made for that fixture. No task-model workload or full new factorial was run. A future study must freeze a fresh identifier and this source/attestation configuration before measurement.

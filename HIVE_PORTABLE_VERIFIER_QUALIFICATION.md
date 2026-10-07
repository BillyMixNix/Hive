# PORTABLE-VERIFIER-001 qualification

On a fresh GitHub-hosted Ubuntu 24.04 runner, unchanged J001 reproduced
**3 cases, 1 failure, 0 errors, 0 skipped, no timeout** in 37.914 seconds.
No original host image, cache, NFRT payload, runtime installation or credential
was transferred. No model call, candidate generation, full verification or
promotion occurred. The result qualifies **FUNCTIONALLY_RECONSTRUCTED** for
this targeted baseline; the complete historical apparatus is not byte-identical.

## Reproducibility authority

| Identity | Recorded value |
| --- | --- |
| Executed Git commit | `53d411379a8d2dfaf9d926c0fe334d3c6821289e` |
| Executed Git tree | `1455ffaadeeb49dffef161108fe89d61bcb574ca` |
| Unchanged source authority | `f93a6c2f79d25d24bdea1b171cd82a6b1f336667` |
| Canonical controller tree, both commits | `2902d721388f772fe27612e9f8c367dd95106739` |
| Verifier source SHA-256 | `3b78838b8b80e44770faecf5917e4fad1d96498103d80e9c8948c1b052433af5` |
| JVM runner source SHA-256 | `bed02c0cdcb40cebb25e92d093b1be63fe2ac8f45e9c906d988c47bb6e8036ad` |
| J001 baseline SHA-256 | `230340980b85d60b7a59d3aa338dffc4447c1bb7d8df90bff4d0dbe89afe5388` |
| Frozen J001 test SHA-256 | `80c1ced02955971cc827aed4e983d9407b919f47cc3af20f457f3a0f0098f159` |
| Successful workflow run | [37666448896](https://github.com/BillyMixNix/Hive/actions/runs/37666448896) |
| GitHub metadata artifact | `11502632906`, `hive-portable-verifier-37666448896-1` |
| Downloaded artifact ZIP SHA-256 | `d46986b018074c63f121c98e5fedf96cb1546570ec3506e60c5dfb964c433316` |
| Preserved manifest SHA-256 | `13e68b42c395d12ae76630efc3952140586d7f365051bd9958df80d92bce091e` |

The [manifest](portable_verifier/evidence/REPRODUCIBILITY_MANIFEST.json) preserves
acquisition URLs and hashes, generated file inventory, runtime fingerprints,
timings, isolation, the sanitized verifier report and exact result counts.
It is the downloaded manifest, unchanged. Diagnostic path redaction occurred
before artifact creation; raw diagnostic/report digests are separately recorded.
The [evidence index](portable_verifier/evidence/INDEX.json) preserves all four
run references and downloaded artifact digests. Historical evidence is unchanged.

## Exact matches and apparatus differences

| Component | Observation | Scope |
| --- | --- | --- |
| Gradle 9.2.1 distribution | Official ZIP pin verified; 314 selected wrapper files match historical hashes | Exact selected file bytes |
| Maven/plugin dependencies | 420 upstream files match historical hashes | Exact selected file bytes |
| Native NFRT inputs | 3,894 upstream files match historical hashes | Exact selected file bytes |
| Previously URL-less binarypatcher | Official versioned Maven origin found and SHA-256 matched | Independently reacquirable; no transfer needed |
| NFRT intermediates | All 22 historical hashes match after reconstruction | Exact measured intermediate file bytes |
| Generated Gradle metadata | 210 of 215 historical hashes match | Four tables/lock files differ; DevLaunch descriptor absent |
| Global launcher index | Historical hash unavailable from its mutable URL | New deterministic 1.21.1-only index; different bytes |
| Verifier image | New image `sha256:1a1579147cf10542e3512281338615225ec424440fd3a03d712d131521485043` | Different from historical image; no exact-image claim |
| Container JDK | Verified upstream Temurin 21.0.12.1+1 archive | Historical embedded JDK bytes not separately sealed |
| Container Python/OS | Official digest-pinned Python 3.13.14 Debian image | Different apparatus; no historical OS/runtime identity claim |
| Host support | Docker 28.0.4, Linux x86-64, overlay2, cgroup v2, four CPUs, approximately 16 GB RAM | Hosted kernel, orchestration Python and filesystem recorded, not exact historical host |

The launcher replacement has SHA-256
`423dbfa580cb4431ed1d3c3dc20a8f1ea5e2b47ce4b68dc7dcd630e88518afb4`
and 348 bytes. It is derived only from hash-verified 1.21.1 metadata. The old
global index has SHA-256
`28b1e1e5d90851ce48ab935fe5644739364e262a8e8813e28e3d036aaec536ef`
and 277,187 bytes. Substituting the new discovery index is explicitly a
functional reconstruction, not retrieval of those old bytes. The unchanged
verifier's existing no-seed reconstruction path is used; the old NFRT seed
attestation and RECOVERY-002 authorization are not reissued.

The five unmatched Gradle metadata paths and both digests where available are
listed in `cache_metadata_comparison` in the manifest and the
[file-level classification](portable_verifier/evidence/ARTIFACT_CLASSIFICATION.json).
The absent DevLaunch descriptor was not necessary for this targeted J001 run;
its absence is not evidence that a full game/server gate can run.

## Preparation failures retained

| Run | Result | Correction confined to new preparation code |
| --- | --- | --- |
| [37663371269](https://github.com/BillyMixNix/Hive/actions/runs/37663371269) | Priming failed; acceptance not executed | Preserve diagnostic information |
| [37664849809](https://github.com/BillyMixNix/Hive/actions/runs/37664849809) | NFRT `downloadJson` timestamp update denied; acceptance not executed | Assign fresh cache ownership to UID/GID 65532 before priming |
| [37665497216](https://github.com/BillyMixNix/Hive/actions/runs/37665497216) | NFRT rebuilt exactly; isolated verifier reported zero cases; baseline not reproduced | Prime the unchanged JUnit runtime classpath for offline execution |
| [37666448896](https://github.com/BillyMixNix/Hive/actions/runs/37666448896) | Expected 3/1/0/0 baseline reproduced | No further experiment needed for this result |

Linux explicit timestamp updates require ownership; write permission alone was
insufficient. A fixed maintenance container uses only CAP_CHOWN, no network,
no source/test mounts and only the newly created cache. Priming and acceptance
containers continue to drop all capabilities. The preparation-only Gradle init
script resolves existing `testRuntimeClasspath`; it changes no dependency,
project source, acceptance test, task definition or verifier policy. Compiled
baseline classes from preparation are not reused by acceptance execution.

## Isolation and publication

The actual acceptance invocation used network `none`, offline Gradle, read-only
root/source/cache inputs, private tmpfs, UID 65532, all capabilities dropped,
no new privileges, 4 GB memory/swap ceiling, two CPUs and 448 PIDs. Gradle used
two workers, a 768 MB heap and two active processors. Inherited host environment
was empty. The only failed verifier check was `frozen_junit_acceptance`, with
return code 1, as expected for the defective unchanged baseline.

The controller, model behavior, prompts, provider, frozen tasks, acceptance
criteria and canonical verifier source are unchanged from the published source
authority. No hidden test was sent to a model. No API credential was needed.
Only source and metadata are published; no third-party binaries, caches,
Minecraft assets or transformed NFRT outputs are uploaded. See the
[licensing audit](HIVE_PORTABLE_VERIFIER_RECONSTRUCTION.md#licensing-and-public-artifact-policy).

## Recovery distinctions and remaining limit

This result is artifact-backed and demonstrates a portable functional recipe
for one unchanged task. It provides a narrow behavioral replication of the
known host-bound J001 failure on another host. It does not establish exact
cross-host apparatus replication, general behavioral replication of Hive,
RECOVERY-002 compliance, full-gate qualification or an API coding result.
Host-bound attestation remains host-bound.

No host-local payload is required for this functional J001 reconstruction.
For exact historical download replay, the smallest unresolved input is the
277,187-byte global launcher index: an independently accessible historical
source matching its sealed SHA-256 would eliminate that download blocker.
Transferring the old file would reproduce bytes but would not establish
independent reacquisition. A complete exact apparatus additionally needs the
old image's immutable layers/build chain, runtime acquisition provenance and
deterministic reconstruction of the five unmatched cache records. None is
silently substituted or labeled exact.

The full Gradle/game/server gate, candidate-backed execution on this apparatus,
remote API orchestration, provider comparison and repeat-run stability remain
unproven. This J001 prerequisite is ready for a separately authorized remote
API Hive qualification; it does not authorize an API request or coding run.

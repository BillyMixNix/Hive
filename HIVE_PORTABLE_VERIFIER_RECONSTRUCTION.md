# Portable verifier reconstruction (PORTABLE-VERIFIER-001)

This is a separate, model-free apparatus. Its source authority is public commit
`f93a6c2f79d25d24bdea1b171cd82a6b1f336667`. Neither RECOVERY-002 nor its host-bound
authorization is reused. The controller, provider, prompts, frozen task, baseline,
acceptance test, Gradle policy and isolated verifier source remain unchanged.

**The clean hosted J001 baseline was reproduced on 2026-10-07.** See
[the qualification report](HIVE_PORTABLE_VERIFIER_QUALIFICATION.md),
[exact bootstrap instructions](HIVE_PORTABLE_VERIFIER_REPRODUCE.md), and
[preserved manifest](portable_verifier/evidence/REPRODUCIBILITY_MANIFEST.json).
The apparatus is FUNCTIONALLY_RECONSTRUCTED, not EXACTLY_REPRODUCED.
Consult the run's `manifest.json` for `classification` and `baseline_matches_host_bound`.
Only an actual isolated result of **3 cases, 1 failure, 0 errors, 0 skipped,
no timeout** qualifies this narrow baseline comparison. A passing baseline is
an integrity failure. A missing dependency, network attempt during verification,
source mutation, other failed check or weakened isolation does not qualify.

## Artifact audit

Acquisition and redistribution are separate questions. The file-level catalog
is generated directly from hash-checked recovery manifests by
`portable_verifier.acquire.catalog()`. Acquisition results record the requested
versioned/content-addressed URL, expected and observed hashes, and failures.
No existing host payload or host cache is an input.

| Required component | Exact historical artifact classification | Reconstruction path |
| --- | --- | --- |
| Historical verifier image `b71e6bea…` | MISSING_PROVENANCE | No independently verified registry origin or complete immutable layer/build chain. Local parents, mutable Temurin base and apt/pip resolution prevent claiming an exact rebuild. |
| Temurin 21.0.12.1+1 upstream Linux x64 archive | INDEPENDENTLY_REACQUIRABLE | Official release archive SHA-256 `ce79869e1307ed8ee1e2baa86a412b1eb5b75d10a01006d788a6f968bcfaee94`. Embedded historical JDK files were not separately sealed; same release does not prove their byte identity. |
| Gradle 9.2.1 ZIP | INDEPENDENTLY_REACQUIRABLE | SHA-256 `72f44c9f8ebcb1af43838f45ee5c4aa9c5444898b3468ab3f4af7b6076c5bc3f`. |
| 314 selected wrapper files | REPRODUCIBLE_FROM_PINNED_INPUTS | ZIP extraction plus two explicitly empty marker files; all 314 historical size/hash records verified. |
| 420 Maven/plugin module files | INDEPENDENTLY_REACQUIRABLE | All 420 independently acquired and hash-matched on the clean runner. Versioned upstream Maven, plugin, Minecraft-library and NeoForged `mojang-meta` endpoints; unverified downloads fail closed. |
| 215 generated Gradle module metadata/lock files | 210 REPRODUCIBLE_FROM_PINNED_INPUTS; five UNRESOLVED for exact historical bytes | 210 historical hashes matched. Four generated indexes/lock files differ; the DevLaunch descriptor was absent and unnecessary for this J001 execution. Full cache byte identity remains unproven. |
| 3,894 non-launcher NFRT downloaded inputs | INDEPENDENTLY_REACQUIRABLE | All independently acquired with exact historical hashes: Minecraft client/server/mappings, version JSON, asset index, asset objects and binarypatcher. Content-addressed URLs where available; versioned URLs checked against sealed SHA-256. |
| Previously URL-less binarypatcher 2.1.2 fat JAR | INDEPENDENTLY_REACQUIRABLE | NeoForged Maven URL in `acquire.py`; 624,217 bytes, SHA-256 `9d73d565b775c8ec9da83da6d2a25454c7aad95eba22f64def9261f214cc49ba`. Independently fetched and matched. |
| Historical global launcher manifest | TRANSFER_REQUIRED for its exact sealed bytes unless an independent historical origin is recovered | Recorded mutable URL now returns different bytes. Old SHA-256 `28b1e1e5d90851ce48ab935fe5644739364e262a8e8813e28e3d036aaec536ef`; current observation `845dfb7f8b28ce06bf0752b597ef2d4d65df973e4b59d8d6ff429ad2d3adde04`. Exact mode stops. |
| Functional launcher discovery index | REPRODUCIBLE_FROM_PINNED_INPUTS | Derive a 1.21.1-only index from the byte-verified version metadata and its recorded content-addressed URL. Record a NEW digest. This is explicitly different from the historical global index. |
| 22 NFRT intermediate files / ten nodes | REPRODUCIBLE_FROM_PINNED_INPUTS | All 22 reconstructed with matching historical hashes. The functional experiment uses the unchanged verifier's existing no-seed reconstruction path, not a fabricated or reauthorized historical attestation. |
| Historical Windows Python installation and installed packages | MISSING_PROVENANCE for independent exact reconstruction | Host executable/DLL/stdlib/package inventories exist; original installer/wheel acquisition chain is not recovered. Windows path/startup/import-tail policy is not portable to Linux. |
| New container CPython 3.13.14 and OS libraries | INDEPENDENTLY_REACQUIRABLE | Official Python amd64 OCI manifest `sha256:de572b33eae61a53675a87bbd02b5e365df7b6b2b06c9276124e965cec08c452` pulled on the clean runner, including Debian runtime libraries. No apt or pip resolution in the new image recipe. |
| Python packages for this J001-only bootstrap/verifier | REPRODUCIBLE_FROM_PINNED_INPUTS (empty package set) | The selected path uses Python's standard library only. This does not qualify the API provider, a Python-task verifier, Node verifier, controller test suite or Windows replay runtime. |
| Docker engine, kernel, filesystem semantics, available CPU/RAM/disk | UNRESOLVED as exact historical host identities | A Docker-capable clean Linux runner is required. Actual daemon version, capacity and launched image identity must be recorded. Matching container limits does not make host hardware/kernel byte-identical. |
| Source, wrapper policy and frozen J001 acceptance | INDEPENDENTLY_REACQUIRABLE | Exact public checkout plus frozen baseline SHA-256 `230340980b85d60b7a59d3aa338dffc4447c1bb7d8df90bff4d0dbe89afe5388` and test SHA-256 `80c1ced02955971cc827aed4e983d9407b919f47cc3af20f457f3a0f0098f159`. |

The cloud workspace used for initial acquisition had no Docker executable or
daemon, zero Linux capabilities, and rejects user-namespace mapping. Host Java
17 is not used as a verifier fallback. A Docker-capable hosted runner is needed
for isolated verification. The subsequent GitHub-hosted Ubuntu 24.04 run
provided Docker 28.0.4, four CPUs and approximately 16 GB RAM, and reproduced
the expected baseline. File-level classifications and observed hashes are in
`portable_verifier/evidence/ARTIFACT_CLASSIFICATION.json`.

## Licensing and public artifact policy

The reconstruction downloads from upstream into a disposable private run root.
**No JAR, ZIP, JDK, Python/OS binary, Docker image, Minecraft asset, transformed
Minecraft/NFRT output, Gradle cache, or third-party source tree is published to
Git or uploaded as a GitHub artifact.** The workflow uploads one metadata JSON
file only. Raw priming logs and private verifier diagnostics are excluded.

* [Minecraft EULA](https://www.minecraft.net/en-us/eula): game software/content
  and modded versions are not publicly redistributable without permission.
  Minecraft binaries/assets and NFRT outputs containing Minecraft classes are
  **LICENSING_BLOCKED for public redistribution**. Independently downloading
  authorized upstream inputs avoids a public cache mirror. No server EULA is
  automatically accepted; this task runs JUnit, not a game server.
* [Adoptium licenses](https://adoptium.net/about): OpenJDK is GPLv2 with the
  Classpath/Assembly exceptions and includes third-party notices. Distribution
  would require applicable licenses/notices and corresponding-source
  obligations. This work distributes no JDK binary.
* [Gradle 9.2.1 license](https://github.com/gradle/gradle/blob/v9.2.1/LICENSE):
  Apache-2.0, with additional licenses for bundled components. Binary
  redistribution requires preserving the relevant notices/licenses; it is not
  necessary here.
* [NeoForge license](https://github.com/neoforged/NeoForge/blob/1.21.x/LICENSE.txt),
  NeoForm Runtime 2.0.31 POM and binarypatcher 2.1.2 POM identify LGPL-2.1.
  LGPL obligations and bundled dependencies apply; a NeoForge tool's license
  does not grant redistribution rights to Mojang code in its outputs.
* [FTB Library license](https://github.com/FTBTeam/FTB-Library/blob/dev/LICENSE.md)
  is All Rights Reserved. Treat FTB binary public redistribution as
  **LICENSING_BLOCKED** without a separate grant. Use FTB's own Maven endpoint.
* [Python license](https://docs.python.org/3/license.html) and the pinned Debian
  base include their own licenses/notices. Other Maven components have
  component-specific terms. Their licenses are not collectively cleared by
  Gradle, NeoForge, or this report. No blanket binary redistribution approval
  is claimed.

## Smallest clean-machine bootstrap

Use a fresh Linux x86-64 machine with Python 3.12+ and Docker capable of enforcing
the unchanged memory/CPU/PID/network/tmpfs settings. Allow about 8 GB of free
disk and enough RAM for the 4 GB verifier plus the OS; a 16 GB runner provides
headroom. Install no local model and provide no API key or GitHub credential to
the bootstrap or containers. Checkout a reviewed full 40-character commit that
contains these reconstruction files:

```bash
git clone https://github.com/BillyMixNix/Hive.git
cd Hive
git checkout --detach <reviewed-reconstruction-commit>
python3 -I -S -B portable_verifier/entrypoint.py --test
python3 -I -S -B portable_verifier/entrypoint.py functional-baseline \
  --expected-commit <reviewed-reconstruction-commit> \
  --root /tmp/hive-portable-fresh \
  --evidence /tmp/hive-portable-results
```

Both output directories must be new. Acquisition concurrency is capped at 24;
downloads are size/hash bounded. The image uses the pinned Python OCI base and
verified Temurin archive with byte-preserved JVM runner sources. Docker build
steps have network disabled; there is no apt/pip dependency resolution.
The host Python launch disables user-site packages, `.pth` startup hooks and
Python environment injection. Its executable and loaded standard-library files
are hash-recorded using relative names. They identify the new runtime; they do
not satisfy the old Windows runtime identity or claim a pinned hosted OS image.

The trusted priming container has network access only to acquire/generate build
inputs. It receives unchanged baseline source, no frozen test and no credentials.
It resolves `createMinecraftArtifacts`, `testClasses`, and the unchanged test
runtime classpath through a preparation-only Gradle init script, inventories generated
cache metadata and NFRT outputs, then checks that all pinned module/native input
bytes remain unchanged. This is preparation, not a coding experiment or an
acceptance result. The no-model targeted verifier subsequently stages the exact
frozen test itself and runs with unchanged 240-second JUnit budget, offline
Gradle, Docker network `none`, readonly root/source/cache mounts, dropped
capabilities, no new privileges, UID 65532, 4 GB memory/swap ceiling, two CPUs,
448 PIDs and private tmpfs. No compiled candidate classes/results are reused.

`acquire` mode instead of `functional-baseline` checks original download pins
only, refuses the changed global launcher index, and never executes acceptance.
The exact old Docker image is not reconstructed by either mode.

## Remote initiation and evidence

`.github/workflows/hive-portable-verifier.yml` is one job with a 60-minute hard
timeout, no matrix, no secrets and no model/provider entry point. Ordinary
commits do not execute it: a push to the reconstruction branch needs the
deliberate `[portable-verifier-once]` commit-message marker. Four clean preparation
runs were required: two stopped before acceptance, the third could not load the
offline JUnit runtime, and the fourth reproduced the baseline. All are preserved.
Later repeats require a new deliberate operator action. `workflow_dispatch` additionally exists; GitHub
requires that workflow registration/default-branch conditions be satisfied.
No merge into main is required for the guarded push path.

Download `hive-portable-verifier-<run-id>-<attempt>` from the Actions run page;
it contains only `manifest.json`, retained for 30 days. Inspect acquisition
failures, image/base/JDK identity, functional launcher digest, regenerated
metadata/NFRT comparisons, baseline counts, isolation, final classification and
model-call count. Keep this manifest together with the exact Git commit and
bootstrap instructions. Never upload the disposable acquisition/cache/image
roots to a public artifact service.

Even a successful functional baseline is not EXACTLY_REPRODUCED, a cross-host
replication of the exact host apparatus, a coding success, a complete full-gate
qualification, or permission to execute an API-backed task. The original
host-bound RECOVERY-002 contract remains unchanged. Further remote API Hive
qualification remains a separate step with its own apparatus and authorization.

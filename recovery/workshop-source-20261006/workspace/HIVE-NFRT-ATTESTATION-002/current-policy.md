# Current attestation policy — before production edits

The original controller is the immutable `HIVE-FACTORIAL-003/repaired-workshop` tree (162 files, tree hash `433d575ac0dfebab27e43d46c75a9e73ad66adb69dda196ba3455ed64ea9cd4b`). Work takes place in a new isolated copy. No model, factorial or promotion is authorized here.

## Creation and provenance

The approved baseline priming run `e5a7c314b902` created the NFRT cache. `HIVE-TRANSITION-004B/inspect_artifacts.py` and `run_probes.py::prepare` inventoried 22 files / 163,178,447 bytes, checked them against the sealed priming inventory and independently recomputed ten key records. `HIVE-TRANSITION-004C/run_experiment.py::prepare` subsequently created the `hive-nfrt-seed-v1` host attestation; `HIVE-TRANSITION-005/bootstrap.py` preserved that manifest. The current approved manifest is `HIVE-TRANSITION-005/evidence/approved-nfrt-seed.json`, pinned by SHA-256 `8c6df7a0c494053f083b4e97a24647b6a066ae024d6402b8ff2c89d0df781b04`.

`verification/nfrt_seed.py::configured_seed` selects only host environment `HIVE_NFRT_SEED_MANIFEST` plus `HIVE_NFRT_SEED_SHA256`. Both absent means original verified reconstruction; partial, missing or incompatible configured evidence fails closed. Candidate source cannot select an attestation.

## Validation path

`load_attestation` verifies manifest digest, schema, bounded inventory, allowed flat filenames, corresponding node records and forbidden application namespace declarations. `configured_seed` checks baseline identity, exact verifier image (JDK), JVM/Gradle profile, downloaded-input manifest, both priming provenance hashes, approved priming status, and seed membership in the priming inventory. It checks the exact modules inventory and every module/tool hash. Existing `workshop/hive_jvm.py` and `hive_verifier.py::run_isolated` independently validate approved downloaded inputs, profile and source integrity.

The last compatibility block in `configured_seed` compares the candidate's `external_root._inventory` with the full attested source inventory. File membership must be identical. Every file outside `independent_java_sources` must have the same SHA-256. A mismatch throws `ValueError('NFRT reconstruction input changed: <path>')`; additions/deletions throw `NFRT source inventory changed`.

Only SnapshotFormatter is currently in `independent_java_sources` because TRANSITION-004B measured that one source variation. This is an intentionally conservative host review, not an NFRT requirement. Production has no benchmark filename; the host-owned v1 manifest carries the one-file allowance.

`verify_seed` verifies exact membership, size/hash, regular-file status, key recomputation, and absence of application packages in dependency JARs. `private_copy` validates before and after byte-copying into a fresh private cache. The host mounts approved artifacts read-only and `verification/jvm_runner.py` permits NFRT to mutate only its private copy. Candidate classes, task history, build directories and reports are never seeded.

## NFRT keys versus conservative host bindings

The ten native key records hash sorted input-content, action/tool and command-option components using SHA-1; their complete files and output files are additionally SHA-256-attested by Hive. NFRT `CacheKey.computeHashValue`, `CacheKeyBuilder`, `CacheManager` and node actions supply the native semantics. An NFRT hit alone is not authorization.

Baseline tree identity, complete source/config inventory, complete approved module inventory, full verifier image and priming provenance are conservative host bindings beyond native keys. These bindings deliberately cover omitted/indirect tool and environment determinants. Actual project reconstruction inputs are obtained by the pinned plugin's `CreateMinecraftArtifacts` / `NeoFormRuntimeTask`; optional access transformers, interface injection and Parchment can add project files even when they are absent in the frozen baseline. The new investigation must establish the allowed input class against this exact build, rather than replacing the old list with benchmark filenames.

No compatibility repair has been made when this reconstruction is written. A measured dependency model and sealed diagnosis must precede edits.

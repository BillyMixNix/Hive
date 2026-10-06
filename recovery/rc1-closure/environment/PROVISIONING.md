# RC1 verifier environment provisioning

The verifier uses the Docker image identified by `sha256:b71e6beae584a3bba27e6fe782a27ef971b481b1dff7226bc57f28626843ad26`, container Java 21, frozen Gradle 9.2.1 wrapper, offline Gradle module and NeoForm caches, and the approved NFRT seed. The exact versions, hashes, layout, and trust boundaries are in `ENVIRONMENT_MANIFEST.json` and the source-backed FACTORIAL-003R1 `FREEZE.json`.

On the current host, the approved cache and image are available only as host-local artifacts. The recovery corpus contains manifests and attestation, but not the approximately 1.4 GB third-party cache payload. No immutable remote source for the exact image was verified. Therefore this procedure demonstrates **hash-verified relocation**, not independent reacquisition on a clean machine. These artifacts must not be committed to Git without a separate redistribution review. A future independently primed cache would require new provenance and NFRT approval; it cannot silently replace this seed.

Create an empty disposable directory outside the recovery corpus and run:

```powershell
python -B recovery/rc1-closure/environment/verify_environment.py provision --root <fresh-root> --source-cache <approved-cache-from-FREEZE.json>
python -B recovery/rc1-closure/environment/verify_environment.py verify --root <fresh-root>
```

The script reads the sealed priming artifact inventory and copies only the Gradle wrapper distribution, module cache, NeoForm downloaded artifacts/assets and approved intermediate results. It verifies every selected source and destination file SHA-256. It copies the historical provenance into the required run-matched sibling layout, extracts the NFRT attestation from the immutable Git anchor, and checks both the exact local Docker image ID and the verifier's invoked tag-to-ID binding. Missing, extra, altered, or mismatched selected bytes fail closed. It does not fall back to the original host cache after relocation.

For the model-free frozen J001 baseline control, set `GRADLE_USER_HOME` to `<fresh-root>/hive_runs/approved-gradle-caches/e5a7c314b902`, `HIVE_NFRT_SEED_MANIFEST` to `<fresh-root>/approved-nfrt-seed-v2.json`, and `HIVE_NFRT_SEED_SHA256` to the frozen attestation hash. `baseline_control.py` performs these assignments after verifying the fresh root, and checks baseline/test/image/profile identity before calling the unchanged 240-second targeted verifier.

The host requires Windows filesystem semantics, a Linux Docker daemon, sufficient disk for the relocated cache and private verifier copy, and the recorded Python dependencies. The Python environment is version-recorded but not yet wheel-digest locked. Offline verification must be maintained; no model provider request is part of provisioning.

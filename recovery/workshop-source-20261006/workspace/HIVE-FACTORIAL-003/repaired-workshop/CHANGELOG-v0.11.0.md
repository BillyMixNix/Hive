# Nix Workshop v0.11.0

## HWR-000 isolated verification boundary

- Model-influenced pytest execution now runs only inside the prebuilt `nix-workshop-verifier:0.11.0` Docker image.
- The verifier receives a sanitized, read-only source copy, no host environment or secrets, no network, a read-only root filesystem, disposable tmpfs workspaces, dropped capabilities, and CPU/memory/process/time limits.
- Missing Docker, a missing image, invalid output, timeout, or isolation failure rejects verification. There is no host pytest fallback.
- Both targeted test-worker checks and full staged/post-apply verification use the same boundary.

## HWR-000B stale-base protection

- Each build records byte-level base and staged manifests for every changed file.
- Apply validates every path before writing and rechecks immediately before each atomic replacement.
- Manual edits, concurrent applies, create collisions, missing files, type changes, symlinks, and stage tampering fail closed instead of being overwritten.
- Legacy ready runs without manifests cannot be applied.

## HWR-001 provenance foundation

- Run records now include schema-versioned experiment metadata, a deterministic source-manifest hash, environment identity, model policy, start/finish timing, and ordered logical call IDs.
- The build API accepts optional study, condition, task, replicate, trial, and condition-spec identifiers without changing ordinary builds.
- Provider attempt metrics are linked to logical call IDs after each run.

## Truthfulness and release hardening

- The capability endpoint now reports the actual sequential worker topology.
- Release packaging excludes secret/configuration and coverage/IDE artifacts.
- Added isolation, timeout, traversal, symlink, stage-tampering, stale-source, reverse-apply, and legacy-run regressions.

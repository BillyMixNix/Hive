# Reproduce the model-free portable J001 baseline

The measured recipe is commit `53d411379a8d2dfaf9d926c0fe334d3c6821289e`.
Use a clean Linux x86-64 machine/cloud runner with Docker and Python 3.12+,
approximately 16 GB RAM and at least 8 GB free disk. The successful reference
runner was GitHub-hosted Ubuntu 24.04 with Docker 28.0.4. A later hosted OS
revision is a new recorded apparatus, not an identical host image.

Provide no API key, GitHub credential, original verifier image, original cache
or original NFRT seed. The bootstrap independently acquires all payloads.
Public Git clone and upstream acquisition need network access; isolated
acceptance does not. The reviewed licensing policy permits upstream private
acquisition; it does not permit publishing the acquired caches/game binaries.

```bash
git clone https://github.com/BillyMixNix/Hive.git
cd Hive
git checkout --detach 53d411379a8d2dfaf9d926c0fe334d3c6821289e
test "$(git rev-parse HEAD)" = 53d411379a8d2dfaf9d926c0fe334d3c6821289e
python3 -I -S -B portable_verifier/entrypoint.py --test
python3 -I -S -B portable_verifier/entrypoint.py functional-baseline \
  --expected-commit 53d411379a8d2dfaf9d926c0fe334d3c6821289e \
  --root /tmp/hive-portable-fresh \
  --evidence /tmp/hive-portable-results
```

Both directories must not already exist. Use new paths for every replay. Do
not add files to the checked-out repository: the bootstrap rejects a dirty or
untracked checkout and verifies protected source identities against the
published qualification anchor. Run without user/site packages via `-I -S`.

The command verifies original manifest hashes, downloads bounded upstream
inputs with SHA-256 checks, builds the digest-pinned image without build-step
network access, primes fresh cache inputs, checks all retained download bytes,
compares regenerated intermediates and stages the unchanged frozen acceptance
test for one targeted offline verifier run. Only the historical mutable launcher
index may be functionally reconstructed, from the pinned 1.21.1 version JSON.
Every other failed download pin stops the experiment. `acquire` mode instead
demands original download bytes and stops at the changed global launcher URL;
it is not an exact-image reconstruction mode.

The result is qualified only when `manifest.json` contains:

```json
{
  "classification": "FUNCTIONALLY_RECONSTRUCTED",
  "baseline_matches_host_bound": true,
  "baseline_result": {
    "tests": 3, "failures": 1, "errors": 0,
    "skipped": 0, "timed_out": false
  },
  "model_calls": 0,
  "host_local_payloads_used": false
}
```

An unexpectedly passing baseline, zero cases, timeout, changed source, failed
integrity check or weakened isolation cannot qualify. Record the new manifest
and image/runtime identities even if the counts match. Do not expect the Docker
image ID or generated mutable cache tables to match the reference run.

## GitHub initiation

The published branch is `remote/hive-verifier-reconstruction`. Its workflow has
a single 60-minute job, no matrix and no API secret. Routine pushes skip the
job. An operator can explicitly initiate one new model-free replay by making
an empty commit on that branch with the `[portable-verifier-once]` message
marker and pushing it. That workflow checks out the exact new commit SHA,
verifies protected source equality and creates new disposable roots. It is a
new run, so preserve its identities separately from the reference commit.

`workflow_dispatch` is also declared, but GitHub's default-branch workflow
registration requirements may prevent dispatch while the workflow exists
only on this experimental branch. The guarded branch-push route requires no
merge into main. Do not use an ordinary evidence commit to initiate a replay.

## Retrieve and inspect evidence

Open [successful run 37666448896](https://github.com/BillyMixNix/Hive/actions/runs/37666448896)
and download `hive-portable-verifier-37666448896-1`. Its ZIP SHA-256 is
`d46986b018074c63f121c98e5fedf96cb1546570ec3506e60c5dfb964c433316`.
The extracted `manifest.json` SHA-256 is
`13e68b42c395d12ae76630efc3952140586d7f365051bd9958df80d92bce091e`.
GitHub retains the artifact for 30 days. The same manifest is durably preserved
as [REPRODUCIBILITY_MANIFEST.json](portable_verifier/evidence/REPRODUCIBILITY_MANIFEST.json).

For a new replay, download its similarly named artifact and compare its SHA-256
with GitHub's recorded artifact digest before inspecting the manifest. Preserve
the exact commit, expected/actual acquisition hashes, baseline counts, all 22
NFRT comparisons, runtime/image fingerprints, isolation and timings. Evidence
contains metadata only; do not publish disposable payload/cache/image roots or
private raw diagnostics.

See [qualification limits](HIVE_PORTABLE_VERIFIER_QUALIFICATION.md) before using
the result as a prerequisite for another experiment. No paid model request or
API-backed coding experiment is part of these instructions.

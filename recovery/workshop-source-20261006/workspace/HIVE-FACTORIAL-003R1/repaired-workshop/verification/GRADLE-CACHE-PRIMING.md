# Explicit Gradle dependency-cache priming

Priming is an operator-run setup operation, separate from verification. It is
never triggered by a Hive build or by verifier failure. The operator must pass
`--allow-network`; only that priming container uses Docker bridge networking.

The operation requires a run-owned candidate at
`hive_runs/external_candidates/<12-hex-run-id>`, its matching run evidence
directory, an immutable external baseline, and a new empty cache directory at
`hive_runs/approved-gradle-caches/<same-run-id>`. It statically reads the
candidate's checked-in Gradle Wrapper and documented full-gate task names.
No Gradle command or argument is accepted from a model or caller.

Example from the Workshop checkout:

```powershell
python verification/prime_gradle_cache.py `
  --baseline-root 'C:\path\to\immutable-baseline' `
  --candidate-root 'C:\path\to\Nix_Workshop\hive_runs\external_candidates\0123456789ab' `
  --cache-root 'C:\path\to\Nix_Workshop\hive_runs\approved-gradle-caches\0123456789ab' `
  --allow-network
```

The container mounts the candidate read-only and the dedicated Gradle user-home
cache as its only writable bind mount. Build work and temporary files live in
container tmpfs. It uses the checked-in wrapper, Java 21 image, and exact
`VERIFICATION.md` full-gate task list. A successful priming run is not a
verification result and never promotes a candidate.

After priming, point the separate, normal verifier process at that cache root
using `GRADLE_USER_HOME`. Verification still uses `--network none`, a read-only
source mount, read-only `modules-2` and wrapper-distribution mounts, and its
private tmpfs Gradle user home. The read-only dependency cache root is the
parent of `modules-2`, so Gradle resolves `<cache-root>/modules-2` exactly once.

The operation stores UTC timing, source and wrapper hashes, image ID, executed
argv, Java/Gradle versions, any repository origins visible in Gradle `--info`
output, and a deterministic SHA-256 inventory of every file populated in the
new cache. The inventory excludes only the provenance directory containing
the inventory and its own provenance record.

For builds statically identified as using NeoForm Runtime, priming also warms
NeoForm's native `caches/neoformruntime` layout. The `artifacts` tree holds
downloaded Minecraft/version metadata and tool artifacts; `assets` holds the
asset indexes and content-addressed game assets. Generated
`intermediate_results` are not treated as downloaded inputs: they are rebuilt
on verifier tmpfs. The native input manifest records every regular file under
`artifacts` and `assets` by relative path, size, and SHA-256, with source URLs
resolved from the cached launcher/version/asset metadata and Gradle request
output where observable. Its run evidence binds the manifest to the baseline,
wrapper, and verifier image. The normal verifier checks exact inventory and
hashes before mounting those two trees read-only under the approved cache root.
The fixed container runner links them into the writable tmpfs Gradle home at
`caches/neoformruntime/{assets,artifacts}`. This avoids Docker creating
root-owned intermediate directories beneath `/work`; the links still resolve
only to read-only manifest-verified mounts. The verifier itself remains
`--network none` and Gradle `--offline`.

Priming executes the repository's documented task list with Gradle
`--continue` so independent tasks can still materialize legitimate inputs
after an application/GameTest failure. Cache priming and application test
success are reported separately. For example, an application failure such as
`Missing test structure: <namespace>:<name>` does not indicate failed input
acquisition when `createMinecraftArtifacts` completed, while a network or
input failure in that task always makes priming fail closed. Priming never
turns that application failure into an offline verification pass.

# HIVE-ASTRA-J001 — resumed preflight

Primary classification: **BLOCKED**

The user supplied `M3.2-frozen-baseline.zip` after the initial missing-repository block. It contains 276 files under `baseline/`, including the authorized Java source, its existing five-case JUnit test class, Gradle wrapper and build definition. The archive was extracted into a new isolated directory without changing any member bytes.

The required repository fingerprint remains unverified. FREEZE.json declares `230340980b85d60b7a59d3aa338dffc4447c1bb7d8df90bff4d0dbe89afe5388`, but neither metadata nor archive supplies its tree-hash algorithm, exclusions, serialization or expected per-file manifest. Limited conventional tree/manifest calculations produced no exact match. This does not prove the baseline differs: a repository digest depends on the defined serialization. The ZIP's separate transport hash is not treated as the repository fingerprint.

The before-edit baseline requirement remains binding. No implementation was attempted and no candidate was substituted. A verified mismatch classification would require the authoritative hash calculation; no mismatch is asserted here.

## Observable engineering findings

- `SnapshotFormatter.MAX_LINE_CHARS` is 240 UTF-16 code units.
- `boundLine` first applies `line.replaceAll("[\\p{Cntrl}\\u00a7]", "?")`.
- Sanitized strings of length at most 240 are returned unchanged.
- Longer strings use `safe.substring(0, MAX_LINE_CHARS - 3) + "..."`, reserving three code units for the suffix.
- The cutoff is index 237 and can divide a UTF-16 surrogate pair.
- Existing `SnapshotFormatterTest` has five JUnit cases covering output bounds, unavailable/empty observations, control/section-sign sanitization and locale-stable formatting. It contains no explicit surrogate truncation boundary case.
- The build requests Java21 and JUnit Jupiter5.11.4; Gradle9.2.1 and NeoForge tooling are pinned. This host currently exposes Java17 runtime, no javac, and no Docker executable.
- The frozen `SnapshotFormatterUnicodeAcceptanceTest` and verifier invocation are absent. Metadata identifies three frozen cases and their expected test hash, but no hidden test source was read or recreated.

## Preserved identity and scope

Archive SHA-256:
`f9d6a5f092e009af86ccf068d5a9cb1325a70031713310fc81094f690310710f`

Original and final authorized-file SHA-256, identical:
`5322a76cc496bdef8c6c5fb3d70ccd11004b076d6246cb7202874ca261255b98`

All 276 extracted files were compared byte-for-byte with archive members after inspection. **Zero files changed; zero files added inside the repository.** The archive contains no `.git` metadata, so the complete byte comparison provides a stronger check than limiting the check to an unavailable tracked-file list. `implementation.diff` is empty.

## Search trajectory summary

Read-only source/context: authorized SnapshotFormatter.java, existing SnapshotFormatterTest.java, build.gradle, wrapper properties, README, ignore rules, and the previously supplied task/freeze metadata. Archive inventory was inspected for a manifest, instruction files, verifier and target source. No other candidate implementation, patch, repair or Hive-controller result was inspected.

One helper agent mechanically calculated limited baseline fingerprints from archive bytes. It did not inspect source text for implementation guidance and did no implementation work. The primary agent inspected the authorized source and performed the byte-preservation check. This is prerequisite delegation, not decomposition of the code change.

- Materially distinct implementation approaches: **0**.
- Implementation attempts: **0**.
- Executable compiler/test verification runs: **0**.
- Compiler/test feedback changing code: none.
- Important uncertainty resolved: the source is now available; frozen baseline identity and executable acceptance remain unverifiable with the supplied artifacts.
- Final frozen gate result: **NOT RUN**.

## Evidence files

- `scope-and-identity.json`: original/final source hashes and full archive-byte scope verification.
- `original-file-hashes.json`: independently recorded SHA-256 for each exact archive member; not claimed to be the authoritative frozen manifest.
- `baseline-hash-search.json`: 24 limited conventional path/content serializer checks.
- `manifest-hash-checks.json`: 12 conventional JSON-manifest serializer checks.
- `implementation.diff`: empty, reflecting zero edits.
- `commands.txt`: read-only command inventory.

To proceed, provide the exact baseline fingerprint function/command (including file exclusions and serialization) and the frozen verifier entry point. The hash function can be supplied separately from the runner so no oracle or other candidate needs to be exposed. Hidden tests can remain verifier-only.

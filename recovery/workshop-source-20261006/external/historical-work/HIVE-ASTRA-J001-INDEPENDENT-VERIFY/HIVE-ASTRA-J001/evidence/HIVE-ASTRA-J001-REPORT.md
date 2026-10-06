# HIVE-ASTRA-J001 — Independent Frozen Trial

Primary classification: **BLOCKED**

The single-file candidate is implemented and passes all available executable checks. The frozen acceptance gate has **not run** because Docker and the pinned verifier image are unavailable on this host. This report does not claim sealed verification or VERIFIED_PASS.

## Baseline and scope

The exact user-provided tree-hash algorithm was implemented in `tree_hash.py`, including exclusions, the source-resource data exception, casefold/path ordering, 8-byte big-endian path lengths, and content SHA-256 hex encoding. Before editing, it produced the exact frozen fingerprint:

`230340980b85d60b7a59d3aa338dffc4447c1bb7d8df90bff4d0dbe89afe5388`

The same fingerprint was checked again immediately before the sole edit. See `baseline-tree.json` and `pre-edit-verification.json`.

Only `src/main/java/dev/atmcompanion/state/SnapshotFormatter.java` changed. All 276 supplied repository files were compared with the original archive after verification: one authorized file differs, zero others differ, zero repository files were added. The supplied archive contains no Git metadata; the complete byte comparison covers all supplied files, rather than relying on an unavailable tracked-file list.

| Identity | SHA-256 |
|---|---|
| Original authorized file | `5322a76cc496bdef8c6c5fb3d70ccd11004b076d6246cb7202874ca261255b98` |
| Final authorized file | `618f6bcae2c6f18d1b4e1b9751817b90640adb57d4079165d0af0dbb8e472ecb` |
| Candidate tree | `ecb294b3b7b9a0bd87e365e9f30d2b07ca083f65734abe0a433f1b69b700d4a6` |

Full patch: `implementation.diff`. Complete candidate repository: `../candidate/` in the delivery ZIP.

## Observed behavior and change

`MAX_LINE_CHARS` is 240 UTF-16 code units. Existing sanitization replaces characters matching `[\p{Cntrl}\u00a7]` with `?`. Strings at or below the bound return unchanged after sanitization. Truncated strings reserve three code units for `...`, giving a prefix cutoff of 237.

The original cutoff could retain a high surrogate while discarding its paired low surrogate. The candidate preserves the original sanitization and early-return behavior, then backs the cutoff up by one code unit only when it intersects a complete surrogate pair. The suffix remains `...`; ordinary truncated ASCII still has length 240. A pair-intersecting truncation has length 239. The change does not attempt to repair malformed UTF-16 already present in the input.

## Executable checks

Tests ran against the actual compiled repository class and unchanged repository DTO/test sources. They used the host Java17 compiler module, JUnit Platform1.11.4/Jupiter5.11.4 and Gson2.10.1. This is supplemental execution, not the frozen Java21 Docker environment.

| Check | Original baseline | Candidate |
|---|---|---|
| Existing SnapshotFormatterTest | 5/5 pass | 5/5 pass |
| Boundary/property probes | Fails at pair intersecting cutoff, exposing an unpaired high surrogate | 10,698 cases pass |
| Frozen acceptance gate | Not run | Not run |

Supplemental checks include ASCII below/exactly/above the bound; pairs wholly before, intersecting and immediately after the prefix cutoff; pair-at-cap and supplementary-only strings; controls and section signs near the cutoff; unchanged C1-character behavior; output length; and absence of unpaired surrogates for valid input. An independently written code-point oracle checks 10,000 seeded valid Unicode inputs. No frozen acceptance source was inspected or reproduced.

Commands, stdout and stderr are retained under `before/` and `after/`. XML JUnit reports are included. Dependency URLs and hashes are in `dependencies/dependency-receipt.json`. The external probe and runner are included under `probes/`; no test file was added to the repository.

Two Gradle launch attempts were blocked before executing tests:

1. `sh ./gradlew ... test --tests dev.atmcompanion.state.SnapshotFormatterTest` failed because the supplied wrapper has CRLF line endings. The wrapper was not modified.
2. Invoking the wrapper's Java entry point avoided the shell issue, then failed with `UnknownHostException: services.gradle.org` while obtaining the pinned distribution. Build configuration was not modified.

Both logs are retained. The fallback compiled the exact relevant source/test classes externally and ran the real existing JUnit class, rather than treating compilation alone as validation.

## Frozen gate status

Required image: `nix-workshop-verifier:0.11.1-jvm21-extroot-002d-tmpfscopy`

Required image ID: `sha256:b71e6beae584a3bba27e6fe782a27ef971b481b1dff7226bc57f28626843ad26`

The attempted `docker image inspect` could not execute: no Docker executable. `result.json` preserves the command and failure. The frozen three-case acceptance class and its source remain outside the coding context. An image name/ID and successful supplemental checks do not establish the frozen acceptance result.

Run the packaged candidate through the existing sealed verifier using the unchanged FREEZE.json conditions. Do not replace that gate with the supplemental runner or promote this result before the sealed result is available. No production promotion was performed.

## Observable search trajectory

- Context inspected: task/freeze metadata; original authorized source; existing formatter tests and fixtures; GameSnapshot, Observation, Capability and CapabilityStatus dependencies; build.gradle, wrapper properties, README and ignore rules. No other trial candidate, patch, repair attempt or controller result was inspected.
- Baseline identity: initial missing-source and missing-hash-definition blocks were resolved by the user-supplied archive and exact hashing algorithm. Earlier fingerprint guesses were not treated as verification.
- Materially distinct implementation approaches: **1**, conditional cutoff adjustment.
- Implementation attempts: **1**, with no repair iteration.
- Compiler/test feedback: baseline probe reproduced the specific surrogate split; candidate compiled and passed on its first run. Environment failures changed the test-launch method, not the implementation.
- Decomposition: source implementation was not decomposed. One helper performed earlier read-only hash checks; another wrote supplemental tests from the original baseline and task, without inspecting the candidate implementation or sealed tests.
- Verification counts: **2 local validation cycles** (before and after), **4 executed suite/probe invocations**, **2 compilation invocations**, **2 blocked Gradle launches**, **0 sealed verification runs**.
- Remaining uncertainty: the actual frozen acceptance result and full Gradle/Java21 build result. Available tests support correctness but cannot discharge those gates.

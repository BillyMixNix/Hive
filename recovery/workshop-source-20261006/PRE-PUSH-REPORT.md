# Pre-push recovery report — 2026-10-06

This is a byte-preserving archival recovery. No Hive source was edited, no tests or experiments were rerun, no model was called, and no candidate was promoted. Original reports and frozen evidence retain their original bytes and classifications. The snapshot is additive; inherited repository files are unchanged.

## Roots and Git provenance

- Original workspace: `C:\Users\billy\Documents\Codex\2026-10-05\hive-transition-001-diagnose-and-repair`.
- Current source: `workspace/HIVE-THINKING-POLICY-001/repaired-workshop/` in this archive.
- Original workspace/current-source Git commit and branch: **none — not a Git repository**.
- Separate nearby backlog checkout: `f65eebd0d1bcbab4e4ecd151f371b987191bf749`, branch `main`, clean at inspection. It is not provenance for the current unversioned Workshop source.
- Destination: `BillyMixNix/Hive`, new branch `recovery/workshop-source-20261006` only.
- New branch parent: `9a4c6436899e24f9bdee216d837c490ffc5d69ca` (existing recovery staging lineage). PR #36 and its branch are not updated.
- Remote main observed before recovery: `f6f0f8dbf998be53199ec9fe32c77eb9b52bc585`.
- All source roots and their original absolute paths: [SOURCE-ROOTS.json](SOURCE-ROOTS.json). Git status, tracked/untracked/ignored lists where Git exists, including generated fixture repositories: [GIT-STATE.json](GIT-STATE.json). Non-repository files are explicitly inventoried as unversioned.

## Deterministic identities

- Original workspace tree SHA-256: `408be1a0b3407318b7c204bfc787ad7f9d45a9b941f585d643255c2804e895e6`.
- Full inventory manifest SHA-256 (uncompressed JSONL bytes): `3bea194f950f0dae0b9ae9d5b9ed75a1d3105fb66bc84d755e3d7e57a7f2318a`.
- Included source/evidence tree SHA-256: `8c34fa43b248ef707201a911ad7f6c09099132ad85bde3f349b2414e2d5f7d55`.
- Latest historical source freeze hash: `9bff60ebc3c8feddafe91672ceb7d3d3f7cb6f651e3e277c4fa0aa4d95953afa`. Its historical algorithm differs from the archival tree algorithm; the per-file comparison is in SOURCE-AND-TESTS.json.
- Inventoried files across all selected roots: 169,620; included: 109,972; excluded: 59,648.
- Included source/evidence bytes: 2,211,616,283.

The archival tree hash is SHA-256 of compact UTF-8 sorted-key JSON mapping relative paths to `{sha256,bytes,type}`. Link hashes cover the link target string, not dereferenced content. JSONL manifests are sorted by archive path. The archive does not claim to preserve NTFS ACLs, creation times, empty directories, or Git executable bits for originally unversioned Windows files.

Full manifests and per-file exclusion reasons are provided as deterministic gzip JSONL files when size requires compression; MANIFEST-SUMMARY.json identifies their storage names and hashes. Original bytes are never redacted or rewritten: a secret-bearing file is excluded as a whole.

## Exclusions

| Reason | Files |
|---|---:|
| `application_runtime_or_user_state` | 268 |
| `compiled_binary_or_runtime_cache` | 3 |
| `compiled_or_dependency_jar` | 7 |
| `credential_or_secret_file` | 16 |
| `downloaded_gradle_cache_payload` | 43,733 |
| `generated_build_output` | 59 |
| `generated_regression_scratch` | 13,942 |
| `git_metadata_or_dependency_runtime_cache` | 1,603 |
| `opaque_archive_not_committed` | 11 |
| `runtime_database_may_contain_private_state` | 6 |

Excluded classes include `.env`/credential files, private application state/databases, Git internals, caches, downloaded dependencies and NFRT intermediate files, model weights, generated build/compiled outputs, regression scratch, and opaque archives. The approved attestation, provenance, recipes, manifests and dependency identities remain where available. Gradle wrapper bootstrap JARs are retained as checked-in build tooling, not candidate compilation output. Exact exclusions are in EXCLUDED-FILES.jsonl (or its `.gz` storage form). Content scanning and manual review results are recorded separately without credential values.

## Tests available; none run during recovery

- Current Workshop: 64 Python files under tests, 418 statically identified test-function definitions. Parameterization means this is not a collected-case count.
- Preserved latest regression XML: 656 passed, 6 skipped, 0 failures, 0 errors. These are **historical results**, not a new validation claim.
- Qualified measurement-harness tests and their historical reports are preserved.
- Frozen J001–J004 acceptance sources and task definitions are archived under `external/historical-work/HIVE-FACTORIAL-001/`.
- Frozen M3.2 baseline includes Java/Gradle source, wrapper configuration/bootstrap and 29 Java files under src/test.
- Static inventory and hashes: [SOURCE-AND-TESTS.json](SOURCE-AND-TESTS.json).

## Source completeness and remaining gaps

| Area | Recovery status |
|---|---|
| FACTORIAL-002 | Original controller, frozen study metadata and non-secret run evidence recovered under external/historical-work/HIVE-FACTORIAL-002. |
| TRANSITION-003 | Source and evidence recovered under workspace/hive-transition-003 (original case preserved). |
| 003R1 | HIVE-FACTORIAL-003R1 source and evidence recovered. No separate directory named HIVE-TRANSITION-003R1 was located; that distinct identifier is unverified. |
| TRANSITION-004 / 004B / 004C / 005 | Original source copies, reports, verifier/attestation code and non-secret evidence recovered. |
| Java/Gradle verification | Frozen baseline, acceptance sources, Java-edit apparatus, verifier recipes and controller code recovered. Docker/JDK/model binaries, downloaded Gradle dependencies and NFRT cache payloads are deliberately excluded. |
| Decomposition | Current planner normalization, ownership, dispatch and replanning implementation is in workshop/hive.py and hive_protocol.py. No separate decomposition module is required by this located implementation. |
| Promotion / apply | Current explicit-human apply guards, stale/scope/integrity checks and reviewer policy recovered. A separately named promotion-bundle exporter was not located; its existence/completeness cannot be asserted. The inherited older grow/kernel/promotion.py is lineage evidence, not a substitute. |
| Reviewer/provider policy | hive_review.py, providers.py, thinking_policy.py and profiles, their tests, and preserved policy reports recovered. |

No located current frozen source file may be silently missing: SOURCE-AND-TESTS.json lists every expected freeze file and any mismatch. Historical absolute paths are intentionally unchanged. SOURCE-ROOTS.json supplies relocation mapping; no configuration was rewritten for portability. This is source/evidence recovery, **not a self-contained offline runtime backup**. Reconstructing the runtime requires the separately managed pinned images, tools, dependencies, model weights and attested cache contents.

The archive contains hidden acceptance sources and historical candidate evidence. It is not a model workspace or model context. Future experiments must isolate their designated baseline/task context using the preserved policies.

## Preservation audit

Rehashed 169,620 original files and 109,972 included copies. Original additions/removals/hash changes: zero. Copy hash mismatches: zero. See [INTEGRITY-AUDIT.json](INTEGRITY-AUDIT.json). Source files were not imported or executed.

Git stores recovered bytes without clean filters or line-ending conversion. For a byte-identical checkout use `git -c core.autocrlf=false clone ...` or extract Git blobs/archive without text conversion. Recovery tooling is included separately; it is not part of Hive production source.

## Push boundary

Only `refs/heads/recovery/workshop-source-20261006` is authorized for this operation. No force push, no changes to main, PR #36 or existing experiment branches, and no production application/promotion. This report is prepared before pushing; the resulting commit and remote verification are reported by the recovery operation.

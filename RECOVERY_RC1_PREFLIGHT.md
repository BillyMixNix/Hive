# RC1 deterministic preflight

**Result: PARTIAL.** The candidate-only adapter passes its recovery authority tests and exact-source checks in a fresh sparse worktree. The archived Workshop suite passes 602 tests, skips 8, and fails 11 because three archived test modules expect historical replay files absent from the selected FACTORIAL-003R1 evidence directory. The unchanged M3.2 baseline reached a real frozen J001 JUnit decision within the original targeted verifier budget. The preflight does not establish that an RC1-generated Java candidate passes acceptance.

The final test worktree was detached at `c0e66e1133376d24f9d89e95fdc44a753ab39ef4` and checked out from the RC1 branch. `recovery/rc1/PREFLIGHT.json` records commands, environment, identities, counts and classifications. On this Windows case-insensitive filesystem, `recovery/rc1/preflight.json` resolves to the same file as `PREFLIGHT.json`; two separately cased Git entries cannot be safely materialized in a clean Windows checkout.

| Check | Observed result | Classification |
|---|---|---|
| Parse 31 canonical Python files | Pass | Verified import/syntax surface |
| Compare 40 runtime files with source manifest and 34 frozen committed blobs | Exact match | Verified provenance |
| `python -B -m pytest -q tests/recovery ...` | 22 passed, 1 skipped (Windows symlink privilege) | Recovery authority path passes within this harness |
| Archived FACTORIAL-003R1 Workshop suite | 602 passed, 8 skipped, 11 failed in 67.00 s | `TEST_INCOMPATIBILITY`: missing fixture paths, not modified source or assertions |
| M3.2 Gradle/J001 baseline targeted verifier | 196.057 s, Gradle return code 1, `frozen_junit_acceptance` failed, no timeout, last phase `junit_reports_collected` | `EXPECTED_HISTORICAL_FAILURE` for unchanged baseline |
| Recovered corpus and baseline Git-tree identities | Anchor and RC1 tree object IDs equal | Archived committed evidence unchanged |

The 11 archived-test failures are all `FileNotFoundError` for `HIVE-FACTORIAL-003R1/evidence/ownership-historical-replay.json`, `evidence/ordinal-03/*`, `evidence/planner-input-fixtures/*`, or an `evidence/live/*` run. Corresponding evidence appears in other transition directories, but these frozen test modules hardcode the selected sibling directory. No fixture was copied over or test changed to force green. Their parser/ownership replay assertions remain unverified in this exact clean checkout. The 602 passing archived tests include the applicable verifier, policy, source-integrity, ownership and reviewer tests.

The Java control used the historical approved Gradle/NFRT cache, attestation manifest and pinned Docker image available on this host; these large machine-local payloads were deliberately excluded from the recovery Git corpus. The baseline tree SHA-256 was `230340980b85d60b7a59d3aa338dffc4447c1bb7d8df90bff4d0dbe89afe5388`, matching FACTORIAL-003R1. The hidden J001 test SHA-256 matched its freeze (`80c1ced02955971cc827aed4e983d9407b919f47cc3af20f457f3a0f0098f159`), and its source was passed only to the isolated verifier. The bounded summary retained the failed frozen gate, return code and phase but not fresh JUnit case totals. The historical 3-case/1-failure baseline record is not substituted for fresh counts.

The original promotion-bundle consumer is unverified. RC1 therefore has no promotion method, reports `promotion_authorization=unavailable`, and disables the copied Workshop apply/rollback entry points on import. The post-review adapter also rejects a frozen test that already resides in the model-visible baseline and no longer lets reviewer-provider unavailability erase a deterministic PASS. The adapter change did not alter the byte-preserved legacy verifier; the fresh recovery suite and source manifest were rerun after it. No model-backed trial, historical experiment, apply or promotion was run.

The recorded test environment is Windows, Python 3.13.14, pytest 9.1.1, jsonschema 4.26.0, FastAPI 0.141.1, httpx 0.28.1, pydantic 2.13.4, Node 22.18.0 and Docker 29.7.2 with pinned image `sha256:b71e6beae584a3bba27e6fe782a27ef971b481b1dff7226bc57f28626843ad26`. `jsonschema` was initially missing from the host test environment and was installed outside the repository before the archived suite ran. The approved Gradle distribution is 9.2.1 and the verifier image supplies Java 21.

Source-manifest SHA-256: `35617f3e24887b013bcc0e237c2f51276dee20983c4b2004f1298dfaeb531f55`. The archived corpus Git tree remains `214a81054c99ec4a12db04f60d17bb25ec9011bb` at both the recovery anchor and RC1; the baseline Git tree remains `517e5cb3a523f944c68833b196bd511cbcd0fc07`.

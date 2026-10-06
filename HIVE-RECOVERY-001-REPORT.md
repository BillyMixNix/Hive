# HIVE-RECOVERY-001 — canonical reconstruction

**Executive result: PARTIAL.** RC1 identifies a coherent, source-backed controller and exposes a candidate-only authority path with complete per-file provenance. Its new deterministic recovery tests pass in a fresh worktree, and the unchanged M3.2 baseline reaches a real frozen JUnit decision within the targeted deadline. Eleven archived regression cases cannot find their hardcoded historical fixture paths in the selected source freeze. The approved Gradle/NFRT cache is host-local rather than recoverable from Git. RC1 is therefore a bounded recovery candidate, not a generally reproduced or promotable production controller.

## Selected source and architecture

RC1 begins at recovery Git anchor `edadbd8da46f3fd5ace479b7292012665d80096f` on `recovery/workshop-source-20261006`. The selected historical controller is `HIVE-FACTORIAL-003R1/repaired-workshop`: its 163-file freeze tree SHA-256 is `f495206de7fecfe5950f941826a84dfd1d81d2ceac164a1899d5eede5cd04ca7`, production tree SHA-256 `bc1596bafb06b9c9d53576dea5832f6a5b4b9691f5ce46a05b90a5120caa0890`. It is the latest coherent controller with a completed 16-cell frozen study (2 verified software successes), rather than the later experimental `think:false` revision (six worker-timeout diagnostics, no frozen/full-gate success). [Controller lineage](RECOVERY_CONTROLLER_LINEAGE.md) records predecessors, source locations, hashes and supersession decisions.

The canonical runtime is a new `hive_canonical/` namespace. Thirty-four controller/verifier files are copied byte-for-byte from the committed 003R1 source blobs; six runtime adapter/metadata files are new recovery code. No archived source was edited. The small host-owned [candidate controller](hive_canonical/controller.py) requires an exact write scope, prepares an isolated external candidate, invokes the recovered planner/worker/verifier/reviewer pipeline, checks baseline and staged source identities, and returns the verified candidate evidence. The archive's absolute `workshop` and `verification` imports are bound to these private copies by a new namespace adapter. [SOURCE_MANIFEST.json](recovery/rc1/SOURCE_MANIFEST.json) binds every one of the 40 runtime files to SHA-256, source path/revision or new-code status; [PROVENANCE.json](recovery/rc1/PROVENANCE.json) binds the chosen freeze.

Authority is: host task, exact scope and frozen test specification → isolated baseline snapshot → planner schema/ownership → bounded workers and observations → scoped edit/stage → targeted verification and bounded correction → full deterministic gate → separate semantic review disposition → candidate identity. **Promotion terminates at `promotion_authorization=unavailable`; no apply occurs.** The [authority map](RECOVERY_AUTHORITY_MAP.md) cites source functions and tests for each transition and marks partial/missing boundaries. Source-backed prior lineages and exclusions appear in [component decisions](RECOVERY_COMPONENT_DECISIONS.md). Old state-packet, reference-model, GROW, cockpit and self-diagnosis work remains history or research, without an established dependency requiring an RC1 import. The later thinking policy is experimental and excluded.

## Promotion and missing source

The [promotion audit](RECOVERY_PROMOTION_AUDIT.md) classifies the chain **PARTIALLY_RECOVERED**. EVAL-009 has a historical bundle exporter and result hashes, but no verified bundle manifest/consumer chain. The separate historical direct `--promote` path lacks stale-base and rollback authority. The later Workshop internal apply has source-backed checks but is not a promotion-bundle consumer, and its external candidates are explicitly nonpromotable. RC1 does not invent that missing authority; its public API has no promotion method and its copied apply/rollback entry points raise `PromotionUnavailableError`.

The selected full 163-file Workshop freeze includes API/UI and other source that RC1 does not expose as runtime authority. RC1 is a candidate-only library, not a recovered live Workshop service or restart/resume engine. Recovery also lacks the approved Gradle/NFRT cache payload and complete promotion-bundle consumer. Eleven archived tests require replay fixtures at paths absent from the selected FACTORIAL-003R1 evidence directory, although analogous artifacts exist in other historical directories. These gaps remain explicit rather than reconstructed from prose.

## Deterministic preflight and integrity

The fresh detached sparse worktree tested source commit `c0e66e1133376d24f9d89e95fdc44a753ab39ef4`. Exact commands, versions, hashes, counts and classifications are in [PREFLIGHT.json](recovery/rc1/PREFLIGHT.json) and [preflight narrative](RECOVERY_RC1_PREFLIGHT.md). Windows resolves `recovery/rc1/preflight.json` to that same file; a second case-only Git filename would not check out safely on this filesystem.

| Check | Result |
|---|---|
| Canonical Python syntax | 31 files parsed |
| RC1 runtime provenance | 40 manifest records exact; 34 committed source blobs byte-preserved |
| `tests/recovery` | **22 passed, 1 skipped** (Windows symlink privilege) |
| Archived FACTORIAL-003R1 Workshop suite | **602 passed, 8 skipped, 11 failed**; all 11 are missing hardcoded fixture paths (`TEST_INCOMPATIBILITY`) |
| Frozen M3.2 baseline Java targeted verifier | Returned in **196.057 s**, no timeout; Gradle exit 1 and `frozen_junit_acceptance` failed, as expected for the unchanged J001 baseline; last event `junit_reports_collected` |
| Historical corpus Git tree | `214a81054c99ec4a12db04f60d17bb25ec9011bb` at both anchor and RC1 |
| Baseline Git tree | `517e5cb3a523f944c68833b196bd511cbcd0fc07` at both anchor and RC1 |

The J001 baseline source hash and frozen test hash matched their 003R1 freeze. Its actual frozen test source was supplied only to the verifier, not a model. The model-free Java preflight used the approved external cache and pinned Docker image present on this host; Git alone cannot supply those payloads on another machine. Its bounded output did not retain fresh case totals, so the historical 3-case/1-failure result is not claimed as a new case count. No RC1-generated Java candidate was submitted to frozen acceptance. No model call or historical study rerun occurred.

## Adversarial result

An independent read-only subagent reviewed the authority path. The [adversarial record](RECOVERY_RC1_ADVERSARIAL_REVIEW.md) first documented a conditional protected-test leak: a same-byte frozen JUnit file already in a baseline could be read via worker observations. A synthetic sentinel reproduced the read path. The new RC1 adapter now refuses baseline-resident frozen acceptance sources before any worker call; fresh recovery tests passed after this containment. The review also found two result-projection defects in the new adapter, now tested and corrected: reviewer-provider unavailability no longer erases deterministic PASS, and planner correction exhaustion is no longer mislabeled as provider runtime failure.

One **unproven** general-scope risk remains: if a future host scope permits edits to a Gradle build script, candidate-controlled Gradle behavior could potentially forge test reports while leaving frozen test source untouched. The frozen J001–J004 scopes allow application Java only, and no exploit was demonstrated. RC1 does not claim such build-script scopes are qualified. Runtime source manifests are checked at preflight, not continuously before each call. No verified promotion, reviewer-over-verifier, or stale-base overwrite path was found in the RC1 public API.

## Disposition and next step

RC1 source commit: `c0e66e1133376d24f9d89e95fdc44a753ab39ef4`; the report and preflight artifacts are committed later on the same `recovery/hive-canonical-rc1` branch. No candidate was applied or promoted. `main`, PR #36, existing experiment branches, historical Git evidence and production state remain untouched. The branch is not merged.

**Not yet a general HIVE-RECOVERY-002 go-ahead.** First reconcile the 11 historical regression fixture paths through a separate, non-mutating recovery harness; qualify any proposed writable build-script scope against report forgery; and ensure the approved verifier cache/image can be provisioned and attested in the intended runtime. After review and separate authorization, HIVE-RECOVERY-002 may run one bounded model-backed replay against source-only scope with the exact frozen acceptance and no promotion. This task ends at deterministic preflight.

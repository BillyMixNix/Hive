# Docker Resource Saver timing addendum

Date: 2026-10-05. Scope: operator observation following HIVE-TRANSITION-004.

**Resource Saver wake consumed a measurable part of the verifier deadline. It is not established as the cause of the verification timeouts.** Newly located Docker lifecycle logs show that TRANSITION-003 woke Docker from idle: **8.302 seconds** from wake request to VM-ready event, **9.107 seconds** from wake request to completed container-start API response. This is approximately **3.8%** of the 240-second budget. The original verifier's first instruction and internal build phases remain unobserved.

The existing TRANSITION-004 baseline measurements now provide a matched cold/warm comparison: **27.057 seconds cold versus 1.680 seconds warm** from verifier launch to first received container event. Both timed out. Resource Saver contributed materially to the cold launch, but removing that launch delay was insufficient for the measured warm baseline or preserved candidate to finish verification. No setting or timeout change is justified by these observations alone.

The original TRANSITION-004 report remains unchanged and classified PARTIAL_DIAGNOSIS. This addendum supplies newly located historical startup evidence; it does not rewrite any outcome.

## Evidence and method

The analysis used existing verifier-only runs and read-only Docker logs. **No new container, verifier run, or model call was made.** The controlled baseline already had two byte-identical candidates, identical runtime sources, identical frozen gate/profile/cache configuration, and identical verifier argv after normalizing unique container names, diagnostic run IDs, and fresh sanitized source paths. Reusing those measurements avoids an unnecessary additional build campaign.

“Warm” means **Docker's engine was already running when a fresh isolated verifier container was launched**. No candidate reused another verifier's writable filesystem. This is a retrospective matched comparison, not a new randomized trial. Host load, filesystem/page-cache warmth, and ordering were not controlled, so later setup-time differences cannot all be attributed to Resource Saver.

Sources are preserved in [Docker lifecycle excerpts](evidence/docker-lifecycle-excerpts.jsonl), including original log path and line number; [source digests](evidence/docker-log-sources.json); [container identity mappings](evidence/container-identities.json); and exact copied [prior timing artifacts](evidence/prior-measurements). The useful records were in Docker's `monitor.log` rotations, not just its separately named backend log. Only study-container and lifecycle lines were preserved, excluding unrelated request bodies and environment data.

Docker's documentation explains that image/listing requests can be served while Resource Saver remains active. Its descriptions vary by backend, so the local lifecycle timestamps—not the documented typical wake duration—determine this finding. [Docker Resource Saver documentation](https://docs.docker.com/desktop/use-desktop/resource-saver/).

## TRANSITION-003 used Docker and woke it inside the deadline

The preserved run observation names `hive-verify-4993c0baef72`. Newly recovered create/start/port records connect that name to container ID `c40377bc172822061bbe0618de0b7c262a9e3cf3ff075520da2f31b995401e75`. This independently corroborates the [original reconstruction](../HIVE-TRANSITION-004/reconstruction.md).

| Observed event | UTC, 2026-10-05 |
|---|---|
| Idle→busy on container-create request; VM wake begins | 14:54:09.3979 |
| Docker idle manager reports VM started | 14:54:17.6994 |
| Named verifier container create returns | 14:54:18.0985 |
| That container's start API returns | 14:54:18.5048 |
| Forced removal of named verifier requested | 14:58:09.4123 |
| Idle timer expires after verifier removal | 15:03:09.8298 |
| VM stopped by idle management | 15:03:11.5903 |

The wake-to-removal interval is **240.014 seconds**. The container-start-response-to-removal interval is **230.908 seconds**. These intervals correlate closely with Hive's 240-second Docker deadline; they are not a claim of 230.908 seconds of Gradle execution. The actual host CLI launch timestamp and first verifier instruction are still missing.

The frozen source confirms `targeted_verify_isolated(... timeout=240)` and `subprocess.run(command, capture_output=True, text=True, timeout=timeout)`, where `command` is `docker run`. Consequently startup is inside the deadline, not a separately timed preparatory step. See [preserved invocation implementation](../HIVE-TRANSITION-003/repaired-workshop/workshop/hive_verifier.py), lines 248–250 and 319.

Resource Saver did **not** leave the original verifier asleep for 240 seconds: the logs record container startup, the preserved stage observation records it alive at 14:57:47, and idle shutdown occurred five minutes after removal. A Resource Saver/RAM-zero observation made after shutdown is compatible with normal post-run inactivity. The operator observation has no supplied exact timestamp, so it cannot be assigned to a particular phase.

Machine-readable historical measurements: [transition-003-startup.json](evidence/transition-003-startup.json).

## Cold versus warm verification

Seconds; all runs used the unchanged 240-second outer limit. “Before Gradle” includes launch and copies, so these columns must not be summed. “Gradle exposure” ends at timeout and is not a completion duration.

| Existing replay | Docker start state | Launch→first container event | Measured VM wake | Native inputs copy | Before Gradle | Gradle exposure | Result |
|---|---|---:|---:|---:|---:|---:|---|
| measured-baseline | Resource Saver wake | 27.057 | 23.939 | 98.599 | 149.348 | 90.703 | Timeout |
| post-regression-baseline | Already running | 1.680 | No wake | 81.798 | 101.566 | 138.477 | Timeout |
| measured-preserved | Already running | 1.123 | No wake | 78.480 | 96.140 | 143.965 | Timeout |
| post-regression-preserved | Already running | 3.063 | No wake | 102.581 | 125.471 | 114.594 | Timeout |
| measured-known-good | Already running | 2.161 | No wake | 115.700 | 140.482 | 99.594 | Timeout |

The cold baseline launch used **11.27%** of its budget. The warm baseline launch used **0.70%**. Their observed launch difference is **25.377 seconds**; **23.939 seconds** is directly located in Docker's VM wake interval. The total pre-Gradle difference is **47.781 seconds**, but the additional copy-time difference is confounded by host/cache state and is not a measured Resource Saver effect.

Warm status is supported by the continuous lifecycle sequence, not inferred only from short launch times. Docker woke at 15:32:08 for the cold baseline. Subsequent containers were created within the unchanged five-minute idle threshold, with no intervening VM-stop/wake records before the measured launches. The largest intervening idle gap in that sequence was approximately 4m57.57s before a regression container, which kept the engine running before the warm baseline replay.

Every replay's last observed Gradle task was `createMinecraftArtifacts`; none observed candidate compilation or frozen test execution. The private native-input copy remained **78–116 seconds even with an already-running engine**. Those costs, followed by artifact construction, explain why startup is only one component of the budget. They do not by themselves prove a particular filesystem defect or an inadequate timeout.

Full measurements: [timing-comparison.json](evidence/timing-comparison.json). Runtime/command comparability audit: [comparison-audit.json](evidence/comparison-audit.json).

## Causal conclusions and falsification

| Hypothesis | Supported conclusion | What would change it |
|---|---|---|
| TRANSITION-003 used Docker | Confirmed by source, named container observation, create/start/removal logs | A mismatch between the recorded container identity and the run; identities currently agree |
| Resource Saver added startup latency | Confirmed: 8.302s VM wake in TRANSITION-003; 23.939s in the cold TRANSITION-004 replay | Evidence that those lifecycle events belong to a different invocation; exact name/ID/timestamp correlation currently supports them |
| Resource Saver remained active throughout verification | Contradicted by observed startup and subsequent container lifetime | Evidence of a later pause affecting the live container; none is present in the relevant lifecycle sequence |
| Disabling Resource Saver is sufficient to eliminate the timeout | Not supported; already-running baseline, preserved candidate, and known-good control all timed out | Repeated matched runs where only prelaunch idle state changes and warm runs finish within 240s; no such successful comparison exists |
| Resource Saver alone caused the historical TRANSITION-003 timeout | Not established | Original internal phase evidence or a faithful matched replay showing completion specifically within recovered wake time; the original internal evidence was lost |

A roughly nine-second historical startup cost might still matter to an individual borderline run. The available data cannot rule out that narrow counterfactual. It also cannot justify calling Resource Saver the root cause of the broader repeated timeout frontier.

## Changes, integrity, and next boundary

Resource Saver remains unchanged; the settings file hash is unchanged. The timeout is still 240 seconds. No production edits, candidate edits, gate changes, engine restarts, pause/unpause operations, or model calls occurred. The read-only current `docker desktop status` returned `stopped`; this value alone is not sufficient to distinguish Resource Saver from another stopped-engine cause. [Current status](evidence/current-status.json).

All **1,670** pre-existing TRANSITION-004 files and its root report were rehashed unchanged. Earlier experiment trees were read only. The comparison audit has eight passing checks. Its initial broad source-manifest check also detected a changed regression-test file and two generated test snapshots between the original measurement batches; that initial result is preserved. The narrower runtime-source audit confirms `app.py`, `workshop/`, and `verification/` are identical, and the actual verifier argv/gate inputs match. [Integrity](evidence/integrity.json), [initial audit](evidence/comparison-audit-initial.json), [final audit](evidence/comparison-audit.json).

No production tests were rerun because this follow-up changed no production or test code. The previous 453-passed/6-skipped regression result remains historical evidence, not a newly executed result.

The unresolved cost remains **inside the running verifier**, particularly private native-input materialization and Minecraft artifact construction. A further causal experiment should isolate that phase while holding Docker's initial state observable. This addendum does not change the verifier or authorize a longer deadline to make the candidate pass.

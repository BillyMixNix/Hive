# HIVE-ASTRA-001 — Controlled Challenge Set

Status: pre-registered; no challenge task has been sent to a model.

All eight tasks use independent disposable candidates copied from the same frozen ATM Companion M3.2 baseline. Their frozen JUnit sources are acceptance inputs, not prompt attachments. For each task, the exact request below is sent unchanged to both conditions. No production promotion is permitted.

## T001 — Straightforward activity summary helper

Add `public int count(ActivityEvent.Type type)` to `ActivitySummary`. Return the count for exactly that type. Every enum value must return its count (including zero); a null type must throw `IllegalArgumentException`. Do not mutate the summary.

Frozen test: `ActivitySummaryCountAcceptanceTest.java`.

## T002 — Snapshot-diff validation / 64-bit trap

Harden `ActivityDiffService.diff`. Before calculating any deltas, reject every null or negative item count in either input map with `IllegalArgumentException`, including equal negative values that would otherwise cancel. Preserve 64-bit arithmetic: valid counts above `Integer.MAX_VALUE` must still produce the correct small delta. Missing keys continue to mean a known count of zero. Keep the existing maximum event-quantity rule.

Frozen test: `ActivityDiffValidationAcceptanceTest.java`.

## T003 — Multi-file activity aggregation

Extend `ActivitySummary` with an immutable `Map<ActivityEvent.Type, Long> quantitiesByType`, initialized for every enum value; a null event quantity contributes zero. Preserve the existing three-argument constructor. Add `ActivityHistory.summary()` that returns a summary of the currently retained events. It must be a snapshot: later appends do not change it.

Frozen test: `ActivityHistorySummaryAcceptanceTest.java`.

## T004 — Omission-prone bounded history retrieval

Add `ActivityHistory.recent(int limit)`. Accept only limits from 1 through the configured capacity. Return at most the newest `limit` retained events in their existing chronological order, as an immutable detached list. Leave the existing no-argument method and history state unchanged.

Frozen test: `ActivityHistoryRecentLimitAcceptanceTest.java`.

## T005 — Large-context planning diagnostics

Add `PlanningReport.diagnostics()` as a deterministic, immutable projection. Start with `plan.limitations()` in encounter order, remove duplicates while preserving first occurrence, then append (when applicable): `Planning search was truncated.`, `Recipe index is incomplete.`, `Quest context unavailable (<STATUS>): <detail>`, and `Knowledge graph is truncated; some nodes or edges were omitted.` Return at most 16 entries. Do not claim unavailable information is known.

Frozen test: `PlanningReportDiagnosticsAcceptanceTest.java`.

## T006 — Subtle denominator

Add `QuestOverview.completionPercent()`. It is the integer percentage `floor(100 * completedQuests / questCount)`, using total quests as the denominator, not available quests. Return zero when `questCount` is zero. Do not change the stored counts or availability semantics.

Frozen test: `QuestOverviewCompletionPercentAcceptanceTest.java`.

## T007 — Decomposed activity window projection

Add immutable record `ActivityWindow(List<ActivityEvent> events, ActivitySummary summary)` and `ActivityHistory.between(Instant startInclusive, Instant endExclusive)`. Include retained events in `[startInclusive, endExclusive)` while preserving append order; the summary must describe exactly the returned events. Equal endpoints produce an empty window. Null endpoints or a start after the end must throw `IllegalArgumentException`. The query must not alter history.

Frozen test: `ActivityWindowAcceptanceTest.java`.

## T008 — Complex quest projection; repair-likely candidate

Add `QuestOverview.fromSnapshot(QuestSnapshot snapshot, String timestamp)`. Preserve the source version, team scope, lock flag, and declared availability rule. Count all observed chapters, all observed quests, and completed quests from the snapshot; use the snapshot's validated available-ID list for the available count. Build options from the first `MAX_OPTIONS` available IDs in their existing sorted order, resolving each ID to its quest title and chapter ID. Preserve the fixed omitted-details text. Do not infer dependencies, availability, or task details.

Frozen test: `QuestOverviewSnapshotProjectionAcceptanceTest.java`.

## Evaluation protocol (fixed before any model run)

- Each of the 16 condition-runs gets a fresh independent candidate copied from the exact frozen baseline. Frozen acceptance tests are supplied to the verifier through the existing frozen-JUnit request field; their source is never included in either model prompt.
- Both conditions use `gpt-6-astra`, the same persistent Agents API family, the same verifier image, and the same read-only approved caches. The task text above is passed byte-for-byte unchanged as the task in each pair.
- Direct condition: one Astra coding turn, with the complete deterministic text snapshot of baseline source/configuration/documentation (excluding `.git`, binaries, generated build output, and caches); no tools, Hive planner, worker split, reviewer, or repair. It must return one unified diff. A fixed local harness may apply only safe in-candidate paths; malformed, escaping, or non-applicable diffs fail closed. If the full repository context cannot fit, classify the run as apparatus-invalid instead of silently truncating it.
- Hive condition: normal frozen Hive planner/worker/reviewer contracts and existing repair limits. No additional retries or manually supplied context.
- Run the task's frozen JUnit acceptance test first. A candidate failing acceptance is not eligible for the full Gradle gate. If acceptance passes, run the unchanged documented M3.2 gate: `clean build runGameTestServer runQuestTestServer packTestJar`.
- No candidate is promoted or applied. Preserve all prompts, responses, candidates, verifier reports, and run artifacts. Do not edit task text or tests after the lock file is written.
- Randomize within-pair order from the recorded seed in `FREEZE.json`; follow that order without substituting or rerunning a failed task.

### Measurements fixed before runs

- **Verified completion:** frozen JUnit passes and, when reached, the complete M3.2 Gradle gate passes. Report acceptance and full-gate outcomes separately.
- **False acceptance:** a condition reaches Hive `ready`/review approval (or the direct harness marks success) while the frozen acceptance fails, or while the full gate fails after acceptance passed.
- **Attempts:** provider model turns, with create-session turns and follow-up turns counted separately and also summed. Infrastructure-only HTTP reads are not model turns.
- **Repairs:** planner correction, worker replan, structural edit repair, and targeted correction are reported as separate counts; never combine them into one opaque retry number.
- **Dropped requirements:** count failed frozen assertions and task requirements not evidenced by the final candidate; preserve the assertion-level report rather than inferring success from a plausible diff.
- **Wall time:** monotonic elapsed time from the first model request to terminal candidate disposition; also report verifier wall time separately.
- **API usage/cost:** record provider-reported per-turn input/output/cached/reasoning tokens when available. Missing fields remain unknown. Report billed cost only from provider billing/usage records; do not infer dollars from turn tokens or emit `$0` when cost is unavailable.

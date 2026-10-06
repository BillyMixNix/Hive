# HIVE-FACTORIAL-001 task preregistration

These are fresh local-model characterization tasks against the unchanged M3.2 baseline. The acceptance sources in `hidden-tests/` are verifier-only and must never be included in model prompts or repository context. Each task starts from an independent snapshot of the same baseline. No candidate can be promoted.

## J001 — Unicode-safe bounded status lines

In `SnapshotFormatter.boundLine`, preserve complete UTF-16 surrogate pairs when truncating a line to `MAX_LINE_CHARS`. Keep the existing control-character and section-sign sanitization, the `...` suffix when truncation is necessary, and unchanged behavior for ordinary ASCII lines. Truncation must never introduce an unpaired surrogate or return a string longer than the bound.

Write scope: `src/main/java/dev/atmcompanion/state/SnapshotFormatter.java`.

## J002 — Reject invalid allocation slot identities

In `IngredientAllocation.canSatisfy`, reject with `IllegalArgumentException` any null, negative, or out-of-range (36 or greater) slot identity in either the matching-slot lists or the counts map, and reject null count values. Preserve valid allocation behavior and do not mutate caller inputs.

Write scope: `src/main/java/dev/atmcompanion/knowledge/IngredientAllocation.java`.

## J003 — Map an observation without inventing availability

Add `Observation.map(java.util.function.Function<? super T, ? extends U>)` returning `Observation<U>`. For available data, apply the mapper exactly once and preserve status and detail; a null mapper or null mapped result must be rejected. For unavailable or not-integrated observations, preserve status and detail with null data and never invoke the mapper. Do not change the existing factories or constructor invariants.

Write scope: `src/main/java/dev/atmcompanion/state/Observation.java`.

## J004 — Two-layer scan coverage projection

Add `ExecutionContext.Scan.coveragePercent()` returning the integer floor of `100 * scannedPositions / totalPositions`, with zero when totalPositions is zero. Coverage counts scanned positions even when some are unloaded; it is not the same as `complete()`. Add `ExecutionAssessment.observedCoveragePercent()` delegating to its observation's scan; return `-1` when the assessment has no observation. Preserve all current assessment and scan invariants.

Write scope: `src/main/java/dev/atmcompanion/execution/ExecutionContext.java`, `src/main/java/dev/atmcompanion/execution/ExecutionAssessment.java`.

# HIVE-ASTRA-002 novel challenge set — preregistration draft

These eight tasks use independent candidates from the unchanged M3.2 baseline. The
matching JUnit sources are verifier-only acceptance inputs, never model context.
The requests below are the exact task text for both future conditions. None has
been submitted to Astra or Hive. N001–N008 were designed without using the
T001–T008 outcomes to tune retrieval or verifier settings.

## N001 — Immutable event source copy

Add `ActivityEvent.withSource(ActivityEvent.Source source)`. Return a new event
with only `source` changed. Preserve every other field and do not mutate the
original. Reject a null source with `IllegalArgumentException`.

Frozen test: `ActivityEventWithSourceAcceptanceTest.java`.

## N002 — Overflow-safe inventory total

Add `GameSnapshot.Inventory.totalCount(String itemId)`. Sum counts for exactly
the requested registry ID across all stacks using 64-bit arithmetic. Return
zero when absent. Reject null with `IllegalArgumentException`; do not mutate
the inventory.

Frozen test: `InventoryTotalCountAcceptanceTest.java`.

## N003 — Exact recipe-type projection

Add `RecipeReport.candidatesForType(String recipeType)`. Return candidates whose
`recipeType` equals the argument, retaining encounter order in an immutable
detached list. Return an empty list when none match. Reject null with
`IllegalArgumentException`; do not change the report.

Frozen test: `RecipeCandidatesForTypeAcceptanceTest.java`.

## N004 — Distinct blocking evidence

Add `ExecutionAssessment.blockingReasons()`. Return blockers followed by
unverified conditions, preserving first occurrence order while removing exact
duplicates. The result must be immutable, including for the empty case.
Do not infer readiness from a missing observation or change stored lists.

Frozen test: `ExecutionBlockingReasonsAcceptanceTest.java`.

## N005 — Selective optional integration inspection

Add `IntegrationRegistry.inspectSelected(Set<String> capabilities)`. Inspect
exactly the named registered capabilities using the existing failure and
unavailable semantics. Do not invoke a mod predicate or adapter factory for
an unselected registration. Reject null, a null member, or any unknown name
with `IllegalArgumentException` before inspecting anything. Return an
immutable map; leave registrations and `inspect()` behavior unchanged.

Frozen test: `IntegrationSelectedAcceptanceTest.java`.

## N006 — Deterministic recipe choice

Add `RecipeSelection.bestOf(List<RecipeSelection> candidates)` returning
`Optional<RecipeSelection>`. Select the minimum by the record's existing
`compareTo` ordering, independent of input order; return `Optional.empty()`
for an empty list. Reject null list or null member with
`IllegalArgumentException`. Do not mutate the supplied list.

Frozen test: `RecipeSelectionBestOfAcceptanceTest.java`.

## N007 — Retained activity identity projection

Add `ActivityHistory.uniqueRegistryIds()`. Return distinct registry IDs from
the *currently retained* events, sorted lexicographically in an immutable
detached list. An empty history returns an empty list. Evicted events must
not contribute, and calling the method must not change history state.

Frozen test: `ActivityUniqueIdsAcceptanceTest.java`.

## N008 — PlanResult immutable limitations update

Add `PlanResult.withLimitations(List<String> limitations)`. Return a new
PlanResult with only its limitations replaced by an immutable defensive copy.
Preserve every other component, including the execution assessment, selected
action, alternatives, and metrics. Reject null with `IllegalArgumentException`;
the original result must remain unchanged.

Frozen test: `PlanResultLimitationsAcceptanceTest.java`.

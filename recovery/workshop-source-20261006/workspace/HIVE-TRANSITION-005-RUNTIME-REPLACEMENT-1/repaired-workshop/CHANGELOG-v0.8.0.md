# Nix Workshop v0.8.0

## Bounded escalation gates

- Added an explicit `blocker_type` to structured worker escalations.
- Require six completed bounded observations before any worker may return `plan_insufficient`.
- Reject escalation requests for files already in the worker's exact write plan.
- Require planner-owned interface contracts for plans with multiple active roles.
- Correct invalid multi-role plans before worker execution.
- Preserve planner-only scope changes, strict validation, structural repair, verification, review, approval, budget and rollback gates.
- Record the bounded observation trajectory with replanning diagnostics.

## Verification

- Full source and clean extracted-archive verification are recorded in `TEST_RESULTS.txt`.

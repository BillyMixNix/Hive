# Nix Workshop v0.7.0

Planner/worker architecture refinement. Hive Build now gives the planner a compact deterministic repository map, always includes explicitly owned files in worker context, and supports a structured `plan_insufficient` worker escalation. A valid escalation receives at most one planner-mediated replan; only the revised planner contract can authorize new files, and the existing strict validator, staged apply, verification, approval, budget, snapshot, rollback, and ledger gates remain authoritative.

Added focused map, owned-context, escalation, replanning, malformed-protocol, bounded-loop, and revised-scope adversarial tests. Runtime history is excluded from repository maps and clean release archives.

# Nix Workshop v0.7.9

## Bounded Worker Coding Correction

- Added a role-scoped candidate loop after observation and before final Hive verification.
- Fully validated proposals are checked on the private staged tree with bounded Python, JavaScript, and changed-test checks.
- Failed candidates are reverted and sent back to the originating worker for at most one complete correction.
- Targeted correction diagnostics and outcomes are recorded in the run artifact.
- Targeted correction budgets remain separate from observation, structural-repair, and planner-replan budgets.
- Preserved exact ownership, strict validation, staged-tree behavior, final verification, reviewer approval, human apply, rollback, routing, and budget controls.

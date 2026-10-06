# Nix Workshop v0.6.2

Worker diagnostics release.

- Hive worker failures now retain role, stage, exception type/message, bounded raw output, and parsed payload details.
- Worker failures are recorded per agent and in the run error list.
- Planner goals marked “no change needed” skip model execution.
- Edit validation and edit application failures are reported as distinct stages.
- Existing safety gates, scopes, approval flow, budgets, snapshots, verification, rollback, and ledger behavior are preserved.

Verification: 40 tests passed, Python compilation passed, frontend parsing passed, and the release builder produced a clean archive.

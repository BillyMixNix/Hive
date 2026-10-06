# v0.9.1 Chat Run-Awareness Fix

- Fixed Workshop Chat run-awareness after live v0.9.0 showed that Qwen could receive the generic Workshop-state wrapper yet fail to identify the latest Hive failure.
- Recent Hive runs are now rendered before repository inventory, with an explicit deterministic `LATEST HIVE RUN` digest.
- Latest-run context now includes bounded rejected planner-attempt diagnostics in addition to run errors, verification, review, changed files, and apply status.
- Chat passes the current user query into the read-only context renderer for future bounded query-aware selection; no write authority or Hive invocation was added.
- Preserved all Hive ownership, observation, escalation, replan, verification, reviewer, approval/apply, rollback, and provider controls.

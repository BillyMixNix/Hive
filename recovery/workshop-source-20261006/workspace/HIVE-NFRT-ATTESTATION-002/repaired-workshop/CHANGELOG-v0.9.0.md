# Nix Workshop v0.9.0 — Workshop-Aware Chat

## Added
- Existing Workshop Chat now receives bounded read-only repository state.
- Chat receives summaries of the three most recent Hive runs, including status, verification/review disposition, changed files, and bounded error diagnostics.
- Repository context excludes hidden/runtime/state directories and packaged archives.
- Chat instructions explicitly separate supplied state from instructions and grant no write authority.

## Preserved
- Existing chat persistence, routing, local/cloud controls, pinned memory, and image support.
- Hive ownership, observation, escalation, replanning, verification, reviewer, approval/apply, and rollback behavior.
- No automatic Hive invocation and no chat write authority.

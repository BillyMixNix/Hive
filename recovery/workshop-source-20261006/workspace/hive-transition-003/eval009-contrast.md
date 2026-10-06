# EVAL-009 observable contrast

Evidence was found at `C:/Users/billy/Documents/Codex/2026-09-22/atm10-ai-companion-autonomous-build-mega/local-model-trial/`. Copies of relevant artifacts, with original paths and SHA-256, are under `evidence/eval009/` and `evidence/eval009-source-manifest.json`. Originals are read-only. Current orchestrator/pipeline source corroborates execution mechanics, but its historical byte identity is not independently established.

Stored `hive-eval-009/plan.json` contains an explicit `decompose_into` pair: activity-reset-service writes ActivityCommandService.java and reads LiveActivityService.java; activity-reset-command writes CompanionCommands.java and reads ActivityCommandService.java. Child contracts already specify the required API/command behavior, prohibit editing tests, and identify frozen acceptance. This is predetermined task-specific decomposition, not an observed model-generated role-ownership plan.

`orchestrated-runs/20260924-073647-a040db65/result.json` records routing from a 54,096-character parent to those two children under a 35,000-character limit. Both children are accepted at attempt 0 with Gradle exit 0; accepted service output is overlaid into the dependent command child. Final status ready_for_promotion, frozenTestsChanged=[], acceptanceExitCode=0, promoted=false. The recorded final command is **Gradle test**; do not equate that historical gate with the present frozen multi-task full gate merely because EVALUATION.md calls it a full Gradle suite. The earlier failed launches disclosed in EVALUATION.md remain failures.

| Dimension | EVAL-009 | Generalized planner in TRANSITION-002 |
|---|---|---|
| Ownership author | Stored explicit child plan | Local planner generates role file arrays |
| Write representation | Named child `writable` list | `worker_files` for UI/backend/tests |
| Read representation | Separate `read_only` list | Bounded source/observations; no standalone read-only worker goal |
| Shared file | Service child writes; command child reads | Role arrays all permit the same allowed path as a write |
| Inactive roles | No unused fixed roles to populate | Three required goal/file/acceptance records |
| Dependencies | Named accepted-child overlay | Planner generates interface contracts |
| Worker task | Prewritten narrow API/command contract | Planner-generated goal and criteria |
| Tests | Host-frozen, explicitly not editable | Host-frozen; planner must avoid inventing a tests writer |

This comparison shows a new ownership/decomposition burden absent from EVAL-009's successful execution path. It does not prove the generalized representation caused a particular token choice: task, harness, gates, prompts and execution protocol differ. It does not justify copying the old task-specific contracts into J001 or bypassing the current planner.

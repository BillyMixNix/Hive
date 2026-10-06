# HIVE-FACTORIAL apparatus repair (separate successor copy)

The completed HIVE-FACTORIAL-001 freeze and raw evidence are historical and have not been edited. This directory is not a continuation or rescore of those trials.

## Failure boundary

The frozen runner checked planner file assignments inside its model-call callback and raised `StudyStop` on an out-of-scope path. That prevented Hive from receiving the planner response and using its existing one-correction allowance. The call record retained a response hash but the run artifact lacked the rejected plan and exact offending paths. The subsequent local-runtime classification was therefore an apparatus artifact, not evidence of an Ollama outage.

## Repair

The successor `workshop/hive.py` accepts an optional, host-supplied `allowed_write_files` list. It exposes the exact outer write boundary to planner and replan prompts, records it in run metadata, and validates every proposed role/file assignment after normal plan validation but before any worker executes. An invalid initial plan is recorded with exact paths and passed to the existing single planner-correction path. If correcting the scope makes a role inactive, the correction schema no longer forces an unrelated interface contract based on that rejected role; a genuinely multi-role corrected plan still has to pass the original contract validator. Invalid corrected plans fail closed. Replanning cannot expand the host boundary. Workers still face the unchanged ownership and edit validators. With no host scope supplied, ordinary Workshop behavior is unchanged.

`factorial_runner_adapter.py` now wires both controller conditions to this boundary. The single-agent condition receives the original deterministic host plan and host reviewer; Hive receives unmodified planner responses so it can spend its own correction allowance. Both pass the exact `task["files"]` list into `hive.run_build`. The adapter deliberately does not replace the experiment's local-only provider, token, wall-time, observation, verifier, integrity, or no-promotion controls. A **new, separately frozen** runner must supply those controls and use this adapter. Do not modify the frozen HIVE-FACTORIAL-001 runner or reuse its lock for a new experiment.

## Validation

`tests/test_host_write_scope.py` exercises a no-model Java fixture through the successor adapter. Both the single-agent controller and a corrected Hive plan reach worker, staged edit, reviewer, and synthetic verifier boundaries. Further tests cover exact-path diagnostics, deactivating an unauthorized second role without a fake contract, one-correction exhaustion, replan expansion, unsafe paths, and a worker trying to edit an unowned file. This is a boundary check, not a model-performance result or a sealed Gradle acceptance run.

Focused tests: 12 passed. Full Workshop suite: 382 passed, 6 skipped. `python -m compileall -q .` passed after adapter integration.

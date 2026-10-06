# Harness and production boundary

The invalid HIVE-FACTORIAL-003 remains immutable and permanently `EXPERIMENT_INVALID`: zero valid cells, one compromised cell, fifteen unstarted cells. Its source and evidence are read-only inputs here.

## MEASUREMENT HARNESS

Every Python file directly inside `HIVE-FACTORIAL-003/` belongs to the experiment harness. `evidence/harness-inventory.json` enumerates every top-level and nested function/class with its source line and file hash.

| Historical file | Responsibilities |
|---|---|
| common.py | Experiment paths, hashes, artifact persistence, event writer (`event(kind, **data)`), local-only environment |
| environment.py | Read-only identities, cache/image/baseline preflight, task/spec helpers, legacy outcome classification |
| freeze.py | Source/evidence inventory, frozen design, configuration and runtime identity capture |
| study.py | Initial cell setup, callbacks, verifier recorder, sequential execution and result collection |
| execute.py | Preserved setup-amended executor; nested `record_verifier`, wrappers, callbacks, aggregation and continuation guard |
| runtime_observer.py | Model HTTP request/stream recording and resource monitoring; not used for task inference here |
| results_analysis.py | Postprocessing, resources, exact statistics; does not implement Hive decisions |
| final_integrity.py | Planned completed-study audit; not used to rescore the invalid study |
| audit_stopped_study.py | Invalid-study integrity audit and partial trajectory extraction |
| build_stopped_report.py | Invalid-study report generation |

New repair and qualification code lives only in `HARNESS-QUALIFICATION-001/`. The repaired recorder is reusable by a future, separately authorized study; no old executor is overwritten or resumed. The new scripted-cell driver uses the actual frozen Hive controller and repaired recorder with injected **script fixtures instead of any model callback**. Provider functions are disabled for this qualification process.

## FROZEN HIVE PRODUCTION SOURCE

`HIVE-FACTORIAL-003/repaired-workshop/` is not harness repair scope. This includes `workshop/hive.py`, `hive_review.py`, `hive_protocol.py`, `providers.py`, `hive_edits.py`, `hive_context.py`, `external_root.py`, `hive_jvm.py`, `hive_verifier.py`, `verifier_trace.py`, `verification/jvm_runner.py`, `verification/nfrt_seed.py`, `app.py`, UI files, tests and all other frozen files.

`evidence/production-before.json` records all 162 frozen file hashes and sizes before recorder repair; source tree hash must remain `433d575ac0dfebab27e43d46c75a9e73ad66adb69dda196ba3455ed64ea9cd4b`. Baseline, all task/test identities, pinned image, tool versions, deadlines, NFRT manifest and policy are inherited unchanged. No production controller, prompt, verifier, model setting, attestation or promotion policy is edited.

In-memory installation of transparent wrappers is the measurement seam, not a production-file edit. It is explicitly qualified and restored in `finally`. Fixture-only fake verifiers are used in deterministic unit tests, never substituted for the real verifier in the A/B controls or scripted cell.

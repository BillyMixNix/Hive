# Reconstruction source links

The pre-instrumentation reconstruction is preserved separately. Concrete source references: preserved [host adapter](../HIVE-TRANSITION-003/repaired-workshop/workshop/hive_verifier.py), [Hive edit/rollback orchestration](../HIVE-TRANSITION-003/repaired-workshop/workshop/hive.py), [image entrypoint](evidence/image/runner.py), [byte-verified JVM runner](evidence/image/jvm_runner.py), and [candidate metadata](evidence/transition-003/candidate_metadata.json).

Relevant functions are `_bounded_process`, `run_jvm_profile`, `run_isolated`, `targeted_verify` and the nested `run_worker`. New per-replay `diagnostics/invocation.json` contains the exact observed command/cwd; historical missing temporary paths remain explicitly unknown.

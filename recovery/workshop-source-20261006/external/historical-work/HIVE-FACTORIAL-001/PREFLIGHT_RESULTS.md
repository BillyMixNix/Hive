# HIVE-FACTORIAL-001 apparatus preflight

Completed before any benchmark model request, 2026-10-04.

- Current Workshop source: `python -m compileall -q .` passed; `python -m pytest -q` yielded 382 passed, 6 skipped.
- Factorial runner: `python -m compileall -q runner.py preflight.py dry_run.py oracle_check.py test_runner.py` passed; focused harness tests yielded 4 passed.
- Exact approved baseline tree SHA-256: `230340980b85d60b7a59d3aa338dffc4447c1bb7d8df90bff4d0dbe89afe5388`.
- Exact sealed image ID: `sha256:b71e6beae584a3bba27e6fe782a27ef971b481b1dff7226bc57f28626843ad26`; approved offline cache/input provenance `e5a7c314b902` validated. The verifier remained network-disabled.
- The experiment child had no OpenAI key; the local endpoint is pinned to `127.0.0.1:11434`. The two installed model digests are captured in `FREEZE.json`.
- All four new hidden classes failed on untouched source for task-related reasons. J001/J002 ran three cases each with 1/2 failures respectively. J003/J004 failed Java compilation because the requested methods were absent. Raw outputs are in `preflight-evidence/baseline_red.json`.
- No-model single-agent adapter dry run accepted its exact-file plan, reached the backend role, skipped full verification for an empty proposal, rejected safely, and did not mutate the candidate or baseline. Raw run: `preflight-evidence/dry-run-runs/`.
- A separate disposable reference candidate passed all four hidden classes (12/12 JUnit cases) and then the unchanged full offline Gradle/GameTest gate. The full report recorded 163 passing JUnit tests and GameTest server execution; source immutability passed. Raw reports: `preflight-evidence/oracle-runs/oracle-targeted.json` and `oracle-full.json`. The candidate and baseline hashes were unchanged by verification. The reference candidate is outside every model's source root and is not an experimental outcome.
- No benchmark run, model request, cloud call, or promotion occurred during this preflight.

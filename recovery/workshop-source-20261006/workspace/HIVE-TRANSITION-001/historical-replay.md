# Preserved-response replay

Commands: `python HIVE-TRANSITION-001/replay.py before` and `python HIVE-TRANSITION-001/replay.py after` from the task workspace. Each uses its selected production implementation, a fresh isolated copy of the exact frozen baseline, and both preserved responses verbatim. No model call or new response is involved. The before run also asserts both prompts are identical to historical prompt bytes.

| Measurement | Before | Repaired |
|---|---|---|
| Response hashes equal historical hashes | Both | Both |
| First response | Rejected: missing multi-role contract | Rejected: unauthorized test file **and** missing multi-role contract |
| Correction schema | Arbitrary file paths; requires at least one contract | Exact host path enums; may deactivate unauthorized role without a contract |
| Corrected historical response | Rejected: unauthorized test file | Rejected: same unauthorized test file |
| Worker reached | No | No |
| Edited candidate | No | No |
| Verification | Not reached | Not reached |
| Terminal status | Failed, correction exhausted | Failed, correction exhausted |

Evidence: [before summary](evidence/replay-before/summary.json), [after summary](evidence/replay-after/summary.json), corresponding `calls.json` with full prompt/schema, and each run's `runs/<id>/run.json`. Both candidate and stage remain `230340980b85d60b7a59d3aa338dffc4447c1bb7d8df90bff4d0dbe89afe5388`.

The replay demonstrates more actionable correction, not progress of the preserved invalid outputs. Deterministic tests separately construct a valid scope-preserving plan and prove worker dispatch and isolated edit execution with explicitly synthetic verifier sentinels. Those synthetic results are not J001 acceptance evidence.

# HIVE Reliability Report

Date: 2026-05-05

Summary
-------
- Unsafe (adversarial) patches: 100 attempts — 0 accepted, 100 rejected (100% rejection).
- Safe (well-formed) patches: 100 attempts — 100 accepted, 0 rejected (100% acceptance).

Artifacts
---------
- Unsafe trial logs: [tmp_stress/log_unsafe.jsonl](tmp_stress/log_unsafe.jsonl)
- Safe trial logs: [tmp_stress/log_safe.jsonl](tmp_stress/log_safe.jsonl)
- Aggregated metrics (JSON): [tmp_stress/metrics.json](tmp_stress/metrics.json)
- Aggregated metrics (CSV): [tmp_stress/metrics.csv](tmp_stress/metrics.csv)

Findings
--------
- The executor's verification stage correctly flagged the unsafe patches. The dominant rejection reason observed is `mixed_scope_detected` (100 occurrences), i.e., patches mixing top-level and nested scope edits in the same diff.
- The safe patch generator produced contiguous, context-anchored replacements that passed verification, syntax, and semantic checks in sandbox.

Tier 2: Deeper Adversarial Suite
--------------------------------
We ran an expanded Tier-2 adversarial suite (100 iterations per case) to probe additional failure modes.

Results (100 iterations each):
- `syntax_failures`: 100 started, 0 succeeded, 100 failed — syntax-corrupt patches are blocked.
- `semantic_undefined_self_call`: 100 started, 0 succeeded, 100 failed — patches adding undefined `self.` calls are blocked.
- `wrong_target_edits`: 100 started, 0 succeeded, 100 failed — edits targeting non-existent anchors are blocked.
- `oversized_diffs`: 100 started, 0 succeeded, 100 failed — very large diffs are blocked by verification/semantics.
- `duplicate_helper_insertion`: 100 started, 0 succeeded, 100 failed — duplicate helper definitions or suspicious helper edits are blocked.
- `correct_context_wrong_intent`: 100 started, 100 succeeded, 0 failed — patches that preserve correct structural context but change behavior/intent are accepted by the executor.

Interpretation
--------------
- The executor's layered checks (context verification + semantic analysis) reliably block syntactic and structural adversarial cases.
- However, `correct_context_wrong_intent` demonstrates a deliberate blind spot: when a patch preserves structural context and passes semantic checks, intent-level regressions (logic changes) are not detected by the current executor. This is expected behavior for the executor's scope: it enforces structural safety, not correctness of intent.

Artifacts (Tier-2)
------------------
- Per-case logs: [tmp_stress/log_tier2_syntax_failures.jsonl](tmp_stress/log_tier2_syntax_failures.jsonl), [tmp_stress/log_tier2_semantic_undefined_self_call.jsonl](tmp_stress/log_tier2_semantic_undefined_self_call.jsonl), [tmp_stress/log_tier2_wrong_target_edits.jsonl](tmp_stress/log_tier2_wrong_target_edits.jsonl), [tmp_stress/log_tier2_oversized_diffs.jsonl](tmp_stress/log_tier2_oversized_diffs.jsonl), [tmp_stress/log_tier2_duplicate_helper_insertion.jsonl](tmp_stress/log_tier2_duplicate_helper_insertion.jsonl), [tmp_stress/log_tier2_correct_context_wrong_intent.jsonl](tmp_stress/log_tier2_correct_context_wrong_intent.jsonl)
- Aggregate Tier-2 metrics: [tmp_stress/metrics_tier2.json](tmp_stress/metrics_tier2.json)

Next steps
----------
1. Implement intent-drift detectors (unit-test execution, behavioral diffing, or differential fuzzing) and re-run Tier-2 to measure improvements.
2. Add timing metrics and failure-mode breakdowns to dashboards.
3. Run repository-wide intent tests and integrate into CI after validating detectors.

Intent-Drift Baseline (correct_context_wrong_intent)
-----------------------------------------------
We ran a focused intent-drift baseline against the `correct_context_wrong_intent` case to prove the detector catches this known blind spot.

Configuration:
- Trials: 200
- Target function: `compute(x)` in `tmp_stress/target_intent.py` (baseline behavior: return x*2)
- Test inputs: `[2, 3, 5]` → Expected outputs: `[4, 6, 10]`

Results:
- Applied patches: 200
- Drift detected (patched outputs != expected): 200
- Baseline matched expected before patch: 200
- Errors: 0

Artifacts:
- Per-trial intent logs: [tmp_stress/intent_checks.jsonl](tmp_stress/intent_checks.jsonl)
- Aggregated intent metrics: [tmp_stress/intent_metrics.json](tmp_stress/intent_metrics.json)

Conclusion:
- The intent detector reliably flagged all `correct_context_wrong_intent` patches in this baseline (100% detection rate). This proves we can catch intent-level regressions for focused, testable functions using execution-based behavior checks.

Next: expand detectors to derive per-function testcases from repo unit tests and integrate intent checks into the Tier-2 suite.
Next steps
1. Add richer adversarial inputs targeting other failure modes (syntax corruption, incomplete context, timeouts).
2. Extend metrics to include timing/latency and lesson reuse counts.
3. Integrate this stress run into CI with a smaller smoke-test matrix and a nightly full-run job.

Notes
-----
The logs contain per-trial reports with the executor's structured feedback. Use the JSONL files above to deep-dive into individual failure reports.

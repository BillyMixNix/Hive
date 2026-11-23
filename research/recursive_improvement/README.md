# Recursive Improvement Research — Prototype 0

**Status:** experimental gate, not an autonomous RSI system.

The first module is a fail-closed, deterministic comparison gate for independently generated baseline and candidate evaluation reports. It does **not** execute patches, grant filesystem authority, or claim that an LLM has learned.

## Research protocol

1. Freeze a baseline implementation and a held-out evaluation set before proposing a modification.
2. Use Hive's planner/coder to propose a candidate in a disposable worktree or container.
3. Run existing regression checks and both versions under identical model, budget, and environment settings.
4. Collect paired per-task correctness, cost, and latency measurements.
5. Apply the gate in `gate.py`; do not interpret its threshold as statistical significance.
6. Repeat with fresh held-out tasks and multiple seeds before claiming reproducibility.
7. Require human review for promotion. Never let candidate code edit tests, thresholds, evaluation data, or its own permissions.

## Initial acceptance gate

- Minimum 20 distinct matched cases.
- At least 5 percentage points higher observed correctness.
- No more than 10% higher total generation cost.
- Missing, duplicate, or mismatched cases raise errors.

This gate is deliberately conservative about data integrity, but **not** sufficient evidence of generalized improvement. Follow-up work must add confidence intervals, repeated independent trials, regression checks, full lifecycle cost, and an isolated candidate runner.

## Local tests

```bash
python -m unittest discover -s research/recursive_improvement -p 'test_*.py'
```

## Reuse targets

Hive's `planner.py`, `coder.py`, `executor.py`, `failure_intelligence.py`, `benchmark_harness.py`, and `regression_gate.py` are candidates for integration after API and sandbox review. Keep the semantic-state product path independent.

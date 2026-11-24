# Recursive Improvement Research — Prototype 0

**Status:** experimental gate, not an autonomous RSI system.

Experiment 1 now has a [container runner and frozen protocol](experiment1/README.md).
Use that controller for generated candidates. The older callback-based integration
below is retained for trusted unit fixtures and is not a hostile-code runner.

The first module is a fail-closed, deterministic comparison gate for independently generated baseline and candidate evaluation reports. The incremental integration in `integration.py` now connects Hive's existing planner/coder contracts to its isolated variant and recorded-regression APIs. It does **not** promote patches, grant broad filesystem authority, or claim that an LLM has learned.

## Research protocol

1. Freeze a baseline implementation and a held-out evaluation set before proposing a modification.
2. Use Hive's planner/coder to propose a candidate without applying it to the live checkout.
3. Run existing regression checks and both versions under identical model, budget, and environment settings.
4. Collect paired per-task correctness, cost, and latency measurements.
5. Apply the gate in `gate.py`; do not interpret its threshold as statistical significance.
6. Repeat with fresh held-out tasks and multiple seeds before claiming reproducibility.
7. Require human review for promotion. Never let candidate code edit tests, thresholds, evaluation data, the research integration, or its own permissions.

`CandidatePolicy` defaults to write authority over only `planner.py`, `coder.py`, and `executor.py`. It rejects path traversal, target/diff disagreement, and all paths under `tests/`, `validation/`, `research/recursive_improvement/`, and `.github/workflows/`, plus the benchmark and regression entrypoints. The core empirical gate now treats protected-directory entries as prefixes rather than exact filenames.

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

The integration invokes `RegressionGate` against the disposable repository before empirical scoring. A passing record can only become a non-deployed `candidate`; `integration.py` intentionally exposes no promotion function and stamps every result with:

- `prototype_status: candidate_evaluation_only`
- `promotion_allowed: false`
- `recursive_self_improvement_proven: false`

## Isolation limit

The disposable repository prevents ordinary candidate patches from changing the live checkout, and the single-file policy prevents direct edits to evaluators or tests. It is not an adversarial execution sandbox: generated Python evaluated by regression or benchmark processes still requires an OS/container boundary before it can be treated as hostile-code-safe.

## Reuse targets

Hive's `planner.py`, `coder.py`, `executor.py`, isolated variant gate, and `regression_gate.py` are now connected at prototype level. Repeated trials, an external execution sandbox, held-out task freezing, and independent evaluation remain required before any recursive-improvement claim. Keep the semantic-state product path independent.

# Empirical Validation Gate

The gate evaluates a proposed single-file patch against an isolated copy of the repository. It can recommend a patch as a **candidate**, but it never deploys that candidate automatically.

## Decision flow

1. Parse and validate the patch target.
2. Reject attempts to modify the benchmark, gate, scoring code, live judge, A/B evaluator, or CI workflows.
3. Copy the repository into a temporary variant.
4. Apply the patch only inside the variant.
5. Perform syntax/read verification and any caller-supplied checks.
6. Score the live baseline and isolated variant repeatedly.
7. Compare the mean improvement against Welch's standard-error noise band and an optional minimum effect.
8. Archive the complete decision, patch, hashes, and rollback material.
9. Return either `reject` or `candidate`.
10. Require a separate Pilot-approved promotion call before touching the live project.

## Basic use

```python
from pathlib import Path
from validation.gate import evaluate, promote_candidate

repo = Path.cwd()
record = evaluate(
    patch_text,
    "Describe the intended behavior",
    repo_root=repo,
    n=3,
    k=2.0,
)

if record["decision"] == "candidate":
    # Present record and evidence to the Pilot first.
    promote_candidate(
        record["evaluation_id"],
        repo_root=repo,
        pilot_approved=True,
    )
```

By default, scoring runs `ReliabilityBenchmarkHarness.run_pack()` in a subprocess and converts `passed_cases / total_cases` into a 0–1 score. Callers may supply a domain-specific `scorer(Path) -> float` and `verifier(Path, target_file)` when a task has a more meaningful behavioral test.

## Live patch loop

Normal `code task` execution now passes every generated patch through `validation.live_loop.evaluate_patch_result()` before the patch is stored for Pilot review.

The live adapter separates two questions:

- **Did the patch measurably complete the requested task?** Explicit completion cues provide a task-specific score with headroom even when the main benchmark already scores 1.0.
- **Did the patch preserve the rest of Hive?** The frozen reliability pack is run as a hard non-regression guard. A lower variant score rejects the patch before candidate scoring.

The resulting workflow is:

1. The coder proposes and sandbox-checks a patch.
2. The gate applies it to an isolated repository copy.
3. Missing completion cues, no measurable gain, regression, syntax failure, or judge tampering block the patch.
4. A measured improvement becomes `candidate` and is stored as `pending_pilot_review`.
5. `pilot accept patch <id>` records intent approval but does not deploy.
6. `apply patch <id>` deploys the archived candidate only if the live source still matches the evaluated baseline.
7. `rollback patch <id>` restores the archived pre-patch source and records the rollback.

Legacy patches created before live integration retain the executor fallback path, but newly generated patches use the archived empirical candidate.

## Paired lesson-memory A/B experiment

`validation.ab_run` compares the same ordered task sequence under two conditions:

- lessons enabled, with one shared lesson store across the sequence;
- lessons disabled, with the same tasks and worker configuration.

Arm order alternates between repeats to reduce run-order bias. The verdict requires the paired mean effect to exceed two standard errors without adding regressions.

Deterministic harness run:

```bash
python -m validation.ab_run --repeats 3 --output validation/results/lesson_ab.json
```

Live configured worker run:

```bash
python -m validation.ab_run --live --repeats 5 --output validation/results/live_lesson_ab.json
```

The live run requires the model provider configured for `ask_hive`; it does not silently substitute a different model.

## Governance guarantees

- Evaluation never modifies the live target.
- A candidate is not a deployment.
- Deployment requires an explicit Pilot apply command and `pilot_approved=True` inside the gate.
- Deployment is refused if the live target changed after evaluation.
- The evaluator, live judge, A/B runner, benchmark, scoring code, and CI workflows are protected from candidate modification.
- Failed patch verification preserves its structured check evidence instead of collapsing into an opaque executor error.
- Every evaluation, deployment, and rollback is recorded in an append-only JSONL archive.
- Deployed candidates retain the pre-patch content required for rollback.

## Current scope

Version 1 accepts existing, single-file unified diffs and requires explicit completion cues for live candidate evaluation. Multi-file transactions, new-file creation, and automatic lesson promotion remain later work. The A/B runner is ready for deterministic and live-provider experiments, but a live result is only evidence for the exact model, task pack, and configuration recorded for that run.

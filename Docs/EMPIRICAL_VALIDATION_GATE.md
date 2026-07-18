# Empirical Validation Gate

The gate evaluates a proposed single-file patch against an isolated copy of the repository. It can recommend a patch as a **candidate**, but it never deploys that candidate automatically.

## Decision flow

1. Parse and validate the patch target.
2. Reject attempts to modify the benchmark, gate, scoring code, or CI workflows.
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

## Governance guarantees

- Evaluation never modifies the live target.
- A candidate is not a deployment.
- Deployment requires explicit `pilot_approved=True`.
- Deployment is refused if the live target changed after evaluation.
- The evaluator and benchmark are protected from candidate modification.
- Failed patch verification preserves its structured check evidence instead of collapsing into an opaque executor error.
- Every evaluation and deployment is recorded in an append-only JSONL archive.
- Deployed candidates retain the pre-patch content required for rollback.

## Current scope

Version 1 intentionally accepts only existing, single-file unified diffs. Multi-file transactions, new-file creation, automatic lesson promotion, and live-loop integration remain later work. This keeps the first empirical claim narrow and testable.

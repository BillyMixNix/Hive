# HIVE-EVAL-009 — Closed-loop fresh-task evaluation

Final run: `orchestrated-runs/20260924-073647-a040db65`

## Frozen objective

Add `/companion activity reset` without changing the production checkout until
manual promotion.

## Preset routing budget

- Maximum local context: 35,000 characters
- Local attempt timeout: 600 seconds
- Maximum repairs per child: 1
- Oversize policy: decompose, then escalate only an indivisible or exhausted child
- Promotion: manual

Hive measured the original parent at 54,096 characters and selected the frozen
two-child decomposition before any worker edit:

1. Add and verify the activity reset service operation.
2. Seed that accepted operation into the dependent command-wiring child.

## Final result

- Service child: accepted on initial Qwen attempt
- Command child: accepted on initial Qwen attempt
- Dependent overlay: automatic
- Frozen acceptance test changed: no
- Combined full Gradle suite: passed
- API escalation used: no
- Production promotion: no
- Promotion bundle: `promotion-bundle/`

The final run required no prompt rewrite, child redesign, seed copying, retry
decision, or gate intervention after launch.

## Disclosed harness failures before the final run

Two earlier launches exposed dependency-gate classification defects. A blocked
Gradle wrapper download and a missing NeoForge plugin download were initially
treated as candidate failures. Hive now uses the installed Gradle distribution
and classifies dependency/network failures as environment failures without
spending model-repair budget. Those launches are retained as evidence and are
not counted as successful evaluations.

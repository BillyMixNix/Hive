# First-Principles Collective Experiment

This is a clean research track inside Hive. It does not modify or depend on the legacy agent/lesson runtime.

## Hypothesis

Cognitive action can be decomposed across bounded cognitive nodes, and interaction plus explicit compilation of their partial artifacts can produce a more useful collective state than an individual node or uncompiled collection of outputs.

The research target is **collectively produced capability**, not an assumption of emergence or AGI.

## Architecture

```text
Task
  -> bounded cognitive nodes
  -> CognitiveArtifact[]
  -> CollectiveCompiler
  -> CollectiveState
  -> next operation / action
  -> observation
  -> next cycle
```

The compiler is deliberately distinct from a summarizer. It preserves claims, evidence, uncertainty, conflicts, proposed actions, and provenance.

## Required baselines

1. Single model / single operation
2. Structured single model
3. Multiple independent nodes + concatenation
4. Multiple bounded nodes + compiler
5. Multiple bounded nodes + compiler + persistent state
6. Same system with iterative feedback

All comparisons should be budget-matched where practical: model calls, tokens, wall-clock time, and tool calls.

## First decisive experiment

Start with a controlled evidence-integration task rather than a coding task. Choose tasks where the answer depends on combining partial evidence and where individual pieces are insufficient alone.

Measure:

- correctness / task success
- evidence coverage
- contradiction handling
- uncertainty calibration
- provenance completeness
- calls and tokens
- wall-clock time
- cost per successful result

The key falsification question is:

> Does explicit decomposition + artifact compilation + state-mediated iteration outperform the strongest budget-matched single-node baseline and simpler multi-node aggregation?

If not, the architecture has not earned additional complexity.

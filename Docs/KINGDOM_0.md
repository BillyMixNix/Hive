# Kingdom-0 / Mind Constructor

Kingdom is an experimental layer above Hive's regression-first contract.

Its mission is not merely to generate more reasoning. It is to turn a compressed human intent into a recursively navigable construction process:

`idea -> decompression -> incompatible worlds -> exploration -> reality contact -> structural reintegration -> executable frontier -> recurse`

## What exists on this branch

### Cognitive topology

`KingdomEngine` provides bounded branch expansion, deduplication, parallel exploration, structural reintegration, a cognitive packet, comprehension probes, and a tamper-evident run ledger.

### Incompatible worlds

`WorldBranchingProvider` injects explicit premise-level interventions before ordinary model-generated branches. The default basis includes premise-true, premise-false, minimum-viable, capability-max, adversarial, and outside-frame worlds.

This is meant to prevent fake diversity where many workers merely paraphrase the same assumptions.

### Arena

`ArenaRegistry` gives branches an explicit reality-contact layer. Current concrete adapters include repository read, repository search, and pre-registered deterministic simulations.

Arena distinguishes three evidence states:

- verified: the tool actually returned an observation
- failed: the operation ran but failed
- unavailable: the requested capability does not exist

An unavailable capability is not silently substituted and is not a terminal error.

### Recursive construction

`MindConstructor` promotes unavailable Arena capabilities into `BuildTarget` nodes attached to the branch that required them.

When a `TargetDecomposer` is supplied, blocked targets are decomposed again into predecessor tools, capabilities, or experiments until the configured construction depth/target budget is reached or an executable frontier appears.

This is the first software implementation of the working hypothesis:

> a blocker can itself become another decompression target rather than ending the inquiry.

### Zoomable reintegration

`CognitiveNavigator` retains stable references from structural claims back to the branch evidence that exposed them. The human-facing packet can remain compact without forcing provenance to disappear.

## Live construct mode

```bash
python -m kingdom "Build an artificial decompression intelligence" \
  --construct \
  --branches 12 \
  --worlds 6 \
  --depth 1 \
  --construction-depth 3 \
  --target-budget 40
```

Construct mode currently performs:

1. forced incompatible worlds plus model-generated branches
2. branch exploration
3. Arena planning
4. execution of available Arena tools
5. missing-capability promotion
6. bounded recursive blocker decomposition
7. reintegration with Arena observations included as evidence
8. construction-frontier reporting

`--construction-depth` currently bounds recursive construction graph depth; `--target-budget` bounds total construction targets.

## Honesty boundary

Kingdom still does not treat model-generated prose as external evidence. Only actual Arena observations are upgraded to observation evidence.

The current Arena is intentionally narrow. It does not yet expose unrestricted shell execution or unrestricted network access. Those should arrive as separately sandboxed, provenance-preserving adapters rather than as implicit powers of the model.

The current recursive construction layer can decompose missing tools into predecessor targets, but it does not yet automatically implement arbitrary generated tools and load them back into Arena. That build-test-register loop is the next major engineering step.

## Research claim still open

The branch demonstrates that the architecture is implementable and can be regression-gated. It does **not** yet prove generalized cognitive amplification.

The stronger test remains whether this coupled human-machine process can solve or construct across problem spaces that exceed the operator's unaided search bandwidth while preserving enough structure for meaningful human direction.

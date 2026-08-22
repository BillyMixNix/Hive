# Kingdom-0 / Mind Constructor

Kingdom is an experimental layer above Hive's regression-first contract.

Its mission is not merely to generate more reasoning. It is to turn a compressed human intent into a recursively navigable construction process:

`idea -> decompression -> incompatible worlds -> exploration -> reality contact -> structural reintegration -> executable frontier -> acquire capability -> recurse`

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

Construction depth is measured relative to each promoted blocker rather than from the original seed.

This implements the working hypothesis:

> a blocker can itself become another decompression target rather than ending the inquiry.

### Capability Forge

Construct mode can optionally enable `CapabilityForge` with `--forge-missing`.

The forge handles only a deliberately narrow capability class: one deterministic Python function `execute(payload)` with no imports, attributes, classes, decorators, file/network/process access, or arbitrary function calls. A model proposal does not receive authority merely because it exists.

A candidate must pass this sequence:

1. restricted AST policy
2. JSON-serializable executable cases
3. Hive `RegressionGate` against those cases in a timeout-bound subprocess
4. a second isolated runtime execution of every case
5. Arena registration only after both validation layers pass
6. immediate retry of the exact request that originally failed

If the retry returns a verified observation, the blocked capability target becomes verified and that evidence is fed into structural reintegration. If forging is impossible or validation fails, the blocker remains in the construction graph and may be recursively decomposed instead.

The forge is intentionally opt-in. It is a capability-acquisition experiment, not a general Python sandbox or unrestricted self-modification mechanism.

### Zoomable reintegration

`CognitiveNavigator` retains stable references from structural claims back to the branch evidence that exposed them. The human-facing packet can remain compact without forcing provenance to disappear.

## Live construct mode

```bash
python -m kingdom "Build an artificial decompression intelligence" \
  --construct \
  --forge-missing \
  --branches 12 \
  --worlds 6 \
  --depth 1 \
  --construction-depth 3 \
  --target-budget 40
```

Construct mode can now perform:

1. forced incompatible worlds plus model-generated branches
2. branch exploration
3. Arena planning
4. execution of available Arena tools
5. missing-capability promotion
6. optional restricted capability forging and regression validation
7. registration and retry when a forged capability survives validation
8. bounded recursive decomposition of blockers that remain unresolved
9. reintegration with Arena and forge observations included as evidence
10. construction-frontier reporting

`--construction-depth` bounds levels below each unresolved blocker; `--target-budget` bounds total construction targets.

## Honesty and authority boundary

Kingdom does not treat model-generated prose as external evidence. Only actual Arena observations are upgraded to observation evidence.

The current Arena is intentionally narrow. It does not expose unrestricted shell execution or unrestricted network access. Generated capabilities are restricted pure functions and execute in isolated timeout-bound Python processes after validation.

This is defense in depth for a tiny generated-code class, not a claim of a complete security sandbox. Multi-file implementations, package installation, shell commands, network clients, privileged APIs, and persistent host mutation remain outside generated-tool authority and should arrive as separately designed host-owned adapters with their own validation contracts.

The next engineering frontier is broader but still gated capability construction:

`missing capability -> implementation plan -> isolated candidate workspace -> task-specific oracle/tests -> Hive regression/reliability gates -> explicit adapter registration -> retry original branch`

That would let Kingdom construct more substantial tools without collapsing the distinction between proposing code and earning authority.

## Research claim still open

The branch demonstrates that the architecture is implementable and can be regression-gated. It does **not** yet prove generalized cognitive amplification or generalized autonomous construction.

The stronger test remains whether this coupled human-machine process can solve or construct across problem spaces that exceed the operator's unaided search bandwidth while preserving enough structure for meaningful human direction.

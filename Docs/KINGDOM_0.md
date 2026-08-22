# Kingdom-0: Cognitive Decompression Vertical Slice

Kingdom-0 is an experimental human-centered reasoning layer for Hive.

Its claim is deliberately narrower than "more agents are smarter":

> A system can expand one compressed human idea into many divergent investigations, preserve the evidence and disagreements discovered there, reintegrate the structure into a bounded cognitive packet, and then test whether the operator actually reconstructed that structure.

## Loop

1. **Seed** — accept an incomplete idea, question, or intuition.
2. **Decompress** — create divergent branches with different lenses and assumption shifts.
3. **Explore** — run branches independently and allow promising branches to spawn bounded children.
4. **Preserve evidence** — findings distinguish support, contradiction, observation, and uncertainty.
5. **Reintegrate structure** — extract invariants, disagreements, hinge assumptions, causal links, anomalies, and unknowns rather than majority-voting branch answers.
6. **Encode** — create a bounded cognitive packet optimized for reconstructable understanding.
7. **Probe** — generate transfer/counterfactual questions rather than recall questions.
8. **Re-expand** — comprehension failures identify concepts that should be decompressed again.

All runs are persisted under `.hive/kingdom/runs/` and a hash-chained append-only ledger records run and comprehension-assessment events.

## Run it

Kingdom-0 uses Hive's existing `ask_hive()` model router, so the same local Ollama / configured Anthropic behavior applies.

```bash
python -m kingdom "Can cognition be externally extensible?" \
  --branches 12 \
  --depth 1 \
  --workers 4
```

The command prints a cognitive packet and 3-5 comprehension probes. Use `--json` to inspect the complete branch tree, evidence, structural map, provenance, packet, and probes.

## Why a provider boundary exists

The orchestration core depends on a `KingdomProvider` protocol rather than a specific model. The current `HiveLLMProvider` is only one implementation. This keeps the experimental object stable while models, tool runtimes, or branch workers change.

It also makes the core deterministic-testable: tests use a fake provider and do not spend model credits.

## Cognitive amplification metric

`kingdom.benchmark` includes a minimal transfer metric. A trial records:

- transfer questions answered correctly,
- total transfer questions,
- human attention consumed (in whatever unit the experiment fixes in advance).

For an assisted condition compared with a baseline:

```text
accuracy_gain = assisted_accuracy - baseline_accuracy
gain_per_assisted_attention = accuracy_gain / assisted_attention
```

This prevents a raw branch dump from looking superior merely because the operator read dramatically more material.

A real experiment should compare at least:

- human alone,
- human + ordinary answer,
- human + flat multi-branch summary,
- human + Kingdom structural codec,

while holding the human-facing attention budget as constant as possible.

## Current boundary

Kingdom-0 does **not** claim that an LLM-generated evidence string is reality. The live provider explicitly instructs branches not to invent sources or tests; when no external oracle is available, evidence should remain uncertain.

The next serious milestone is an Arena adapter that gives selected branches executable/web/repository/simulation tools and records machine-verifiable evidence into the same provenance graph.

The research target is not "more generated text." It is measurable transfer of useful structure across a human attention bottleneck.

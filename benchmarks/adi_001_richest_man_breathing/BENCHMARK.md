# ADI Benchmark 001 — I Became the World's Richest Man by Breathing

## Research question

Can a recursively decomposing, reality/continuity-checking cognitive architecture preserve and develop one compressed human creative intent across a narrative horizon too large for a single model context, better than a strong model operating as a conventional sequential writer under a comparable generation budget?

This benchmark is a long-horizon semantic test, not a claim that prose quality alone proves cognitive amplification.

## Canonical seed and neutral contract

`SEED.md` is the frozen human story specification. `CONTRACT.md` contains only the story obligations shared by both writers. The experimental protocol in this file is deliberately **not** supplied as writer context, because exposing the treatment strategy to the control condition would contaminate the A/B comparison.

Runs hash the exact seed and neutral contract and must refuse continuation if either changes.

## Human intent anchors

1. Ren Fujitsu begins as a broke, twenty-six-year-old delivery driver whose concerns are painfully ordinary.
2. The foundational rule is exact and legible: inhale longer than exhale => +$1; exhale longer than inhale => -$1; equal => $0.
3. The money is legally recognized by reality. The mystery is not ordinary fraud.
4. Money-Breathing is secretly the primitive child technique of the Fujitsu Clan's Dao of Exchange.
5. Ren is not a finance prodigy. Experimentation, curiosity, learning, and occasional recklessness are central to his progression.
6. Tone begins as comedy/economic wish fulfillment and gradually becomes serious modern wuxia and civilizational philosophy.
7. Progression must be earned through intermediate conceptual steps: profitable breath -> circulation of wealth -> productive assets -> civilization as formation -> abstract exchange -> multiversal exchange.
8. Productive circulation matters more than hoarding. Ren grows most efficiently when the systems and people around him become more capable and prosperous.
9. Modern civilization is itself cultivation substrate: money, attention, networks, law, logistics, information, medicine, authority, and other concepts can become Daos.
10. The final philosophical correction is not "everything has a price" but "value exists because someone chooses what matters." The intentional -$1 breath must be earned by the entire prior story.
11. `DIVINE ART — MULTIVERSAL MARKETPLACE` is the logical outer expansion of Exchange, not an unrelated late-story DLC mechanic.
12. The Marketplace equalizes desire rather than resources, requires genuine recognized exchange, uses escrow, cross-reality delivery, and generates Exchange Authority by bridging otherwise impossible exchanges.
13. Ren's ultimate strength comes from enabling exchange and becoming indispensable, not merely conquering or owning.
14. The novel should remain recognizably the same story promised by Chapter One even hundreds of chapters later.

## Anti-drift constraints

The generator must not silently convert the story into a generic system novel, generic billionaire fantasy, generic cultivation academy, or generic multiverse shop story. New material must attach to an existing intent anchor or create an explicit new dependency that remains inspectable.

Power escalation without prerequisite setup is a failure. Continuity patches that merely explain away contradictions after the fact are weaker than preventing or tracing the contradiction.

## Long-horizon obligations

The experiment tracks at minimum:

- character-state continuity
- who-knows-what continuity
- financial/economic state
- cultivation realm and unlocked mechanics
- technique rules and exceptions
- businesses/assets and their causal role
- promises, debts, contracts, favors, and obligations
- factions and institutional incentives
- mysteries and foreshadowing
- unresolved plot threads
- thematic claims and counterclaims
- chapter-level setup/payoff dependencies
- tone trajectory
- original-intent alignment

## Experimental conditions

### Baseline

A strong model receives the canonical seed, the neutral story contract, previous prose/memory support allowed by the chosen baseline protocol, and a matched generation-call budget. It writes sequentially without Kingdom's recursive construction graph, explicit incompatible-world exploration, dependency closure, or terminal intent walk.

The executable pilot gives the baseline seven model calls per generated chapter: an initial sequential draft, five ordinary revision passes, and one final polish. Its shared post-chapter state extraction is evaluation/memory bookkeeping and is counted separately from generation, exactly as on the Kingdom side.

### Kingdom / ADI

The same canonical seed and neutral story contract are used. The system decomposes narrative obligations, uses specialized subagents/workers for independent planning and challenge, maintains dependency/provenance state, generates chapters against that state, performs continuity/semantic checks, and runs a Critical-Path revision against the original seed.

For the executable pilot, Kingdom receives the same seven generation calls per chapter:

1. continuity specialist
2. progression/economics specialist
3. character/theme specialist
4. adversarial contradiction specialist
5. synthesis specialist
6. prose synthesis
7. Critical-Path prose revision

The first four specialist calls are independent proposals and do not see one another's work. Synthesis resolves them against the immutable seed and persistent state. Proposal is not authority.

The harness passes an explicit `model=` override to Hive for every generation and evaluator call, preventing role routing from silently using stronger models for one side.

## Evaluation

Measure at checkpoints such as chapters 10, 25, 50, 100, 250, 500, and 1000. The pilot defaults to 5 and 10 so harness failures are discovered before large generation spend.

Primary measures:

- contradiction count per 100k words
- unresolved promised-thread rate
- setup/payoff success rate
- character consistency
- progression-rule consistency
- causal traceability of major developments
- original-intent retention
- blind-reader preference for coherence, payoff, engagement, and perceived intentionality

The executable harness also emits an automatic model-based checkpoint score and an automatically blinded pairwise comparison. Those are diagnostics, not independent evidence: the decisive version of the experiment still requires blind human readers or an independently validated evaluator.

Critical prediction:

> If externally extensible cognition is useful, Kingdom's relative advantage should increase as narrative horizon and dependency density increase, rather than merely producing better Chapter 2 prose.

## Executable pilot

Run both conditions through the same explicit model and the same neutral contract:

```bash
python -m kingdom.webnovel_benchmark \
  --seed-file benchmarks/adi_001_richest_man_breathing/SEED.md \
  --benchmark-file benchmarks/adi_001_richest_man_breathing/CONTRACT.md \
  --output-dir .hive/benchmarks/adi_001/pilot-10 \
  --chapters 10 \
  --checkpoint 5 \
  --checkpoint 10 \
  --model qwen2.5-coder:7b
```

The run directory contains:

- a manifest with seed/contract hashes, explicit model, and budgets
- separate baseline and Kingdom chapter streams
- persistent extracted narrative state for both streams
- an auditable model-call ledger containing prompt/response hashes and character counts
- checkpoint JSON with per-condition diagnostics and Kingdom-minus-baseline delta
- a result summary stating the longitudinal prediction and the human-evaluation boundary

The harness can continue an existing output directory only when its frozen seed, neutral contract, and model still match the manifest.

## Pass/fail honesty boundary

A beautiful chapter does not prove the theory.

A useful result requires longitudinal comparison against a baseline, explicit failure accounting, and ideally blind human evaluation. The benchmark is successful as an apparatus if it can expose where and why the long-form narrative drifts, even if Kingdom ultimately loses.

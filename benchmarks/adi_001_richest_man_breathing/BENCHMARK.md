# ADI Benchmark 001 — I Became the World's Richest Man by Breathing

## Research question

Can a recursively decomposing, reality/continuity-checking cognitive architecture preserve and develop one compressed human creative intent across a narrative horizon too large for a single model context, better than a strong model operating as a conventional sequential writer under a comparable generation budget?

This benchmark is a long-horizon semantic test, not a claim that prose quality alone proves cognitive amplification.

## Canonical seed and neutral contract

`SEED.md` is the frozen human story specification. `CONTRACT.md` contains only the story obligations shared by both writers. `STORY_MAP.json` is a frozen, hash-checked authority map that separates timeless rules, published Chapter-One canon, and locked future blueprint. It also supplies the exact Chapter-One starting state and continuation tail. The experimental protocol in this file is deliberately **not** supplied as writer context, because exposing the treatment strategy to the control condition would contaminate the A/B comparison.

Runs hash the UTF-8 text projection of the seed and contract (with platform newlines decoded consistently), plus the exact Story Map text, initial state, deterministic projections, model tag, and installed model digest. They must refuse continuation if any identity changes.

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

A strong model receives the same static authority packet, source facts, eligible frontier, locked authorial direction, and previous prose as the Kingdom condition, under a matched generation-call budget. Its dynamic memory is rendered as conventional flat rolling notes, without claim IDs, statuses, dependency edges, or provenance metadata. It writes sequentially without Kingdom's recursive construction graph, explicit incompatible-world exploration, dependency closure, or terminal intent walk.

The executable pilot gives the baseline three model calls per generated chapter: an ordinary chapter plan, a prose draft, and one holistic conventional revision. Its shared post-chapter state extraction is evaluation/memory bookkeeping and is counted separately from generation, exactly as on the Kingdom side.

### Kingdom / ADI

The same byte-identical static authority packet is used. The same accepted source facts are rendered for Kingdom as a typed claim ledger with statuses, dependency edges, and provenance; that structural representation is part of the treatment under test. The system generates chapters against that state, performs continuity/semantic checks, and runs a Critical-Path revision against the original intent.

For the executable pilot, Kingdom receives the same three generation calls per chapter:

1. structured dependency plan
2. prose synthesis
3. Critical-Path prose revision

The first call decompresses continuity, knowledge, obligations, progression/economics, character/theme, setup/payoff, and adversarial failure search into one structured proposal. The second writes prose from that proposal. The third walks the immutable intent and dependency plan through the completed draft. Proposal is not authority.

The harness passes the same explicit `model=` override, 32,768-token Ollama context, 2,048-token maximum output, and 900-second request timeout to every baseline, Kingdom, extraction, and evaluator call. Role labels therefore cannot silently route one side to a stronger model or different runtime budget.

The harness also fixes temperature and sampling seed, disables hidden HTTP retries, records Ollama completion/token metadata, and invalidates truncated calls. One ledger row therefore corresponds to one physical model request.

The compressed protocol is stage-matched to avoid a prose-pass confound. Both conditions receive exactly one planning call, one prose-draft call, and one revision call. The treatment difference is ordinary planning plus ordinary revision versus dependency-aware planning plus Critical-Path revision.

This three-call pilot does **not** test the independent-agent proposal diversity of the earlier seven-call design. The continuity, progression/economics, character/theme, and adversarial lenses are compressed into one structured planning call. Claims from this pilot must therefore be limited to structured decompression plus terminal verification under a matched stage budget.

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

First run the Chapter-Two smoke through both conditions with the same explicit model and authority boundary:

```bash
python -m kingdom.webnovel_benchmark \
  --seed-file benchmarks/adi_001_richest_man_breathing/SEED.md \
  --benchmark-file benchmarks/adi_001_richest_man_breathing/CONTRACT.md \
  --story-map-file benchmarks/adi_001_richest_man_breathing/STORY_MAP.json \
  --output-dir .hive/benchmarks/adi_001/smoke-story-map-v1 \
  --chapters 2 \
  --checkpoint 2 \
  --model qwen2.5-coder:7b
```

`STORY_MAP.json` currently freezes the Chapter-Two frontier deliberately. A ten-chapter launch must wait until Chapters 3–10 receive the same reviewed frontier/prerequisite treatment; the runner fails closed when a requested chapter has no frozen frontier.

The run directory contains:

- a manifest with seed/contract hashes, explicit model tag/digest, and budgets
- the Story Map, initial-state, Chapter-One, prompt-projection, and guard identities
- separate baseline and Kingdom chapter streams
- persistent canonical claim ledgers whose ordinary state views are derived only from accepted evidence
- atomic, hash-linked chapter artifacts containing prose, proposed deltas, accepted state, gate result, and call hashes
- an auditable model-call ledger containing prompt/response hashes and character counts
- checkpoint JSON with per-condition diagnostics and Kingdom-minus-baseline delta
- a result summary stating the longitudinal prediction and the human-evaluation boundary

After the remaining frontiers are frozen, a clean 10-chapter run will still have 78 accepted ledger records: 54 generation calls (9 generated chapters × 2 conditions × 3), 18 shared state extractions, 4 automatic checkpoint scores, and 2 blinded pairwise comparisons.

The harness refuses a changed protocol on resume: seed, neutral contract, model, chapter/checkpoint configuration, three-call pipelines, context clipping, and Ollama runtime limits must all match the manifest.

For evidentiary runs, use a fresh output directory. A chapter becomes authoritative only when its prose, state delta, deterministic gate result, and ancestry are committed together as one atomic artifact. Rejected prose and rejected extractor proposals are preserved outside canonical history. The runner reconciles completed history against the exact call ledger and refuses asymmetric, incomplete-checkpoint, or corrupt histories rather than silently resuming them.

The shared extractor never receives the undifferentiated future seed. It sees only immutable rule anchors, prior accepted canon, and the current final chapter. Its JSON is a proposal: deterministic code requires exact current-chapter evidence, legal transitions, satisfied dependencies, grounded numbers, and absence of locked future material before promotion. This validation consumes no model calls and is identical for both conditions.

## Pass/fail honesty boundary

A beautiful chapter does not prove the theory.

A useful result requires longitudinal comparison against a baseline, explicit failure accounting, and ideally blind human evaluation. The benchmark is successful as an apparatus if it can expose where and why the long-form narrative drifts, even if Kingdom ultimately loses.

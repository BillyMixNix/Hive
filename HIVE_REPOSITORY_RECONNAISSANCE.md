# Hive Repository Reconnaissance

Status: Phase 1 complete

Reference revision before this work: `7f8ae1877d5d9093824527a018ddf2f135ccd98b`
Scope: read-only archaeology of the Hive repository; no inference run and no prior benchmark artifacts modified.

## Executive finding

There is no existing whole-system Hive model hidden in the repository. There are five strong but disconnected implementation islands:

1. a deterministic causal/temporal benchmark ledger and fixed compressed codec;
2. a narrative-specific authority and canonical-state guard;
3. auditable, matched model-call and experiment infrastructure;
4. Kingdom construction, navigation, provenance, and intent structures;
5. code-agent lesson, candidate-validation, promotion, and rollback loops.

The smallest responsible next step is a new, small, domain-neutral reference-model package with adapters to those systems. Promoting any existing island into the whole architecture would silently inherit the wrong domain assumptions.

## Reuse map

| Existing component | Reuse decision | Reference-model role | Important limit |
|---|---|---|---|
| `kingdom/decompression_test.py` and frozen case pack | Reuse directly through an adapter | Experiment A/B/C fixture; deterministic replay; fixed codec; raw/retrieval/compressed packets; ablation | It is an engineered, query-blind event serialization, not learned abstraction |
| `kingdom/protocol_v2_audit.py` | Reuse directly for model-backed experiments | Fresh-run enforcement, one physical attempt, raw prompt/response artifacts, hashes, token and latency metadata | It is model-call evidence plumbing, not a scorer or state model |
| `hive_llm.py` | Reuse behind a replaceable transport | Local Ollama and external solver access with explicit runtime settings | Frozen experiments must bypass role routing and retries |
| `kingdom/story_map.py` | Reuse its validation patterns | Exact schemas, evidence-bound claims, dependency validation, non-promotion of future plans | Its categories and lifecycle are webnovel-specific and not bitemporal |
| `kingdom/adi_story_boundary.py` | Reuse its anchoring patterns | Content hashes, source identity, immutable authority boundary, exact evidence | It is tied to ADI/Kingdom chapter semantics |
| `kingdom/core.py` `HashChainLedger` | Reuse or adapt for evidence anchoring | Append-only, hash-linked experiment and claim records | Timestamped JSONL is tamper-evident, not a transactional database |
| `kingdom/persistence.py` | Reuse content-hash and resume patterns | Immutable checkpoints and provenance records | Construction-domain schema only |
| `validation/gate.py`, `variant.py`, `archive.py` | Reuse the governance pattern | Isolated candidate evaluation, explicit promotion, rollback, protected graders | The implementation mutates code patches, not representations |
| `kingdom/forge.py` | Reuse the proposer/oracle separation pattern | Candidate proposal, independent validation, register only after passing | The actual policy and sandbox are Python-capability-specific |
| `twin_realms/engine.py`, `simulation.py`, `models.py` | Optional deterministic-world adapter | Replay, invariants, snapshots, more complex synthetic environments | State is game-specific and events are not a generic epistemic ledger |
| `twin_realms/knowledge.py` | Reuse the separation principle | Observations do not affect the world until explicitly admitted | Its repeated-observation confidence heuristic is not a general truth rule |
| `twin_realms/narrative.py` | Reuse the authority-boundary pattern | A model may render or propose but never receives mutable simulation authority | Narrative fallback is domain-specific |
| `kingdom/navigation.py` | Reuse provenance/navigation ideas | Inspectable reconstruction references and bounded expansion | References point to Kingdom branch summaries, not generic event spans |
| `kingdom/construction.py` | Adapt dependency/frontier concepts | Construction paths, dependency closure, explicit status | It is a mutable single-parent tree, not a strict causal DAG |
| `kingdom/intent_path.py` | Adapt intent capture and verification ideas | Original-intent constraints and verification paths | Domain/application proof mechanism, not generic memory |
| `kingdom/protocol_v2_metrics.py` | Reuse strict metric-validation patterns | Bounded metrics, deterministic derived fields, trajectories | Its additive narrative degradation score is not representation fitness |
| `validation/ab_run.py`, `validation/scoring.py` | Reuse paired-order/statistics patterns | Counterbalancing and later replicated comparisons | Existing measures target lesson reuse/code reliability |

## Components that must not become the core

### `HiveStateManager.py`

This is a mutable code-session snapshot. It stores file state, patch history, tasks, agents, and observability data, and reconciles files from disk. It is not an event-sourced model of world truth, authority, or provenance.

### `repo_map.py`

Repo Map is a Python AST index of files, symbols, imports, calls, and spans. It is useful for source-code navigation, but it has no temporal validity, authority, evidence lineage, contradiction, state promotion, causal mechanism, or reconstruction contract. It is not an Idea Map or a semantic architecture graph.

### `kingdom/benchmark.py` fitness shortcuts

The `understanding_per_attention` style scores collapse correctness and cost into one scalar. The reference model requires hard validity constraints and a Pareto frontier; a small representation that loses transfer or authority correctness cannot win by arithmetic averaging.

### Legacy lesson memory as abstraction learning

`HiveLessonMemory.py` and `failure_intelligence.py` contain useful failure records, routing, counters, and promotion heuristics. They are prompt-advice memories whose generalizations remain human-shaped strings and thresholds. Existing evidence is mixed. They must not be relabeled as learned concepts or recursive improvement.

## Layer-by-layer gaps

| Required layer | What exists | What is missing |
|---|---|---|
| Observation | Arena observations and Story evidence | Generic immutable, content-addressed observations with actor/tool/model/source identity |
| Canonical event | Frozen benchmark `Event`; Twin Realms events | Generic entities, relations, claims, evidence, dependencies, effective time, record time, and state transitions |
| Authority and epistemics | StoryGuard promotion discipline | Separate basis, truth, temporal validity, confidence, supersession, contradiction objects, and multi-source lineage |
| World state | Benchmark and Twin Realms replay | Generic bitemporal projection, historical query, counterfactual replay, and unknown/disputed facts |
| Compression | Fixed benchmark codec | Structural, causal, conceptual, temporal, procedural, and failure representation objects with preserve/discard contracts |
| Decompression | Prompt packets and answer grading | First-class task-conditioned selection and lineage-bearing reconstruction API |
| Minimum sufficient state | Five one-effect ablations | Generic singleton and bounded combinatorial ablation; multiple minimal sufficient sets |
| Abstraction | Free-text `StructureMap` | Invariant, scope, instances, counterexamples, prerequisites, reconstruction rules, and uncertainty |
| Transfer | Small transfer scaffolds | Locked unseen generators, task families, structural and cross-domain transfer taxonomy |
| Representation learning | None | Query-blind candidate generation, downstream evaluation, cost accounting, and held-out selection |
| Fitness | Benchmark-specific scores | Multiobjective quality/cost vector, hard safety constraints, Pareto comparison |
| Meta-representation | Lesson outcome counters | Representation-family x solver x task profiles and calibrated known failure modes |
| Repair | Code patch promotion/rollback | Immutable representation versions, regression evaluation, migration, rollback |
| Recursive improvement | No valid implementation | Matched meta-heldout experiment testing improved future representation discovery |
| Solver separation | Replaceable transports and recent evidence | Generic capability gate that blocks interpretation when Raw is not solvable |
| Evidence/research registry | Benchmark artifacts only | Whole-program claim registry, evidence map, architecture graph, and research DAG |

## Evidence already present

### Established within a frozen artifact

- The deterministic codec and replay checks preserve the designated canonical event/state/reference information on the frozen decompression case pack while reducing visible state bytes.
- Protocol v2.1 completed a valid, matched local run with one Qwen2.5-Coder 7B digest. Raw scored 5/20, Retrieval 3/20, and Compressed 4/20, with widespread selected-option chronology/authority errors. This establishes a solver-capability limitation for that model/benchmark pairing, not a compression failure or advantage.

### Supporting but exploratory

- The operator-reported, history-isolated Codex solve achieved 20/20 for Raw, Retrieval, and Compressed and 10/10 on the ablation set, with no chronology errors or illegal promotions. Compressed used roughly 51% of Raw prompt bytes and 20% of Raw supplied-state bytes.
- No sealed tracked artifact for this Codex run is present in this branch. The claim registry must identify it as operator-supplied exploratory evidence unless a separately sealed artifact is later imported.

### Not established

- superiority over Raw or Retrieval;
- automatic discovery of canonical event semantics;
- learned compression or abstraction;
- held-out structural or cross-domain transfer;
- causal mechanism discovery;
- representation fault localization or repair;
- meta-learning or recursive representation improvement.

## Integration boundary

The reference model will:

1. own a small generic event, authority, state, representation, evaluation, and versioning core;
2. keep all observations, events, and representation versions immutable and provenance-linked;
3. treat model outputs as proposals and keep deterministic gates authoritative;
4. adapt the frozen decompression benchmark rather than copy or modify it;
5. use the existing audited call store only for inference-backed experiments;
6. reproduce the validation gate's candidate/evaluate/promote/rollback discipline for representations;
7. generate the architecture, evidence, and research graphs from explicit machine-readable registries rather than Repo Map;
8. run deterministic tests and demonstrations without any model dependency.

## Phase 1 conclusion

The repository already contains credible pieces of an experimental research system. It does not contain learned abstraction or recursive improvement under a different name. The architecture should preserve the working pieces, make the missing mechanisms explicit, and create executable seams where the speculative claims can later be falsified.

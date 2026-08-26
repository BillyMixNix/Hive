# Hive Evidence Map

Authority evidence in this map applies to the immutable built-in policy/configuration. Injected policy implementations are an explicit trust boundary and require their own sealed identity and validation; plugin behavior is not evidence for the built-in policy.

This map distinguishes implementation, deterministic proof, empirical support, exploratory evidence, and speculation. The machine-readable architecture graph is [`hive_reference/spec/architecture.json`](hive_reference/spec/architecture.json); scoped claims are in [`hive_reference/spec/claims.json`](hive_reference/spec/claims.json).

## Evidence sources

| Evidence ID | Validity | Result | What it bears on | What it does not bear on |
|---|---|---|---|---|
| EXP-DECOMP-CODEC-PREFLIGHT | Deterministic, frozen | Required codec replay/reference checks pass | Scoped structural information preservation and visible state reduction | Solver usability, generality, learning, transfer |
| EXP-DECOMP-QWEN-V2.1 | VALID | Raw 5/20, Retrieval 3/20, Compressed 4/20; Compressed authority-type errors 16; essential ablation 0/5 | Solver-capability gate failure; exact local costs; all conditions admitted | Representation ranking or compression loss |
| EXP-DECOMP-CODEX-EXPLORATORY | Exploratory, operator-reported, unsealed in this branch | Raw/Retrieval/Compressed 20/20; ablation 10/10; zero chronology/promotion errors; Compressed about 51% Raw prompt bytes and 20% Raw state bytes | Plausibility of engineered-packet usability for the reported solver stack | Sealed verification, superiority, generality, learned representation, formal replication |
| EXP-STORY-GUARD-TESTS | Deterministic tests | Evidence/source/dependency/status guards pass | Narrative-scoped nonpromotion and provenance discipline | Generic bitemporal truth or longitudinal Kingdom advantage |
| EXP-REF-MODEL-TESTS | Deterministic tests at this revision | Tracked authority, replay, contradiction, compression, ablation, versioning, rollback, and registry behaviors | Executable coherence for the tested cases | Exhaustive proof of every caller path or documented invariant; empirical learning or cognition |
| EXP-REF-WHOLE-SYSTEM-DEMO | Deterministic fixture | Typed experience through induced representation failure and gated repair | Pipeline integration and rollback-safe repair plumbing | Autonomous canonicalization, learned abstraction, fault diagnosis, recursive improvement |

## Architecture edge status

```text
Observation --PARTIAL--> Canonicalization
Canonicalization --IMPLEMENTED--> Event/Claim Ledger
Ledger --IMPLEMENTED--> Authority Policy
Authority --IMPLEMENTED--> Bitemporal State
State/Ledger --EXPERIMENTALLY SUPPORTED--> Handcrafted Compression
Representation + Task --IMPLEMENTED--> Selective Decompression
Decompression --PARTIAL/solver-relative--> Solver
Solver/Reconstruction --PARTIAL--> Evaluation
Evaluation --PARTIAL--> Evidence Registry
Evaluation --PARTIAL--> Failure Analysis
Failure --IMPLEMENTED mechanism--> Versioned Repair
Failure --PROPOSED--> Representation Profile
Profile --SPECULATIVE--> Candidate Proposer
Candidate Proposer --PROPOSED--> Learned Representation
Meta outcomes --SPECULATIVE--> Improved Proposal Policy
```

“Implemented” means an executable interface/path, not that its broad scientific claim is true.

The evidence-registry edge is `PARTIAL`: the current registry loads scoped claims and checks evidence record syntax, but it neither verifies referenced protocol/artifact bytes nor owns an authenticated append-only update path. Consequently, caller-supplied `VALID`, `PROVEN`, or `SUPPORTED` labels cannot authorize a high-confidence upgrade.

## Evidence by Hive rung

| Rung | Evidence level | Current evidence | Missing decisive evidence |
|---|---|---|---|
| Structured state | PROVEN within deterministic implementations | replay/authority tests in benchmark, StoryGuard, and reference core | real observation semantics and broader contradiction resolution |
| Reconstructable compression | PROVEN/SUPPORTED within frozen codec | deterministic round-trip and source references | independent codecs/domains and collision/property studies |
| Minimum sufficient representation | SUPPORTED only for frozen removal effects | frozen essential/control ablations plus a conservative contract-relative reference ablator | causal-semantic necessity, replacement certificates, grouped interactions, alternative minima, robustness/transfer |
| Abstraction formation | SPECULATIVE | free-text maps and human-engineered rules only | automatic, query-blind concept induction with counterexamples |
| Abstraction transfer | SPECULATIVE | no valid broad transfer artifact | locked generators, vocabularies, structures, domains |
| Learned compression | SPECULATIVE | none | automatically proposed Pareto candidate on heldout worlds |
| Self-evaluation | SPECULATIVE | failure records exist; no causal localization | controlled layer-specific fault intervention study |
| Representation repair | PLAUSIBLE mechanism | code-gate analogue and deterministic reference repair | autonomous diagnosis, heldout improvement, no regression |
| Representation-system improvement | SPECULATIVE | none | authentic-profile versus shuffled/no-meta future episodes |
| Recursive improvement | SPECULATIVE | none | replicated matched metaheldout gains under fixed protocol |

## Preserved negative evidence

The local Qwen result is not a compression failure. It is evidence that the solver/benchmark pairing was insufficient:

- all three main representations were near chance;
- condition differences were too small and wrongness too widespread to isolate compression;
- Compressed used much less input but did not maintain correctness;
- the run therefore remains `VALID / NOT_SUPPORTED` for its frozen hypothesis.

This negative must remain in the registry. It prevents future results from being interpreted without a Raw capability gate.

## Supporting evidence boundary

The exploratory Codex result makes the following scoped reading plausible, but does not establish it without a sealed replication:

> On the frozen synthetic worlds, the engineered compressed packet may have retained enough causal, temporal, and authority information for that capable solver stack to answer every case while receiving materially less state/context.

It does not support:

- that Compressed is better than Raw or Retrieval (all hit 20/20);
- that the result generalizes;
- that Hive discovered the representation;
- that the packet is effectively smaller after every static/training cost;
- that Hive learned a concept;
- that representation repair or recursive improvement works.

## Evidence propagation rules

1. Deterministic information preservation does not imply solver usability.
2. Solver usability does not imply superiority.
3. In-domain superiority does not imply transfer.
4. Transfer of a handcrafted representation does not imply learned abstraction.
5. Candidate generation does not imply useful learning.
6. One repair does not imply correct self-diagnosis.
7. Iteration does not imply recursive improvement.
8. Invalid or capability-gated runs do not upgrade downstream claims.
9. Negative and contradictory evidence is retained rather than overwritten.
10. Human semantic contribution is part of every learning claim's evidence scope.

## The weakest edge

The weakest edge is:

```text
human-defined canonical events and evaluation feedback
  -> automatically discovered, transferable representation
```

The current system starts with event keys, authority, preconditions, effects, query families, and oracles already supplied. No evidence yet shows Hive can discover that semantic structure without importing it through the grammar or evaluator.

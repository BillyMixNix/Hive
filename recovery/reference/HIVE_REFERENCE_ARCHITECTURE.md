# Hive Reference Architecture

Status: PARTIAL executable research specification, version 0.1
Scope: a falsifiable model of Hive's proposed mechanism; not a claim of AGI, understanding, or recursive self-improvement.

## What Hive is

Hive is a research program for testing whether explicit, versioned representations can make stored experience cheaper and more useful without destroying the distinctions future tasks require.

Its central experimental object is not a summary. It is a **representation version** with:

- immutable source lineage;
- an explicit preservation and discard contract;
- reconstruction dependencies and rules;
- measured direct and hidden cost;
- known failure modes;
- a human/automatic origin ledger;
- task-, solver-, and budget-conditional fitness;
- versioned replacement and rollback.

Hive's operational hypothesis is:

> For a preregistered task distribution, solver panel, and total resource budget, some query-blind representations of experience can reduce effective information or computation cost while preserving or improving task-relevant reconstruction, reasoning, robustness, and transfer relative to strong Raw and Retrieval baselines.

This is narrower and testable. It does not say that compression is intelligence. It does not promise sufficiency for arbitrary future queries. It does not imply that a system can discover the right representation.

## Formal core

Let:

- `O` be immutable observations;
- `E = Canonicalize(O)` be proposed events and claim revisions;
- `L = Admit(E, policy)` be the append-only admitted/rejected/disputed ledger;
- `S(t, k) = Replay(L, valid_time=t, known_at=k)` be a bitemporal state view;
- `R = Compress(L, S, scope)` be a versioned representation;
- `Z = Decompress(R, task, dependencies)` be a selective reconstruction;
- `a = Solver(task, Z)` be an answer;
- `y = Evaluate(a, Z, oracle, budget)` be a trial outcome.

A representation is **task-sufficient** only relative to a tuple:

`(task family, solver, evaluator, threshold, resource budget, world distribution)`.

A representation is **task-reversible** when the distinctions needed by that tuple can be reconstructed with source lineage. This is weaker than lossless recovery of the original observations.

A candidate is preferable only when it passes hard correctness and authority constraints and is non-dominated on a declared multiobjective fitness vector. Byte reduction alone cannot promote it.

## Non-negotiable invariants

1. Canonical records are immutable. Ledger, event, representation, migration, and activation content is hash-bound at its stated boundary. `Observation.source_sha256` addresses the source identity plus payload; the ledger digest, not that field alone, binds observation ID, record time, and provenance. External experiment/evidence records require protocol-sealed artifact hashes rather than being assumed individually authenticated.
2. Effective time and record time remain separate. Historical truth and what was known at the time are different queries.
3. Epistemic basis, truth status, and temporal status are separate dimensions. One overloaded `status` field is forbidden.
4. A plan, proposal, or prediction may establish that an intention exists; it may not materialize its proposed world effects. Only an admitted completion observation or licensed inference can do that.
5. Contradictions are explicit conflict objects. An active, authority-admissible `DISPUTED` or `UNKNOWN` claim creates explicit unknown state even when no accepted value competes with it; it is never collapsed into absence. Plans, proposals, failed conditional assertions, and untrusted claims do not gain that authority. Unresolved conflicts produce disputed or unknown state, never silent last-write truth.
6. State is a deterministic projection of the ledger and authority policy, not an independently mutable memory blob.

   Trust boundary: the built-in `AuthorityPolicy` freezes its inference-rule configuration and derives its identity from that frozen configuration. A caller-injected policy implementation remains trusted external code; results produced under such a policy do not prove the built-in authority invariants unless that implementation and configuration are independently sealed and identified.
7. Counterfactuals are ephemeral replay specifications. They never rewrite canonical history.
8. Every reconstructed atom identifies its representation components and ultimate evidence/event lineage.
9. A preservation or discard declaration is a hypothesis until verified against deterministic replay or frozen tasks.
10. Raw solver capability is gated before representation comparisons are interpreted.
11. Model outputs may propose events, claims, concepts, or representations. Deterministic validators retain canonical authority.
12. Candidate generation cannot modify its evaluator, protected tests, evidence registry, or success criteria.
13. Representation repair creates a new version. Promotion is explicit, old versions remain addressable, and rollback is tested.
14. Fitness includes schema, ontology, lookup, preprocessing, model, computation, and human-engineering costs, not just packet bytes.
15. Recursive-improvement claims require future, unseen representation-discovery episodes at matched total compute and human input.

## Core types

### Observation

`Observation` contains a content hash, source kind and locator, source actor/tool/model, record time, immutable payload, and parent observation IDs. It records what entered Hive, not whether it is true.

### Canonical event

`CanonicalEvent` contains effective time, record time, entities, relations/action, preconditions, state effects, causal/dependency IDs, claim revisions, observation/evidence IDs, and provenance. Canonicalization proposes structure; authority admission decides whether its world effects apply.

`hard_dependencies` and `causal_parents` are executable replay dependencies: a rejected or unapplied parent gates the child. Typed `edges` are informational graph links unless their target is also declared in one of those executable dependency fields.

### Claim revision

Each claim revision contains:

- `(subject, predicate, object)`;
- `Basis = OBSERVED | INFERRED | PROPOSED | PLANNED | PREDICTED | UNKNOWN`;
- `Truth = ACCEPTED | DISPUTED | FALSE | UNKNOWN`;
- validity interval and record time;
- evidence and dependency IDs;
- superseded revision IDs;
- confidence and authority source.

`CURRENT`, `HISTORICAL`, `SUPERSEDED`, and `FUTURE` are derived temporal views, not mutable truth labels.

### Promotion decision and contradiction

`PromotionDecision` records `ADMIT`, `REJECT`, or `DISPUTE`, the exact policy rule, evidence, and reason. `Contradiction` records incompatible claims, its resolution status, and any explicit resolution decision. Incompatible values are never silently overwritten.

### State view

`StateView(valid_time, known_at)` contains accepted facts, disputed facts, unknowns, conflicts, transitions, and source references. It is reproducible from the ledger. Historical state, rollback views, and counterfactual views use the same projector. The current scalar `StateCell` projects one source for compatible simultaneous claims with the same value and validity; all claims remain in the ledger, but multi-source co-provenance in the projected cell is a known missing feature.

### Representation version

A `RepresentationVersion` contains immutable `RepresentationComponent` objects. Each component has a kind:

- `ATOM`: compact state or relation;
- `TRANSITION`: validity-changing event;
- `CAUSAL_RULE`: reusable mechanism/dependency;
- `CONCEPT`: invariant with scope and exceptions;
- `PROCEDURE`: reusable action sequence;
- `CONSTRAINT`: compressed failure, prohibition, or boundary.

The representation declares its compression mechanisms:

- structural;
- causal;
- conceptual;
- temporal;
- procedural;
- failure.

Every component records what it replaces, preserves, discards, depends on, cites, and cannot safely answer.

### Task, selection, and reconstruction

`TaskSpec` declares query family, valid time, known-at time, answer schema, and budget. A condition-blind selector chooses components. The decompressor follows dependencies and emits a `Reconstruction` containing lineage-bearing atoms, omitted components, costs, and any unsupported reconstruction attempt. Before selection, the executable decompressor requires an independently configured immutable `RepresentationRootCommitment` binding the source ledger, full-source manifest, family, codec, and schema. A self-consistent hash carried only inside a candidate packet is not a trust anchor: the experiment/bootstrap protocol must authenticate and seal the original root, and packets outside that root fail closed.

The reference implementation reconstructs only task-relevant components. It does not regenerate the full source history unless the task requires it.

### Concept

A concept is a representation component with:

- a compressed invariant;
- scope;
- known instances;
- counterexamples and exception boundaries;
- prerequisites;
- causal implications;
- reconstruction rules;
- uncertainty;
- provenance.

Observation-to-concept is only half of the test. `concept + task -> relevant distinctions` must also work. Failure to reproduce a required distinction is harmful compression.

### Outcome and fitness

`TrialOutcome` separates:

- answer correctness;
- reconstruction precision and recall;
- causal, temporal, and authority correctness;
- illegal promotions and hallucinations;
- unnecessary reconstruction;
- input/output tokens, calls, latency, state bytes, and effective bytes;
- solver capability-gate status;
- compression-loss attribution.

This is the reference outcome contract, not a claim that one general evaluator
already enforces every field.  The executable core currently checks exact
deterministic answers and records lineage and supplied bytes; benchmark-specific
adapters provide some capability and provenance checks.  A domain-neutral,
independent reconstruction/provenance grader remains partial.

`FitnessVector` does not default to one score. Quality, transfer, robustness, provenance, cost, and human contribution remain visible and are compared by hard constraints plus Pareto dominance.

### Profile, repair, and version registry

`RepresentationProfile` summarizes failure distributions conditional on representation family, solver, task family, and load. A `RepairProposal` cites a failure cluster and original evidence. At construction, the registry freezes one exact repair gate/evaluator, protected and new task manifests, a normalized protocol hash, and the preregistered candidate cost ceiling. Each replaceable solver and decompressor must expose a normalized configuration digest covering every behavior-relevant setting; the evaluator derives its digest from those collaborator digests, and the registry revalidates it before activation. Collaborators without this contract fail closed. The built-in deterministic solver is stateless and frozen; the frozen decompressor's only state is its sorted immutable set of externally sealed representation-root commitments, which is included in its configuration digest. Its activation operation accepts only a registered candidate ID, evaluates the exact active parent and candidate, validates every returned summary against the task count and outcomes, and mutates the active pointer inline only for that synchronous result. Caller-supplied `MigrationDecision` records never authorize activation. Parent/child version, family, schema, codec, source ledger, full-source component manifest, promotable validation status, and content hashes must match. Migration IDs bind the complete decision content; activation IDs also bind the append-only activation sequence, so rollback and reevaluation remain distinct events.

Cost and validation trust is deliberately split. `packet_bytes` is recomputed from the canonical components plus full-source-manifest envelope, and every `CostBreakdown` field must be an exact nonnegative integer at construction and at registry/gate use. Schema, ontology, lookup, preprocessing, human-contribution, and validation-status attestations are not independently measured by this reference gate; they remain trusted external inputs whose provenance must be sealed by a real experiment protocol.

Registration captures each representation's complete content hash and revalidates it before bootstrap, lookup, active access, evaluation, or rollback. This detects mutation through a retained Python object alias and prevents an old ID from restoring changed content. A hash commitment is not source authentication: the initial/bootstrap representation, its full-source manifest, externally supplied validation and cost attestations, evaluator task/protocol manifests, solver/decompressor configuration digests, and any injected authority policy are trusted sealed roots. The reference code detects later drift from those commitments; an experiment must authenticate the roots before constructing the registry.

### Meta-representation and recursive cycle

A meta-representation describes observed behavior of representations, such as:

- expensive but reliable;
- weak on bitemporal questions;
- lossy for nested ownership;
- difficult for a particular solver;
- poorly evidenced in one domain.

Using that profile to choose or propose future representations is a testable mechanism. It is not recursive improvement until a distinct modified proposal policy outperforms a frozen policy on replicated future unseen representation-discovery episodes, fails a shuffled/no-meta ablation, and has exact equality on every declared `CostBreakdown` resource field. Self-reported resource-match booleans are not evidence of matching.

## End-to-end dataflow

```text
Observation
  -> Canonicalization proposal
  -> Authority decision + explicit conflicts
  -> Append-only event/claim ledger
  -> Bitemporal state projection
  -> Versioned compression candidate
  -> Task-conditioned component selection
  -> Selective reconstruction with lineage
  -> Replaceable solver
  -> Frozen evaluation
  -> Failure attribution
  -> Representation profile
  -> Repair/candidate proposal
  -> Locked old+new evaluation
  -> Explicit promotion or rejection
  -> Rollback-capable version registry
```

Feedback loops:

```text
Evaluation -> Failure cluster -> Repair proposal -> Candidate evaluation
Evaluation -> Representation profile -> Selector policy
Training outcomes -> Candidate proposer -> Representation candidates
Meta-heldout outcomes -> Proposal-policy version -> Future candidate search
```

Original evidence remains reachable through every loop.

## The ten-rung research DAG

The proposed ladder is not a monotonic staircase. Minimum size can conflict with robustness and transfer, and meta-learning is a distinct hypothesis. The rungs are represented as dependency-gated research nodes:

| Rung | Executable object | Current status |
|---|---|---|
| 1. Structured state | event ledger and state projector | Implemented in domain fragments; generic reference implemented here |
| 2. Reconstructable compression | representation and deterministic decoder | Supported for the frozen engineered codec |
| 3. Minimum sufficient representation | sufficiency/ablation report | Partial; exact/approximate minima are relative to the conservative fail-closed representation contract, not yet causal-semantic minima |
| 4. Abstraction formation | concept proposal and bidirectional test | Proposed |
| 5. Abstraction transfer | locked unseen transfer harness | Proposed/partial scaffolding |
| 6. Learned compression | query-blind candidate proposer | Proposed; deterministic heuristic demo is not learning evidence |
| 7. Self-evaluation | representation profiles and fault interventions | Proposed |
| 8. Representation repair | immutable candidate, gate, migration, rollback | Generic reference mechanism implemented; empirical capability unproven |
| 9. Representation-system improvement | proposal-policy comparison | Speculative |
| 10. Recursive improvement | matched meta-heldout slope experiment | Speculative |

## Solver boundary

Solvers are replaceable and separately described by model, digest/version, prompt/interface, tools, context, sampling, calls, and compute budget. Every representation experiment begins with a Raw capability gate. If Raw is below the preregistered threshold, the run may validate plumbing but cannot adjudicate representation quality.

The local Qwen result and exploratory Codex result are therefore complementary:

- Qwen shows that a weak solver/benchmark pairing can make all representations uninterpretable;
- the unsealed, operator-reported Codex result makes it plausible that the engineered compressed packet retained usable distinctions for that solver stack;
- neither shows Compressed superiority or learned representation discovery.

## Learning loop

The research interface for representation learning is:

1. observe training histories;
2. propose candidates without held-out query/answer access;
3. validate schema, lineage, and authority invariants;
4. evaluate reconstruction and downstream tasks;
5. measure direct and effective cost;
6. run bounded ablations and counterfactual distinction tests;
7. compare candidates and baselines on a Pareto frontier;
8. freeze the selected candidate;
9. evaluate once on locked unseen worlds/tasks;
10. retain or reject without moving criteria.

An LLM summary or schema proposal is merely `MODEL_PROPOSED`. It becomes `AUTOMATICALLY_VALIDATED` only after deterministic and empirical gates. It becomes evidence of learned abstraction only after held-out transfer, bidirectionality, counterexample retention, and reduced domain-specific human contribution.

## Resource policy

- Deterministic replay, codec checks, ablations, registry validation, and synthetic worlds run locally without inference.
- The local Qwen-class model is suitable for plumbing and capability-gate experiments, not assumed capable of adjudicating a benchmark.
- Expensive solvers run only after deterministic validity and Raw capability checks.
- Calls, context, output, latency, preprocessing, schema, ontology, and human-engineering budgets are declared before inference.
- A failed apparatus run stops; it is not repaired inside the same experimental identity.

## Hive and Kingdom

Hive is the domain-neutral representation research program described here. Kingdom is an application and proving ground for long-form continuity, original intent, authority, and state promotion. Kingdom may implement or test Hive interfaces, but narrative-specific categories never define the generic Hive ontology.

## What survives formalization

### Survives

- event-sourced, provenance-preserving state as a reliable substrate;
- authority-safe separation of plans, claims, and current state;
- representations as explicit, fallible, versioned experimental objects;
- task-conditioned reconstruction as a better criterion than byte reduction;
- solver capability gates and solver/representation interaction analysis;
- full-cost Pareto comparison;
- ablation, failure clustering, versioned repair, and rollback as coherent mechanisms;
- an experiment DAG from engineered state through learned and recursive hypotheses.

### Does not yet survive as an empirical claim

- autonomous observation-to-event semantics;
- genuine causal-mechanism discovery rather than guarded transition replay;
- automatically learned concepts;
- broad transfer;
- correct representation-fault localization;
- representation repair that reliably improves held-out tasks;
- recursive improvement of representation discovery.

## Answers to the ten architecture questions

1. **Is reconstructable compression sufficient?** No. It is a useful memory objective that requires authority, task scope, capable solvers, evaluation, provenance, grounding, and governance.
2. **What is known computer science?** Event sourcing, bitemporal databases, truth maintenance, provenance graphs, state/causal graphs, MDL and rate-distortion, retrieval/query planning, feature ablation and delta debugging, program/concept induction, transfer learning, Pareto optimization, AutoML, versioning, and rollback.
3. **What may be a distinctive combination?** Explicit preserve/discard contracts plus task-conditioned inverse reconstruction, authority safety, solver gates, effective-cost accounting, human-contribution tracking, and empirically gated versioned repair. No algorithmic novelty is claimed.
4. **Where are human semantics hidden?** Event fields, entity/state keys, authority rules, codec columns, causal prerequisites, world generators, query families, oracles, relevant references, ablation targets, and evaluator definitions.
5. **What proves learned abstraction rather than summarization?** Query-blind automatic discovery that improves a locked size/correctness/transfer frontier on unseen generators and vocabularies, preserves counterexamples and reconstructability, beats strong summary/retrieval baselines, and reduces domain-specific human structure.
6. **What proves representation-assisted cognition?** With the same capable solver and matched resources, a representation improves held-out correctness, robustness, reasoning distance, or cost at matched correctness after all hidden costs are counted.
7. **What proves recursive representation improvement?** A policy changed by prior representation experience improves future unseen representation-search quality or efficiency against a frozen/shuffled/no-meta policy at matched compute; ablating the learned meta-state removes the gain.
8. **What falsifies the strongest thesis?** Repeated preregistered meta-heldout studies in diverse domains where the improved proposal policy does not beat fixed nonrecursive search, or every apparent gain disappears after accounting for overfitting, hidden compute, human ontology growth, or shifted criteria.
9. **What is the smallest path to Hive-3?** Unified deterministic event/authority core; capable-solver frontier benchmark; restricted query-blind representation language; automatic candidate proposal; train/dev Pareto selection; one locked transfer test; then one immutable repair cycle.
10. **What is weakest?** Automatically discovering useful, transferable representations from downstream feedback without importing human semantics or oracle leakage. Recursive improvement is even more speculative.

## Current definition

Hive is an event-sourced, authority-aware research architecture in which representations are explicit, versioned, provenance-bearing hypotheses about how experience can be compressed and selectively reconstructed. Those hypotheses are judged by downstream behavior, transfer, robustness, total cost, and human contribution, then repaired only through frozen evidence and rollback-safe evaluation.

That is a coherent machine to test. It is not yet a machine that has learned its own abstractions.

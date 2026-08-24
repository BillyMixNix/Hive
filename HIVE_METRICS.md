# Hive Metrics

Hive does not have one “intelligence score.” Representation quality is conditional and multiobjective. A result is meaningful only when its task set, solver, evaluator, resources, representation origin, and validity gates are frozen.

## Measurement tuple

Every result is indexed by:

```text
(protocol, world distribution, task family, representation version,
 solver version, evaluator version, resource budget, split, run ID)
```

Vectors with different protocols, solvers, task sets, or hard constraints are not directly rankable unless the comparison protocol explicitly permits it.

## Hard validity gates

Before any performance interpretation:

- artifacts, hashes, schemas, and source revisions verify;
- worlds/tasks/answers were frozen before candidate evaluation;
- every physical model attempt is recorded and matched as specified;
- no timeout, truncation, retry, clipping, or hidden evidence access occurred;
- deterministic oracle implementations agree or the case is invalid;
- representation provenance and dependencies resolve;
- Raw passes the preregistered solver capability threshold;
- candidate did not modify evaluators, tests, registry, or criteria;
- full representation origin and cost ledgers are present.

An invalid run may diagnose apparatus behavior. It cannot support or falsify the representation hypothesis.

## Reconstruction metrics

Let `G` be the gold task-relevant semantic projection and `R` the reconstructed projection.

- **Atom recall**: `|G ∩ R| / |G|`.
- **Atom precision**: `|G ∩ R| / |R|`.
- **Required-edge recall**: fraction of required temporal, causal, authority, supersession, containment, and dependency edges reconstructed.
- **Proof closure**: whether reconstructed premises and rules entail the answer under the frozen rule engine.
- **Provenance retention**: fraction of required atoms/edges with valid ultimate source lineage.
- **Hallucinated reconstruction**: count/rate of reconstructed atoms not entailed by representation components and dependencies.
- **Unnecessary reconstruction**: correct but task-irrelevant atoms supplied to the solver, reported as count and bytes/tokens.
- **Explicit unknown accuracy**: missing or discarded necessary structure is labeled unknown/incomplete rather than guessed.
- **Compression-loss failures**: task failures deterministically attributable to a distinction absent from the representation but present in Raw canonical history.

Exact deterministic reconstruction is distinct from solver usability. A codec can reconstruct perfectly while a solver answers incorrectly.

## Task and reasoning metrics

- exact answer correctness;
- causal proof correctness and prerequisite closure;
- temporal ordering and validity-window correctness;
- authority/epistemic correctness;
- contradiction and supersession correctness;
- illegal current-state promotions;
- false resolutions of open obligations;
- counterfactual correctness where a structural causal oracle exists;
- abstention correctness for genuinely insufficient state;
- chapter/case-by-case degradation and load-conditioned slopes.

Outcome-derived error classes must be labeled as such. Selecting a planned option can diagnose an authority-type error, but it is not an independent trace of the model's internal reasoning.

## Solver metrics and capability gates

- Raw accuracy and hard-constraint pass rate;
- representation-condition accuracy;
- solver x representation interaction;
- JSON/interface admissibility, separate from semantic correctness;
- input/output tokens, calls, latency, and completion reasons;
- capability-gate status.

If Raw is below the frozen gate, report the run as solver-incapable for representation inference. Do not choose a new solver after seeing condition results inside the same protocol.

## Direct representation cost

- packet bytes;
- supplied state bytes;
- full solver-context bytes and tokens;
- dynamic lookup bytes/tokens;
- output tokens;
- solver model calls;
- latency and compute where available.

These answer: “How much did this trial show the solver?” They do not answer: “How much machinery did the representation require?”

## Effective compression cost

Record unique representation-specific dependencies:

- schema and legend bytes;
- ontology and concept-library bytes;
- codec/decoder and configuration bytes;
- lookup-table/index bytes;
- preprocessing calls, tokens, latency, and compute;
- learned-representation training and selection cost;
- domain-specific human-authored bytes/components;
- common byte-identical harness machinery, identified and excluded consistently.

For a frozen workload of `N` uses:

```text
ECR_N =
  (schema + ontology + codec/config + lookup
   + sum(packet_i + dynamic_aux_i))
  /
  (raw_specific_static + sum(raw_i))
```

Report both:

- `ECR_1` cold start;
- `ECR_N` at the preregistered amortization horizon.

Training/preprocessing compute and model calls remain separate dimensions even when byte-amortized. A one-byte code plus a megabyte dictionary is not one-byte effective compression.

## Human-engineering contribution

Origin and validation are separate axes.

Origin values:

- handcrafted;
- model-proposed;
- learned from declared training data;
- automatically discovered by a non-model algorithm.

Validation values:

- unvalidated;
- schema-validated;
- deterministically validated;
- empirically validated in-domain;
- transfer-validated.

Report:

- fraction of components by origin;
- domain-specific human-authored bytes;
- human-authored predicates, authority rules, causal rules, task labels, and ablation targets;
- human interventions per candidate and per accepted version.

Hive-3 requires the domain-specific human-authored fraction to decline without hidden oracle leakage.

## Minimum sufficient state

Sufficiency is conditional on the measurement tuple. Report algorithm and guarantees:

- `EXACT_SUBSET_MINIMUM`: exhaustive subsets within a small component limit;
- `ONE_MINIMAL_APPROXIMATION`: greedy/ddmin result where no tested single removal preserves the pass predicate;
- `SINGLETON_ESSENTIALITY`: leave-one-out diagnostic only;
- `CONDITIONAL_REDUNDANCY`: component removable only in the presence of named substitutes.

The pass predicate includes answer, reconstruction, causal, temporal, authority, provenance, and illegal-promotion constraints. A baseline representation that already fails cannot yield a valid minimum.

Track:

- evaluated subsets;
- all discovered minimal sufficient sets;
- essential and redundant components;
- interactions and substitutes;
- explicit UNKNOWN tombstones;
- matched irrelevant-removal controls;
- retained robustness/transfer after minimization.

## Compression frontier

Frontier points remove semantic structures, never random byte percentages. Removal units include:

- effects and state atoms;
- preconditions and causal edges;
- authority/status markers;
- effective or record time;
- supersession/contradiction edges;
- provenance anchors;
- concept instances/counterexamples;
- procedures or failure constraints.

Every point stores an exact removal manifest and preserved/discarded declarations. Plot all hard correctness dimensions and costs, not one accuracy-per-byte score.

## Transfer metrics

Report separately:

- memorized/training performance;
- same-generator interpolation;
- structural transfer to unseen compositions;
- causal-mechanism transfer;
- vocabulary/surface transfer;
- unseen query-family transfer;
- cross-domain transfer.

Template siblings are not independent domains. Include generator family, seed hierarchy, and effective replication unit.

## Representation repair metrics

- failure-localization accuracy under controlled observation/representation/decompressor/solver/evaluator faults;
- implicated-component precision and recall;
- repaired-case delta;
- locked prior-task regressions;
- new-task transfer;
- added effective cost;
- candidate count and evaluation compute;
- promotion/rejection reason;
- rollback fidelity and time.

A repair that retrieves an oracle-identified missing atom proves versioning and regression-gate plumbing, not self-diagnosis or learning.

## Meta-representation and recursive metrics

For representation profiles:

- calibration of predicted failure risk by solver/task/load;
- representation-selection regret against an oracle selector;
- profile ablation and shuffled-profile controls;
- cost of maintaining and consulting the profile.

For recursive representation improvement:

- held-out frontier hypervolume or Pareto-set quality;
- candidates evaluated to reach a target frontier;
- wall-clock, model calls, tokens, and total compute;
- domain-specific human interventions;
- generation-by-generation performance on new meta-heldout episodes;
- treatment minus frozen/shuffled/no-meta slope;
- profile/proposal-policy ablation effect.

No recursive claim is admissible if benchmarks, evaluator, candidate language, compute budget, or success criteria changed between arms.

## Pareto comparison

Quality dimensions maximize:

- reconstruction, task, causal, temporal, authority, transfer, robustness, and provenance scores.

Cost/error dimensions minimize:

- hallucinations, illegal promotions, effective bytes, tokens, calls, latency, compute, and human-domain contribution.

Candidate `A` dominates `B` only when:

1. their measurement tuples are comparable;
2. `A` passes every hard constraint;
3. `A` is no worse in every reported dimension;
4. `A` is strictly better in at least one dimension.

Missing required dimensions make candidates incomparable. Arbitrary scalar weighting is not the default.

## Evidence interpretation

- A deterministic replay/hash property may be **PROVEN** at a fixed revision.
- A valid empirical benchmark may be **SUPPORTED** within its scope.
- One exploratory ceiling result is supporting evidence, not general proof.
- A capability-gated run does not compare representations.
- A smaller packet without hidden-cost accounting supports visible size reduction only.
- A deterministic whole-system demo proves executable plumbing and invariants only.

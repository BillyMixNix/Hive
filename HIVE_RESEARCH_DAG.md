# Hive Research DAG

The authoritative machine-readable DAG is [`hive_reference/spec/research_dag.json`](hive_reference/spec/research_dag.json).

Hive's ten rungs are not a guaranteed staircase. Minimum size can hurt transfer; self-evaluation can be studied before learned abstraction; meta-learning is not a natural consequence of a repair loop. The program is a dependency-gated DAG:

```text
R0 deterministic event / authority / bitemporal state
  |
  v
R1 scoped reconstructable compression
  |
  +-------------> R3 compression frontier / sufficient state
  |                    |                     |
  v                    v                     v
R2 usable          R5 learned           R7 fault
decompression      representation       localization
  |                    |                     |
  v                    v                     |
R4 load/depth/      R6 abstraction / <-------+
authority stress      transfer               |
                         |                    v
                         +---------------> R8 repair
                                              |
                                              v
                                      R9 meta-representation
                                              |
                                              v
                                      R10 recursive improvement
```

## Node summary

| Node | Question | Cheapest decisive test | Current status |
|---|---|---|---|
| R0 | Is canonical truth/state coherent? | Plan, conflict, late-evidence, rollback tests | Implemented in reference core |
| R1 | Does a representation preserve scoped distinctions? | Round-trip/collision properties | Engineered codec supported |
| R2 | Can a capable solver use it? | Raw gate then small matched comparison | Partial; Qwen gated, Codex exploratory |
| R3 | Where is the compression frontier? | Semantic removal + exact small-set ablation | Partial |
| R4 | Does compression alter degradation under load/depth/authority stress? | 2x2 support/distractor and authority suite | Proposed |
| R5 | Can Hive discover a representation? | Frozen rule-grammar learner on locked worlds | Proposed; critical transition |
| R6 | Is the learned object an abstraction that transfers? | Hidden generators, compositions, symbols, counterexamples | Proposed |
| R7 | Can Hive identify representation-caused failures? | Layer-specific fault interventions | Proposed |
| R8 | Can it repair without regression? | Immutable repair + protected old/new tests + rollback | Mechanism modeled; capability proposed |
| R9 | Does knowledge about representations improve future search/selection? | Real profile vs shuffled/no-profile | Speculative |
| R10 | Does improved representation machinery improve itself? | Nested future metaheldout episodes at matched cost | Speculative |

## Experiments A–J

### Experiment A — Information Preservation

**Claim:** compressed state deterministically reproduces required canonical information.

**Gate:** exact replay/state/reference/authority equivalence and provenance resolution.

**Failure:** any in-scope representation collision joins histories with different oracle projections.

**Cost:** deterministic local.
**Current evidence:** established narrowly for the frozen engineered codec.

### Experiment B — Usable Decompression

**Claim:** a capable solver reasons correctly from compressed state.

**Gate:** Raw capability, matched solver/settings/calls, zero illegal promotions.

**Failure:** Compressed loses required correctness due to absent/unusable structure.

**Cost:** small model panel after deterministic preflight.
**Current evidence:** Qwen run cannot adjudicate; exploratory Codex run supports scoped usability but hit a ceiling.

### Experiment C — Compression Frontier

**Claim:** there is a useful rate-distortion frontier.

**Design:** nested candidates remove named effects, rules, authority markers, times, conflict edges, provenance, or concepts—not random bytes.
**Failure:** gains disappear against minified/lossless controls or full effective cost.

### Experiment D — Distractor Resistance

Hold required support/dependency structure fixed while increasing plausible distractors. Rotate evidence position. Compare degradation slopes and full context fit. Compression helps only if a capable solver degrades more slowly at matched correctness/cost.

### Experiment E — Reasoning Distance

Hold total history approximately fixed while increasing temporal/causal/dependency depth. Separate temporal dependencies from genuine causal interventions. Measure reconstruction/proof and answer slopes.

### Experiment F — Authority Stress

Test plans, predictions, late evidence, retractions, supersession, equal-authority conflicts, false claims, scoped authority, and validity windows. Any silent promotion is a hard failure.

### Experiment G — Learned Compression

Provide training histories only to a bounded proposer over a frozen representation grammar. Select on development, freeze once, evaluate on locked worlds. Compare Raw, Retrieval, minified canonical state, engineered codec, learned summary, and equal-size controls with full costs.

The first useful result is not “an LLM wrote a schema.” It is an automatically selected representation that improves the heldout Pareto frontier without test-query access.

### Experiment H — Transfer

Separate memorization, same-generator interpolation, structural transfer, causal transfer, vocabulary transfer, unseen query-family transfer, and cross-domain transfer. New names alone are not transfer.

### Experiment I — Representation Repair

Inject independently controlled observation, representation, decoder, and solver faults. Require correct layer/component localization, immutable candidate, protected regression/transfer suite, explicit promotion, and exact rollback.

### Experiment J — Meta-Learning

Across new representation-discovery episodes compare:

- frozen proposer;
- proposer with authentic prior profiles;
- shuffled-profile control;
- no-meta control.

Match candidate count, compute, calls, human input, and evaluator access. Measure heldout frontier quality and resources to first admissible candidate. This is the first experiment that can support recursive representation improvement.

## World-complexity curriculum

Difficulty is assigned before representation condition and separated from history length.

| Level | World property | New failure pressure |
|---:|---|---|
| 1 | simple ownership/state changes | current value |
| 2 | nested containment and transitions | derived location/ownership |
| 3 | plans versus outcomes | authority/status |
| 4 | contradictory claims and source authority | dispute/supersession |
| 5 | long dependency chains | support depth |
| 6 | interacting agents and scoped knowledge | truth vs belief |
| 7 | known latent rules | mechanism application |
| 8 | rules inferred from traces | representation discovery |
| 9 | unseen compositions/generators | structural transfer |
| 10 | learner proposes abstractions | learned representation and meta-evaluation |

Every level must support Raw/Retrieval/Compressed equivalence, solver capability gates, and deterministic or independently validated oracles.

## Resource staging

1. Run schema, replay, lineage, collision, and ablation checks locally.
2. Run the Raw capability probe before any multi-condition inference.
3. Use the local Qwen-class model for plumbing only unless it passes the frozen gate.
4. Use capable expensive solvers only on prevalidated, frontier-informative cases.
5. Freeze expected physical calls and worst-case tokens before launch.
6. Stop on apparatus failure; do not repair a live protocol.

## Strongest falsifier

The strongest scoped Hive thesis is falsified when diverse preregistered metaheldout studies show that a representation-informed proposer does not improve future representation-search quality or efficiency over fixed nonrecursive search at matched compute and human input—or when every gain disappears after hidden complexity, task leakage, ontology growth, evaluator gaming, or forgotten hard cases are counted.

Negative results at lower nodes block evidence propagation upward. They do not justify redefining the node.

# Hive Claim Registry

The authoritative machine-readable registry is [`hive_reference/spec/claims.json`](hive_reference/spec/claims.json). Claims are deliberately scoped. Evidence levels apply to the exact statement and scope, not to Hive as a whole.

## Evidence-level policy

- **PROVEN**: a formal property or deterministic invariant at a fixed revision under explicit assumptions. Never a broad empirical generalization.
- **SUPPORTED**: direct empirical or replicated evidence that addresses major confounders within the stated scope.
- **PLAUSIBLE**: coherent mechanism with limited, indirect, or exploratory evidence.
- **SPECULATIVE**: coherent but not meaningfully established.
- **FALSIFIED**: the scoped claim crosses an explicit failure condition or is false of the current implementation.

Invalid experiments cannot upgrade a claim. Supporting and contradicting evidence coexist. A claim cannot inherit a dependency's evidence level automatically.

The executable `EvidenceRegistry` is presently a read-only, syntactic view of this file. It has no trusted artifact verifier or authenticated update authority and therefore fails closed rather than authorizing `PROVEN` or `SUPPORTED` upgrades from caller-constructed evidence records.

## Current registry

| ID | Level | Scoped claim | Current reading |
|---|---|---|---|
| HIVE-C001 | PROVEN | Frozen codec preserves designated state/reference distinctions on the frozen pack | Deterministic artifact property |
| HIVE-C002 | PROVEN | Frozen codec reduces visible supplied-state bytes | Packet-size property, not full lifecycle compression |
| HIVE-C003 | SUPPORTED | Local Qwen pairing lacked solver capability to isolate a representation advantage | Valid negative capability result |
| HIVE-C004 | PLAUSIBLE | Exploratory Codex stack reportedly used the compressed packet on all frozen cases | Operator-reported and unsealed here; ceiling, no superiority, no replication |
| HIVE-C005 | SPECULATIVE | Compressed reasoning is superior to Raw/Retrieval | Not demonstrated |
| HIVE-C006 | PROVEN | Deterministic authority guards can block plan-to-current promotion | Scoped implementation invariant |
| HIVE-C007 | PLAUSIBLE | Task-reconstructable compression is a useful research objective | Coherent, not a theory of intelligence |
| HIVE-C008 | SUPPORTED | Frozen ablation identifies components whose removal breaks a declared task/solver/contract predicate | Contract-relative removal effect; causal necessity remains unproven |
| HIVE-C009 | SPECULATIVE | Hive forms bidirectional abstractions | Not implemented |
| HIVE-C010 | SPECULATIVE | Hive representations transfer beyond generators/domains | Not tested |
| HIVE-C011 | SPECULATIVE | Hive discovers useful representations | Critical missing transition |
| HIVE-C012 | SPECULATIVE | Hive localizes representation-caused failures | Not tested |
| HIVE-C013 | PLAUSIBLE | Versioned repair can improve without regression | Mechanism modeled; capability unproven |
| HIVE-C014 | SPECULATIVE | Meta-representations improve future selection/proposal | Not tested |
| HIVE-C015 | SPECULATIVE | Better representations improve future representation discovery | Strongest unestablished claim |
| HIVE-C016 | PLAUSIBLE | Kingdom is a useful domain proving ground | Domain adapter, not Hive's definition |
| HIVE-C017 | SPECULATIVE | Hive achieves effective compression after hidden costs | Not measured |
| HIVE-C018 | PLAUSIBLE | Solver capability materially interacts with representation | Cross-solver contrast relies on the unsealed exploratory run; preregistered replication is required |
| HIVE-C019 | SUPPORTED | The reference model passes its tracked deterministic invariant tests | Fixed tracked tests only; not an exhaustive proof of every documented invariant |
| HIVE-C020 | PROVEN | One deterministic whole-system pipeline executes end to end | One synthetic fixture; proves plumbing only |
| HIVE-C021 | FALSIFIED | Current Hive automatically discovers domain semantics from raw observations | False of the current implementation |

## Evidence-update rule

Every future update must identify:

1. the exact claim and scope;
2. frozen protocol and artifact hashes;
3. validity and capability-gate status;
4. supporting and contradicting result;
5. unchanged falsification criterion;
6. dependency changes;
7. who or what supplied the representation semantics.

The registry is not writable by the candidate representation, proposer, solver, or evaluator being tested.

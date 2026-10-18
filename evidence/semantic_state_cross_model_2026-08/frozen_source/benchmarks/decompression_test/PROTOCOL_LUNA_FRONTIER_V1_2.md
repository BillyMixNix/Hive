# Hive Luna Compression Frontier v1.2 — Matched Raw Baseline

Protocols v1 and v1.1 and every prior execution remain sealed permanent
evidence. Protocol v1.2 answers the representation question directly: Raw is
the contemporaneous comparison baseline, not a requirement that the solver be
perfect before compressed representations are allowed to run.

The sole material experimental change from v1.1 is orchestration:

- all six Raw and all eighteen C0/C1/C2 calls run unless the apparatus fails;
- Raw errors remain baseline observations rather than stopping the run;
- every compressed result is paired with the same case under Raw;
- C0 versus Raw is the primary decompression comparison;
- C1 and C2 locate the relative information-removal frontier.

Everything else is frozen from v1.1: the 20-case pack and hashes, expanded
worlds, questions, options, representations, condition order, batch membership,
prompts, strict batch-cardinality schemas, model (`gpt-5.6-luna`), medium
reasoning effort, 4,096 output-token allowance, current-turn isolation, default
service tier, SDK `openai==3.3.1`, no tools, no cache, no storage, no retry, one
physical attempt per call, deterministic graders, budget-exhaustion scoring,
fail-closed apparatus behavior, and immutable artifacts.

## Primary interpretation

C0 supports the scoped hypothesis on this frozen smoke only if:

1. C0 uses fewer representation bytes than Raw;
2. C0 exact correctness is at least Raw correctness;
3. C0 admissibility is at least Raw admissibility;
4. C0 chronology/authority errors do not exceed Raw;
5. C0 illegal state promotions do not exceed Raw.

Aggregate support and per-case zero-distortion are reported separately. The
latter additionally requires that C0 lose none of the cases Raw answered
correctly; corrected Raw errors cannot conceal different compression-induced
errors.

If none of Raw, C0, C1, or C2 scores above 10/20, the result is
`INCONCLUSIVE_LOW_SOLVER_CAPABILITY` rather than evidence about representation
quality. Otherwise failure of any primary criterion is `NOT_SUPPORTED`.

C1 and C2 use the same no-regression rule against their immediate predecessor
in hierarchical order (C0→C1→C2). A later level cannot repair an earlier
confirmatory failure; later recovery is descriptive.

No finite outcome proves Hive generally. Any supported result is scoped to this
case pack, solver, configuration, and single execution and requires replication.

Frozen limitations are reported, not repaired mid-run: Raw is always first
while C0/C1/C2 positions are counterbalanced; each batch is one stochastic
physical attempt; errors within a batch may be correlated; twenty designed
cases do not establish population generality; and visible representation bytes
exclude the shared codec, schema, and human engineering behind the packet.

Fresh artifact directory:

`.hive/benchmarks/decompression_test/luna-frontier-v1-2-001`

Maximum physical calls: 24. Conservative cost ceiling: $0.30. No prior artifact
may be modified, resumed, overwritten, or reinterpreted.

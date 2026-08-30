# Hive Luna Compression Frontier v1.3 — Exact Stability Replication

Protocols v1, v1.1, v1.2, and all of their artifacts remain sealed. Protocol
v1.3 does not tune the solver or the representation against those results.

The sole material change from v1.2 is repetition: v1.3 executes six fresh,
independent copies of the complete frozen v1.2 24-call schedule. Six was fixed
before inference because six concordant nonzero run-level differences are the
smallest sample that can reach `p < .05` under a two-sided exact sign test
(`p = .03125`). The prior v1.2 run is descriptive context and is excluded from
the new confirmatory sample.

Every replication preserves:

- the same frozen 20 cases, expanded worlds, questions, and answer options;
- Raw, C0, C1, and C2 representations byte-for-byte;
- the same six batches, case membership, and condition ordering;
- identical prompts and strict structured-output schemas;
- `gpt-5.6-luna`, medium reasoning, and 4,096 maximum output tokens;
- current-turn isolation, `store=false`, no tools, default service tier, and
  explicit no-breakpoint caching;
- one physical attempt per scheduled call, no retries, no output repair, and
  the same deterministic graders;
- the v1.1 score-and-continue treatment of exact output-budget exhaustion;
- fail-closed handling of every other apparatus failure.

The source-neutral inference fingerprint is pinned to the sealed v1.2
PRECHECK as
`e563686089680920898c8cdaaf07c98754b2bd2e67e85e6c82b45d4cd96d891e`.
Every child PRECHECK hash and source revision must equal the root binding, and
the returned model identity must remain identical across all 144 calls.

The run is sequential because the inherited protocol bindings are process
global. There is no interim success stop. If any replication has an apparatus
failure, v1.3 stops, preserves every completed artifact, and is INVALID. A
failed replication is not replaced.

## Frozen inference

C0 versus Raw remains primary. C1 versus C0 is hierarchical secondary. C2
remains the known-loss boundary control.

For each complete replication, the original v1.2 no-regression and per-case
zero-distortion predicates remain unchanged. Across the six new replications:

- if any complete replication triggers v1.2's frozen low-solver-capability
  gate (no condition exceeds 10/20), the aggregate is
  `VALID_INCONCLUSIVE_LOW_SOLVER_CAPABILITY` and no representation inference
  is licensed;
- `OBSERVED_NO_REGRESSION_ALL_SIX` requires C0 to satisfy aggregate
  no-regression in all six runs. Per-case zero distortion is reported
  separately and requires all six runs to pass that stricter predicate. This
  supports the frozen criterion; it is not a statistical equivalence test.
- `SYSTEMATIC_CORRECTNESS_REGRESSION` requires a negative run-level correctness
  effect that reaches `p < .05` in the frozen two-sided exact sign test.
- chronology-error and illegal-promotion sign tests are descriptive safety
  diagnostics, not two additional unadjusted confirmatory tests. Six
  directionally worse safety outcomes are labeled as an observed safety
  regression rather than a family-wise statistical claim.
- every other valid pattern is
  `CONSISTENT_WITH_STOCHASTIC_VARIATION_NOT_PROVEN` / `INCONCLUSIVE_MIXED`.

Failure to reject a directional effect does not prove equivalence. Pooled
case-level trials are descriptive because answers within a physical batch can
be correlated; the sign test uses the complete 20-case replication as its
unit. A case-specific representation mechanism is flagged only if the same
Raw-only case recurs in all six new replications with no favorable reversal.

No result proves Hive generally. A stable result is scoped to this frozen case
pack, representation family, solver, model configuration, and protocol.

Fresh artifact directory:

`.hive/benchmarks/decompression_test/luna-frontier-v1-3-001`

Live execution is locked to that directory and requires it not to exist. Test
code may inject temporary directories only with committed-source enforcement
disabled. This prevents replacement samples or favorable output selection
under the v1.3 identifier.

Maximum physical generation calls: 144. Expected cost from the sealed v1.2
usage is approximately `$0.294`. The tokenizer-independent conservative bound
is `$1.7192088`; the frozen authorization ceiling is `$1.75`.

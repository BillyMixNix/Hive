# Hive Experiment 3 — Matched-Size Semantic Control

Identity: `hive-luna-matched-size-semantic-control-v1`

Version: `1.0`

Implementation: `ecdaed49915a46e0b9de5505bed57a4d0523633c`

Run: `.hive/benchmarks/decompression_test/luna-matched-size-semantic-control-v1-001`

Acknowledgement: `--acknowledge-frozen-matched-semantic-control-v1`

This document is the protocol-only preregistration. It is committed after the
implementation/tests commit and before the first live call. No live output was
inspected while defining it.

## 1. Narrow research question

Study 2 found that deleting `kind`, `authority`, and `status` together caused a
large performance and inference-cost failure, while single-field deletions
remained near ceiling. Experiment 3 asks only:

> Does C1 work because the K/A/S columns contain useful semantic information,
> or can three additional structured columns, matched visible-state bytes, and
> regular formatting recover the benefit without those semantics?

The experiment does not test Hive generally, transfer, learned abstraction,
new compression, prompt optimization, other models, or new benchmark worlds.

## 2. Sealed evidence lineage

The implementation verifies all of these objects before inference:

- Study 2 starting checkpoint:
  `7b13c99c237315fb6a6330f3607c3591edeaa9c5`
- Study 2 implementation:
  `7e3f35e1d8b135fa2cfc7a6e36090b68a7e60e82`
- Study 2 sealed evidence:
  `3e3a746061bc72f3b052c607259178c262bd952a`
- Study 2 evidence subtree:
  `f0db41367d55f4ea8ad063abeabc07b395c1f157`
- Study 2 `RESULT.json` SHA-256:
  `f92398a86d513d1dd8bbc66184e4d57dfd6f770b3e51b2ac078341868d092dbd`
- Study 2 `EVIDENCE_INDEX.json` SHA-256:
  `1b99589d6ef9c1c3341c3e45531cec77a7670b68830d6ed2e1fa5c955d7361ec`

The current history must be:

1. sealed Study 2 evidence;
2. one implementation commit changing exactly the Experiment 3 module and
   its test module;
3. one protocol commit changing exactly this file.

Any other parentage or source drift is an apparatus failure.

Study 2 remains prior evidence only. Experiment 3 reruns contemporaneous C1
and KAS- controls and does not reuse Study 2 model outputs as observations.

## 3. Frozen benchmark and solver

All three conditions use the exact frozen 20 deterministic worlds, six frozen
batches, questions, answer choices, oracle, grader, chronology/authority
classifications, batching policy, and strict response schema used by the valid
Study 2 apparatus. C1 and KAS- solver prompts must be byte-identical to their
sealed Study 2 prompts for all six batches.

Solver configuration:

- provider: OpenAI Responses API;
- model: `gpt-5.6-luna`;
- reasoning effort: `medium`;
- maximum output tokens: `16384`;
- service tier: `default`;
- tools: none;
- storage: false;
- truncation: disabled;
- reasoning context: current turn only;
- prompt-cache mode: explicit;
- previous response ID / conversation carry-over: none;
- physical attempts: exactly one per scheduled call;
- retry, repair, fallback, resume, overwrite, and salvage: none.

Returned model identity and service tier must remain constant. The strict
structured response is the frozen batch-cardinality `answers` array containing
only `A`, `B`, `C`, `D`, or `INSUFFICIENT`.

## 4. Frozen conditions

### C1 — semantic control

Ordered columns:

`ref, effective_t, kind, authority, status, requires, effects`

### KAS- — semantic bundle removed

Ordered columns:

`ref, effective_t, requires, effects`

### M3 — matched-size nonsemantic control

M3 begins with the KAS- projection and adds exactly three opaque columns in
the structural positions occupied by the removed bundle:

| Ordinal | Frozen key | Frozen value | Key bytes | Value bytes |
|---:|---|---|---:|---:|
| 1 | `_` | `~` | 1 | 1 |
| 2 | `_______` | `^` | 7 | 1 |
| 3 | `___________` | `%` | 11 | 1 |

Thus M3's ordered columns are:

`ref, effective_t, _, _______, ___________, requires, effects`

The three keys contain no Unicode alphanumeric character. The three values
are fixed punctuation. There is no seed, lookup table, encrypted substitution,
per-row adaptation, or category-dependent mapping.

The filler generator accepts only `record_count`. It does not receive source
rows, target bytes, case IDs, event values, questions, choices, oracle labels,
grading metadata, model outputs, or prior results. Every row receives the same
tuple `("~", "^", "%")`.

The semantic names have individual UTF-8 lengths `4/9/6`; the opaque names
have `1/7/11`. Only the aggregate 19-byte key-name budget matches. This avoids
encoding the identity of each removed semantic name through its individual
length. Every frozen K/A/S value and every M3 value is one unescaped ASCII byte,
so exact aggregate size matching requires no inspection of the category values.

Changing arbitrary K/A/S source values while holding the nonsemantic structure
fixed must leave the complete M3 projection byte-identical.

## 5. Canonical projection and exact size boundary

Every projection is recursively detached through canonical JSON. Dictionary
insertion history, source aliases, and later nested mutation cannot alter the
projected packet. Conditions may differ only as follows:

- C1 versus KAS-: deletion of `kind`, `authority`, and `status`;
- M3 versus KAS-: insertion of the three frozen opaque columns and values.

No question-aware selection or other state transformation is permitted.

The primary visible-state matching boundary is canonical compact UTF-8 JSON of
the ordered list of representation objects in each batch. Frozen tolerance is
zero bytes. Full prompt bytes are also exactly equal between C1 and M3; provider
input tokens are measured rather than assumed equal.

Deterministic preflight values:

| Batch | C1 state bytes | M3 state bytes | KAS- state bytes | C1/M3 full-prompt bytes | KAS- full-prompt bytes |
|---:|---:|---:|---:|---:|---:|
| 1 | 6520 | 6520 | 5448 | 30348 | 26024 |
| 2 | 6567 | 6567 | 5495 | 30143 | 25819 |
| 3 | 4833 | 4833 | 4029 | 22768 | 19525 |
| 4 | 4075 | 4075 | 3415 | 19872 | 17241 |
| 5 | 4807 | 4807 | 4003 | 22839 | 19596 |
| 6 | 5706 | 5706 | 4758 | 26505 | 22650 |

Summed per 20-world replication, canonical individual-packet state bytes are
C1 `32482`, M3 `32482`, and KAS- `27122`.

The solver request exposes no condition ID. All conditions share the same
solver prefix, questions, choices, output schema, and provider settings.

## 6. Required preflight invariants

Before a live directory is created, deterministic preflight must prove:

1. exact sealed lineage and untouched prior artifacts;
2. exact benchmark and expanded-world hashes;
3. C1 and KAS- prompt equivalence to sealed Study 2;
4. M3 semantic independence under arbitrary K/A/S substitutions;
5. projection blindness to questions, choices, oracle, decoys, and grading data;
6. exact condition isolation;
7. recursive canonical detachment and deterministic serialization;
8. punctuation-only semantic-vocabulary exclusion, including one-character
   category codes;
9. exact per-case, per-batch, and full-prompt C1/M3 byte equality;
10. exact schedule, request-plan, schema-cardinality, and solver hashes;
11. one attempt, no retry/fallback/tools/storage/carry-over/resume/overwrite;
12. strict response parsing and deterministic regrading;
13. source files equal the committed blobs throughout the run;
14. the authorized run directory does not already exist;
15. the conservative cost bound remains under the authorized ceiling.

Any failure blocks live inference.

## 7. Frozen schedule

The schedule contains eight complete stochastic replications. Each replication
contains all six batches and all three conditions:

`3 conditions × 8 replications × 6 batches = 144 calls`.

Within each replication, batches remain in the frozen order 1 through 6. The
condition orders use these six permutations once each:

1. `C1, M3, KAS-`
2. `M3, KAS-, C1`
3. `KAS-, C1, M3`
4. `KAS-, M3, C1`
5. `C1, KAS-, M3`
6. `M3, C1, KAS-`

Replication `r` rotates this six-order cycle left by `(r - 1) mod 6`. Across
the 144 requests, each condition occupies each ordinal position exactly 16
times and each ordered pair precedes the other exactly 24 times.

Frozen schedule SHA-256:
`3263572168bdf2d2b1f5dad34441aa9bdf09ed1c9faff6a6a694dabf72f4ce58`

Frozen request-plan SHA-256:
`56fd5abc0c8625d3c7e46022b3959ef49c9ec4a62191441b1a47768a0c631a46`

## 8. Estimand and statistics

Primary estimand:

> Expected solver accuracy on these fixed 20 benchmark worlds under repeated
> stochastic inference using the frozen Luna configuration.

The complete 20-world stochastic replication is the inferential unit. The 20
worlds are repeated fixed benchmark units, not 160 independent population
samples. Generation batches induce within-call dependence and are absorbed
inside each complete replication.

### Confirmatory primary comparison

For replication `r`:

`d_r = M3_correct_r - C1_correct_r`

All eight complete paired differences are reported. The test is the exact
two-sided sign-flip test used in Study 2:

- statistic: `abs(sum(d_r))`;
- enumerate all `2^8 = 256` sign assignments;
- count assignments with statistic greater than or equal to the observed one;
- p-value is that count divided by 256;
- zero differences remain in all eight slots and all 256 assignments;
- alpha: `.05`;
- multiplicity correction: none, because there is one primary comparison.

No case-level inferential test is permitted. Incomplete replication vectors are
not imputed or reduced to a seven-replication analysis.

### Preregistered secondary mechanistic comparison

M3 versus KAS- uses the same exact paired sign-flip test on eight complete
replication aggregates:

`M3_correct_r - KAS-_correct_r`

This is one separately preregistered secondary mechanistic comparison, with no
multiplicity adjustment. It may inform only the frozen outcome table below; it
does not replace or alter the primary test.

### Contemporaneous control and drift gates

KAS- versus C1 is an adequacy gate. It clears only when the two-sided p-value is
at most `.05` and the mean `KAS- - C1` effect is negative. Failure of this gate
forces a valid inconclusive result.

C1 aggregate accuracy below `144/160` triggers `BASELINE_DRIFT` and a valid
inconclusive result. Exactly `144/160` does not trigger drift.

Non-rejection of M3 versus C1 is never statistical equivalence. For the frozen
outcome table only, “near C1” is a descriptive recovery rule:

`C1 aggregate correct - M3 aggregate correct <= 4 answers out of 160`.

Four is inclusive; five is not. This 2.5-percentage-point margin is not an
equivalence test.

## 9. Frozen interpretation and dispositions

Classification applies in this precedence order:

1. C1 below `144/160` → `VALID_INCONCLUSIVE / BASELINE_DRIFT`.
2. contemporaneous C1/KAS- gate fails →
   `VALID_INCONCLUSIVE / CONTEMPORANEOUS_CONTROL_NOT_REPLICATED`.
3. M3 aggregate is below KAS- →
   `VALID_INCONCLUSIVE / CONTROL_DISTRACTION_M3_BELOW_KAS`.
4. primary M3-C1 harm is significant and the preregistered M3-KAS secondary is
   significantly positive →
   `VALID_MIXED_RESULT / BOTH_STRUCTURE_AND_SEMANTICS_CONTRIBUTE`.
5. primary M3-C1 harm is significant without that positive secondary result →
   `VALID_SUPPORTED_SEMANTIC_CONTROL / M3_FAILED_TO_RECOVER_C1`.
6. M3 significantly exceeds C1 →
   `VALID_STRUCTURAL_ALTERNATIVE_SUPPORTED / M3_EXCEEDED_C1`.
7. the primary is not significant, M3 is within four answers of C1, and M3
   significantly exceeds KAS- →
   `VALID_STRUCTURAL_ALTERNATIVE_SUPPORTED / M3_NEAR_C1_AND_IMPROVED_OVER_KAS`.
8. all other valid patterns →
   `VALID_INCONCLUSIVE / NO_PREREGISTERED_INTERPRETATION_CLEARED`.

Interpretation 7 supports only a benchmark-scoped structural alternative; it
does not assert statistical equivalence. An intermediate nonsignificant result
more than four answers below C1 remains inconclusive.

If M3 is worse than KAS-, it is a possible noise/distraction or control-design
effect, not stronger evidence for semantics. No post-hoc control redesign is
allowed in this run.

## 10. Fail-closed live policy

This protocol chooses the strict form of the user-authorized fail-closed rule:
any transport, timeout, incomplete response, parser rejection, schema failure,
grader failure, response-ID reuse, model/tier drift, source drift, token/config
mismatch, or artifact-integrity failure after the first live call immediately
stops the schedule and seals `INVALID_APPARATUS` with all partial artifacts.

No failed call is retried, repaired, resumed, replaced, or salvaged. No semantic
claim is licensed from a partial run. A new reason for apparatus failure requires
a separately frozen future protocol starting from physical call 1.

## 11. Cost and frozen hashes

The exact canonical request UTF-8 byte length is used as a conservative,
tokenizer-independent upper bound on input tokens. Provider usage is
authoritative after the run.

- authorized ceiling: `$100.00`;
- conservative input-token upper bound: `3886160`;
- output-token upper bound: `2359296`;
- conservative generation-cost upper bound: `$3.6083872`;
- solver-config SHA-256:
  `0fa9c5f438388516fd4ac130c44320f08cafb7bddbad6e102444326c56a04b54`;
- M3-construction SHA-256:
  `0f0b82917eb89aefd7905cc711a68c2478c060fb0b99611a1e254fe43f4e2b74`.

Actual input, output, reasoning, and total tokens; latency; state bytes; calls;
and API cost are recorded separately for C1, M3, and KAS-.

## 12. Evidence, audit, and claim ceiling

Every request, raw response, response ID, provider metadata, parser decision,
deterministic grade, score, and usage record is written immutably. `RESULT.json`,
`RUN_STATUS.json`, and `EVIDENCE_INDEX.json` are sealed and independently
recomputed by the verifier.

The implementation and statistics reviews must be ACCEPT before this protocol
commit. The Protocol Auditor and Implementation Adversary must then ACCEPT this
exact committed snapshot before inference. After the run, independent Evidence
and Claim Adversaries inspect the physical artifacts. The final evidence commit
may add only the sealed experiment directory and report/index material; it may
not alter implementation or protocol source.

Even a clean result is scoped only to these 20 fixed worlds, this exact
representation grammar and M3 operation, and the returned Luna model/service
tier under eight stochastic replications. It does not establish Hive generally,
transfer, learned abstraction, universal authority semantics, Sol equivalence,
AGI, or recursive improvement.

The one authorized live command is:

```powershell
python -m kingdom.decompression_matched_semantic_control_luna --acknowledge-frozen-matched-semantic-control-v1
```

No live call may begin until the protocol-only commit exists, the committed
preflight passes, both final pre-inference auditors return ACCEPT, the API
credential is present, and the authorized run directory is absent.

# Hive Experiment 2 — Semantic Authority Decomposition v1

This is a new preregistered experiment descended from sealed evidence commit
`7b13c99c237315fb6a6330f3607c3591edeaa9c5`, whose implementation parent is
`a87e54e1af7960dfb67d55c3f4e6c818bc28983f`. All earlier protocols and
artifacts remain sealed. This experiment does not test Hive generally,
transfer, learned abstraction, Sol, retrieval, Raw superiority, recursive
improvement, or prompt compression generally.

## Question and estimand

The experiment asks which individual fields, or interactions among fields, in
the C1→C2 `kind`/`authority`/`status` bundle account for the sealed Luna
performance collapse.

The target estimand is expected solver accuracy on these fixed 20 frozen
benchmark worlds under repeated stochastic inference with the specified Luna
configuration. A complete 20-world stochastic replication is the primary
inferential unit. The 20 worlds are fixed repeated units, not 160 independent
draws from a broader population. Cases are grouped into six batches of 3 or 4;
cases within each call are dependent.

## Frozen representations

Every packet starts from exact C1 columns:

`ref, effective_t, kind, authority, status, requires, effects`

`record_t` is absent in every condition. Projection is query-blind deletion of
named columns only:

| Condition | Deleted columns |
|---|---|
| C1 | none |
| K- | kind |
| A- | authority |
| S- | status |
| KA- | kind, authority |
| KS- | kind, status |
| AS- | authority, status |
| KAS- | kind, authority, status |

Projection code receives only an exact C1 packet and a canonical condition ID.
It cannot receive or inspect question text, choices, oracle labels, correct
answers, required references, error categories, event roles, decoy labels, or
prior model outputs. C1 prompts must be byte-identical to sealed prior C1
prompts, and KAS- prompts must be byte-identical to sealed prior C2 prompts for
every corresponding batch. No metadata exclusion is needed for these prompt
comparisons.

The benchmark is the exact frozen 20-case pack, including worlds, event order,
questions, choices, batch membership, oracles, and deterministic secondary
grading.

## Solver contract

- OpenAI Responses API
- model `gpt-5.6-luna`
- medium reasoning effort
- 2,048 maximum output tokens
- no tools
- exactly one physical attempt
- no retry, repair, fallback, resume, or overwrite
- `store=false`
- truncation disabled
- current-turn reasoning context only
- default service tier
- explicit no-breakpoint cache policy
- the same strict batch-cardinality answer schema used by the sealed Luna work

The explicitly required Experiment-2 output allowance is 2,048. The sealed
v1.3 replication used 4,096; this is an unavoidable, prominently recorded
solver-setting difference. Any incomplete/truncated response is an apparatus
failure in Experiment 2 and is never scored or salvaged.

Returned model identity and returned service tier must remain constant. Every
response ID must be nonempty and unique. Parser, transport, schema,
token-accounting, response-identity, truncation, cache, retry, provider, or
deterministic-grader failure stops the run as `INVALID_APPARATUS`. Partial
artifacts remain evidence and are not repaired or replaced.

## Replication and order

There are exactly eight complete replications, eight conditions, and six
frozen batches per condition: at most 384 physical generation calls. Within a
condition, batches remain in frozen order 1–6.

The even-order Williams schedule is:

1. C1, K-, KAS-, A-, AS-, S-, KS-, KA-
2. K-, A-, C1, S-, KAS-, KA-, AS-, KS-
3. A-, S-, K-, KA-, C1, KS-, KAS-, AS-
4. S-, KA-, A-, KS-, K-, AS-, C1, KAS-
5. KA-, KS-, S-, AS-, A-, KAS-, K-, C1
6. KS-, AS-, KA-, KAS-, S-, C1, A-, K-
7. AS-, KAS-, KS-, C1, KA-, K-, S-, A-
8. KAS-, C1, AS-, K-, KS-, A-, KA-, S-

Every condition occupies every ordinal position exactly once. The canonical
schedule SHA-256 is
`9b411628e56d291a26b5a0e44bca54577484957b26adc945f38199fabce596cd`.
Within each replication, batches execute in order 1–6 and the corresponding
Williams row is applied inside each batch. The complete deterministic
384-request plan SHA-256 is
`29706dd5d1361f0bdf66a48b58cd00c453850740f740046c169847069a5e6640`.

## Confirmatory inference

The three primary comparisons are C1 versus K-, C1 versus A-, and C1 versus
S-. For each replication, the paired difference is
`correct(condition) - correct(C1)` over all 20 fixed worlds.

Each comparison uses the preregistered exact two-sided sign-flip test over all
`2^8` sign assignments to the eight replication differences, with absolute
sum as the statistic. Holm correction applies across exactly these three
primary tests. A field is individually load-bearing only when its Holm-adjusted
`p <= .05` and its mean condition-minus-C1 difference is negative.

KA-, KS-, AS-, and KAS- are secondary mechanistic conditions. Their frozen
interaction vectors are:

- `I_KA = y_KA - y_K - y_A + y_C1`
- `I_KS = y_KS - y_K - y_S + y_C1`
- `I_AS = y_AS - y_A - y_S + y_C1`
- `I_KAS = y_KAS - y_KA - y_KS - y_AS + y_K + y_A + y_S - y_C1`

These four interaction vectors use the same exact two-sided `2^8` sign-flip
test and a separate Holm family of four. They are never promoted into the
three-test primary family after outputs are seen.

The sealed prior C2−C1 replication vector is
`[-17,-17,-17,-16,-17,-17]`. New KAS−C1 has eight entries. Behavioral
replication uses the frozen exact two-sample permutation test over all
`C(14,6)=3003` allocations with
`abs(mean(group6)-mean(group8))`. The observed allocation is included and no
plus-one correction is used. `p <= .05` yields
`VALID_KAS_REPLICATION_FAILURE`; non-rejection is only “no detected
discrepancy,” never equivalence.

## Frozen disposition precedence

1. Any apparatus failure: `INVALID_APPARATUS`.
2. C1 below 144/160: `VALID_BASELINE_DRIFT`; semantic statistics remain
   descriptive and license no supported semantic conclusion. Exactly 144 does
   not trigger drift.
3. KAS behavioral permutation `p <= .05`:
   `VALID_KAS_REPLICATION_FAILURE`.
4. Two or three harmful Holm-significant single fields:
   `VALID_SUPPORTED_DISTRIBUTED_BUNDLE`.
5. Exactly one harmful Holm-significant single field: the corresponding
   `VALID_SUPPORTED_KIND_LOAD_BEARING`,
   `VALID_SUPPORTED_AUTHORITY_LOAD_BEARING`, or
   `VALID_SUPPORTED_STATUS_LOAD_BEARING`.
6. No harmful significant single but at least one harmful Holm-significant
   interaction: `VALID_SUPPORTED_MULTIFIELD_INTERACTION`.
7. All three primary adjusted p-values exceed .05:
   `VALID_NO_SINGLE_FIELD_EFFECT`, meaning no effect detected—not equivalence.
8. Any remaining valid pattern: `VALID_NOT_SUPPORTED`.

Model or service-tier drift is an apparatus failure, not baseline drift.

## Representation and cost metrics

“Visible state” means canonical serialized UTF-8 bytes of the representation
object supplied for all 20 worlds. Bytes and API tokens are always reported
separately. Absolute per-replication and eight-replication state bytes, actual
API input/output/reasoning/total tokens, latency, calls, and dollars are
recorded by condition. Token comparisons to Raw use the sealed v1.3 Raw mean
as a clearly marked noncontemporaneous reference.

Every exact request is serialized before inference. Its UTF-8 byte length is
a conservative tokenizer-independent upper bound on input tokens. The frozen
bound is 10,091,776 input tokens plus 786,432 output tokens, for no more than
`$2.9620736` at the pinned rates. The Pilot's frozen authorized ceiling is
`$100.00`; actual API usage remains authoritative.

## Claim ceiling

Any support is limited to this frozen 20-world benchmark, this representation
grammar, this Luna solver identity/configuration, these exact column
projections, and repeated stochastic inference under this protocol. It does
not establish Hive generally, transfer, learned abstraction, universal
authority semantics, model substitution, Sol equivalence, general causal
necessity, AGI, or recursive improvement.

The only authorized live directory is
`.hive/benchmarks/decompression_test/luna-semantic-authority-decomposition-v1-001`.
It must not exist before inference. Implementation and evidence are committed
separately; an evidence commit may not alter experiment code.

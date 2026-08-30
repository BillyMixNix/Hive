# Hive Luna/Sol × Raw/C1 Factorial — Protocol v1

## Status and lineage

This is a new, preregistered experiment. It does not modify, rerun, reinterpret,
or overwrite any earlier experiment.

Its sealed parent is commit
`81dc05d320c7989d2ad9b169a9ef39623ccb8b3b`, which seals the completed
Luna+C1 versus Sol+Raw experiment. Before inference, preflight must resolve that
commit exactly and verify the sealed parent artifacts, including:

- `RESULT.json` SHA-256:
  `de076ec96ef8b1c87966d6607215ec18ae6ca5cf5af4d6f4187fc9448d1064d1`
- `EVIDENCE_INDEX.json` SHA-256:
  `f0a1395b4a1608387cce0587478eceb428408887f8178c3a288e65dda6a6c41d`
- 72 physical calls, 72 unique response IDs, and a `VALID` parent result.

The parent responses are prior evidence only. No response, score, or stochastic
output from that experiment may be reused in this one.

## Research question

On the frozen 20-world decompression benchmark, how do solver model and supplied
representation affect accuracy, chronology/authority safety, token use, API
cost, and latency?

The factorial design separates the two factors that the sealed two-arm study
changed together:

1. solver model: GPT-5.6 Luna versus GPT-5.6 Sol;
2. representation: full Raw history versus Hive's compact C1 semantic ledger.

The experiment asks whether C1 changes performance within each model and
whether that representation effect differs between Luna and Sol. It does not
test learned compression, transfer, long-horizon workflows, or Hive generally.

## Four frozen arms

Run exactly these four conditions:

| Condition | Model | Representation |
| --- | --- | --- |
| `LUNA_RAW` | `gpt-5.6-luna` | full verbose Raw history |
| `LUNA_C1` | `gpt-5.6-luna` | compact C1 semantic ledger |
| `SOL_RAW` | `gpt-5.6-sol` | full verbose Raw history |
| `SOL_C1` | `gpt-5.6-sol` | compact C1 semantic ledger |

The Raw representation is the exact frozen full verbose history. C1 contains
exactly these named columns:

- `ref`
- `effective_t`
- `kind`
- `authority`
- `status`
- `requires`
- `effects`

`record_t` remains absent from C1. There is no question-aware selection,
retrieval, projection, or adaptation. For a given representation, the prompt
and input payload must be byte-identical across Luna and Sol. For a given model,
the frozen solver configuration must be identical across Raw and C1. The model
ID and representation payload are the only intended factorial differences.

## Frozen benchmark and prompt

Reuse the exact sealed benchmark apparatus:

- the same 20 deterministic worlds;
- the same six generation batches and within-arm batch order;
- the same histories, event order, questions, answer options, and oracle;
- the same chronology, authority, illegal-promotion, and correctness graders;
- the same strict output schema and exact batch cardinality;
- the same Raw and C1 input payloads used by the sealed frontier apparatus.

Use the neutral shared solver title from the sealed two-arm experiment. Apart
from that already sealed neutral title, the solver instructions must remain
byte-identical to the frozen Raw/C1 prompts. The prompt must not disclose which
model is running, compare conditions, or include prior results.

The response schema contains one field, `answers`, whose array length must equal
the current batch size exactly. Every item must be exactly one of `A`, `B`, `C`,
`D`, or `INSUFFICIENT`. Do not recover fenced output, embedded JSON, answer
text, partial arrays, or malformed responses.

## Frozen solver contract

Every arm uses:

- OpenAI Responses API;
- reasoning effort `medium`;
- maximum output allowance `16,384` tokens;
- default service tier;
- current-turn-only reasoning context;
- strict structured output;
- no tools;
- `store=false`;
- truncation disabled;
- explicit prompt-cache mode with no cache breakpoint;
- no `previous_response_id` or conversation carry-over;
- exactly one physical attempt per scheduled call;
- no retry, repair, fallback, or output salvage;
- a 900-second request timeout.

Returned model identity, service tier, SDK behavior, response status, response
ID, structured-output schema hash, and token accounting must be recorded and
validated. Every response ID must be unique across all four arms.

## Replications, batches, and frozen order

Run exactly eight complete stochastic replications. Every replication contains
all four conditions over all six frozen batches:

`8 replications × 6 batches × 4 conditions = 192 physical calls`.

Each condition therefore receives 48 generation calls and 160 fixed-world
answers. No call may be repeated.

Use this four-row Williams schedule, with abbreviations in the order shown:

- `A = LUNA_RAW`
- `B = LUNA_C1`
- `C = SOL_RAW`
- `D = SOL_C1`

Base rows:

1. `A, B, D, C`
2. `B, C, A, D`
3. `C, D, B, A`
4. `D, A, C, B`

Flatten the 48 replication/batch blocks in replication-major order, preserving
batch order 1 through 6 inside each replication. Select base row
`block_index mod 4`, where the first block has index zero. Each base row is
therefore used exactly 12 times. Every condition occupies every ordinal
position exactly 12 times, and every directed adjacent carry-over occurs
exactly 12 times. Freeze and hash the complete 8 × 6 schedule before inference.
Order may never depend on results.

## Estimand and inferential unit

The estimand is expected solver accuracy on these fixed 20 benchmark worlds
under repeated stochastic inference with the specified model and
representation configuration.

The complete 20-world replication is the inferential unit. The 20 worlds are
repeated fixed benchmark units, not 160 independent samples from a broader
world population. Generation batching adds within-call dependence. Case-level
totals and error identities are descriptive only.

For replication `r`, define the four correct-answer counts out of 20 as:

- `LR_r = correct(LUNA_RAW)`
- `LC_r = correct(LUNA_C1)`
- `SR_r = correct(SOL_RAW)`
- `SC_r = correct(SOL_C1)`

## Three confirmatory hypotheses

The confirmatory family contains exactly these three comparisons:

1. `H_LUNA_REPRESENTATION`
   - paired difference: `D_LUNA_r = LC_r - LR_r`
   - asks whether C1 changes accuracy relative to Raw for Luna.
2. `H_SOL_REPRESENTATION`
   - paired difference: `D_SOL_r = SC_r - SR_r`
   - asks whether C1 changes accuracy relative to Raw for Sol.
3. `H_MODEL_BY_REPRESENTATION_INTERACTION`
   - paired difference-in-differences:
     `D_INTERACTION_r = (LC_r - LR_r) - (SC_r - SR_r)`
   - asks whether the C1-minus-Raw effect differs between Luna and Sol.

For each comparison, report all eight replication-level differences and use the
same exact two-sided paired sign-flip analysis:

- enumerate all `2^8 = 256` sign assignments;
- use the absolute sum of paired differences as the statistic;
- count assignments at least as extreme as the observed absolute sum;
- include zero differences as ties;
- report the exact uncorrected p-value.

Apply Holm's step-down correction across exactly these three confirmatory
hypotheses at family-wise `alpha = 0.05`. Report both raw and Holm-adjusted
p-values, rejection decisions, mean paired difference out of 20, and aggregate
paired difference out of 160. No other comparison may be added to this
confirmatory family after outputs exist. Non-rejection is not equivalence.

Model comparisons within Raw (`SOL_RAW` versus `LUNA_RAW`) and within C1
(`SOL_C1` versus `LUNA_C1`) may be reported only as explicitly secondary,
descriptive comparisons unless separately preregistered before inference. Do
not treat case answers as independent Bernoulli trials.

Two additional secondary factorial summaries are frozen:

- pooled representation contrast:
  `(LC_r - LR_r) + (SC_r - SR_r)`;
- pooled model contrast:
  `(SR_r + SC_r) - (LR_r + LC_r)`.

The exact sign-flip tests use those integer doubled contrasts. For effect-size
reporting, divide each contrast by two and label it explicitly as the
normalized main effect in answers out of 20. These secondary p-values are not
part of the three-test Holm family and cannot be promoted after inference.

## Capability warning

Raw is the capability reference for each model. Freeze this rule:

- if `LUNA_RAW` is below 144/160 correct, or
- if `SOL_RAW` is below 144/160 correct,

the top-level result is `VALID_CAPABILITY_WARNING` provided the apparatus is
otherwise valid. Preserve all descriptive results and statistics. A failed
Raw gate blocks that model's simple representation-effect claim; it does not
block the other model's simple effect when that other model passes its own Raw
gate. Either Raw-gate failure blocks the representation-by-model interaction
claim. Do not discard replications or cases because Raw makes stochastic
errors.

## Required descriptive reporting

For every arm, report:

- correct and admissible answers out of 160;
- all eight correct-answer counts out of 20;
- exact world-level error identities;
- chronology errors;
- authority errors;
- illegal state promotions;
- `INSUFFICIENT` answers;
- parser, grader, transport, and incomplete-response failures;
- serialized representation UTF-8 bytes;
- provider input, output, reasoning, and total tokens;
- latency and mean latency per physical call;
- actual API cost;
- physical call count and unique response-ID count.

Bytes must not be called tokens. Provider usage is authoritative for actual
token and cost accounting. Latency is descriptive because default-tier queueing
is uncontrolled.

## Cost authorization

Freeze pricing for experiment accounting at:

- GPT-5.6 Luna: $0.20/M input tokens and $1.20/M output tokens;
- GPT-5.6 Sol: $4.00/M input tokens and $20.00/M output tokens.

Before inference, serialize every deterministic request and compute a
tokenizer-independent conservative upper bound by treating request UTF-8 bytes
as input tokens and charging the complete 16,384-token output allowance for all
192 calls. The exact derived bound and per-arm bounds must be frozen in code and
the precheck. This experiment freezes a $55 ceiling beneath the Pilot's $100
maximum. If the total exceeds $55, stop before creating the live run directory.
Never silently raise either limit.

## Preflight and apparatus validity

Deterministic tests and preflight must establish at minimum:

- exact sealed-parent lineage and parent artifact hashes;
- frozen case-pack and expanded-world hashes;
- prior evidence remains untouched;
- exactly four canonical conditions and the correct model/representation map;
- Raw prompts are identical across models;
- C1 prompts are identical across models;
- each model's solver settings are identical across representations;
- Raw and C1 payloads match their sealed source payloads;
- exact strict schema and batch cardinality for every call;
- the complete Williams schedule and its hash;
- every condition in every batch and replication;
- 48 calls and 160 answers per condition;
- exactly 192 scheduled physical calls;
- one-attempt enforcement and no retry, repair, fallback, tools, storage,
  carry-over, resume, or overwrite;
- unique response IDs and arm-appropriate returned model identities;
- recursively canonical, stable serialization;
- deterministic grading and statistics;
- the three-member Holm family and no pseudoreplication;
- a conservative cost bound no greater than the frozen $55 experiment ceiling;
- credentials absent from requests, artifacts, and sanitized errors;
- the live run directory does not exist before inference.

## Fail-closed execution rules

Any unresolved preflight defect stops the experiment before inference.

After physical call 1, any transport, parser, schema, cardinality, truncation,
response-identity, returned-model, service-tier, token-accounting, grader,
source-integrity, schedule, artifact, or cost-accounting defect invalidates the
apparatus. Stop immediately, preserve all partial artifacts, and report
`INVALID_APPARATUS`. Do not repair, resume, rerun, replace, or salvage the run.
A malformed or rejected response is an experimental artifact, not permission
for another attempt.

The implementation, tests, exact schedule, frozen derived constants, and this
protocol must be committed before call 1. No source, prompt, threshold,
hypothesis, statistic, interpretation, or condition may change after the first
live call. Seal evidence in a separate evidence-only commit.

## Frozen dispositions

Use one top-level validity disposition:

- `INVALID_APPARATUS`: any apparatus failure.
- `VALID_CAPABILITY_WARNING`: valid apparatus, but either per-model Raw arm is
  below the frozen 90% threshold.
- `VALID_FACTORIAL_COMPLETE`: valid apparatus and both Raw capability checks
  pass.

For a `VALID_FACTORIAL_COMPLETE` run, report a separate machine-readable
decision for each confirmatory hypothesis after Holm correction:

- `SUPPORTED_POSITIVE`: adjusted `p <= .05` and the mean frozen difference is
  positive;
- `SUPPORTED_NEGATIVE`: adjusted `p <= .05` and the mean frozen difference is
  negative;
- `NOT_SUPPORTED`: adjusted `p > .05` or the mean difference is zero.

Multiple scoped decisions may coexist. Do not convert a valid negative or
ceiling result into apparatus failure. Do not describe `NOT_SUPPORTED` as proof
of no effect or equivalence.

## Interpretation and claim ceiling

A positive, Holm-supported Luna or Sol representation contrast supports only
the benchmark-scoped statement that C1 improved expected accuracy relative to
Raw for that named model under this frozen configuration. A negative contrast
supports the correspondingly scoped harmful-effect statement.

A Holm-supported interaction supports only the statement that the observed C1
minus Raw accuracy effect differed between these two named models on this
benchmark. Its sign must be interpreted using the preregistered
`D_INTERACTION` definition. It does not, by itself, establish that either model
or representation is generally superior.

Even a perfect result does not establish:

- Hive generally;
- general model superiority or substitution;
- transfer to unseen worlds or domains;
- learned abstraction or learned compression;
- long-horizon workflow improvement;
- universal causal, temporal, or authority understanding;
- recursive improvement, AGI, or general intelligence.

No benchmark content, prompt, output budget, parsing rule, hypothesis,
correction family, threshold, or interpretation may be tuned after observing
live outputs. The experiment's purpose is to measure the frozen 2 × 2 system,
including clean negative or inconclusive results, not to produce a favorable
Hive outcome.

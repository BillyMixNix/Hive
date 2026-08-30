# Hive Luna+C1 versus Sol+Raw — Protocol v1

## Question

On the frozen 20-world decompression benchmark, what accuracy, chronology/
authority safety, API cost, token use, and latency are observed for these two
complete systems?

1. `LUNA_C1`: `gpt-5.6-luna` receives Hive's compact C1 ledger.
2. `SOL_RAW`: `gpt-5.6-sol` receives the full verbose history.

This is deliberately a **joint system comparison**. Model and representation
change together. It cannot identify a representation-only effect or a
model-only effect.

## Frozen benchmark and interface

- Exact sealed 20 worlds, questions, options, oracle, six batches, and graders.
- Raw and C1 input payloads are byte-identical to their sealed Luna-frontier
  v1.3 counterparts.
- The inherited title `HIVE LUNA COMPRESSION FRONTIER` is replaced for both
  arms by the shared neutral title `HIVE SYSTEM COMPARISON`. No other solver
  instruction changes.
- Exact batch-cardinality JSON schema; outputs are only `A`, `B`, `C`, `D`, or
  `INSUFFICIENT`.
- Any transport, identity, parser, schema, grading, source-integrity, or
  accounting failure fails closed and preserves partial artifacts.

## Solver contract

Both arms use the OpenAI Responses API, medium reasoning effort, 16,384 maximum
output tokens, default service tier, current-turn-only reasoning context,
strict structured output, no tools, no storage, no retries, no repair, no
fallback, and exactly one physical attempt per scheduled call. The requested
model and supplied representation are the only between-arm differences.

## Schedule and cost

Six complete stochastic replications are the inferential units. Every
replication runs both arms over the same six frozen batches. Arm order
alternates by replication and batch, so each arm occupies each ordinal position
18 times.

Maximum calls: `6 replications × 2 arms × 6 batches = 72`.

Pricing frozen for accounting:

- Luna: $0.20/M input and $1.20/M output.
- Sol: $4.00/M input and $20.00/M output.

The conservative request-byte-plus-full-output allowance must stay below the
Pilot-authorized $100 ceiling. Provider usage is authoritative for actual cost.

## Estimand and analysis

The estimand is observed accuracy, API token cost, and latency of Luna+C1 versus
Sol+Raw on these fixed worlds under repeated stochastic inference. The 20 cases
are repeated benchmark units, not 120 independent population samples. Batching
adds within-call dependence.

For each replication:

`difference = correct(LUNA_C1) - correct(SOL_RAW)` out of 20.

The frozen primary analysis is an exact two-sided sign-flip test over the six
replication differences. Non-rejection is not equivalence. Accuracy, state
bytes, input/output/reasoning tokens, latency, and API cost are also reported
descriptively for each arm.

## Frozen interpretation

- If either arm is below 108/120, report `VALID_CAPABILITY_WARNING`.
- Equal aggregate accuracy: `VALID_OBSERVED_ACCURACY_TIE`.
- Higher Luna+C1 aggregate accuracy:
  `VALID_OBSERVED_LUNA_HIVE_HIGHER_ACCURACY`.
- Higher Sol+Raw aggregate accuracy:
  `VALID_OBSERVED_SOL_RAW_HIGHER_ACCURACY`.
- Any apparatus failure: `INVALID_APPARATUS`.

An observed tie may support benchmark-scoped **Pareto parity** when Luna+C1 also
uses less state, fewer input tokens, and lower cost. It does not prove
statistical equivalence, Hive causality, general superiority, transfer, or
long-horizon workflow performance. Latency is descriptive because default-tier
queueing is uncontrolled.

## Evidence discipline

The implementation and this protocol must be committed before call 1. The run
directory must not exist before inference. Every raw response, request,
transport record, response ID, decision, and failure is append-only. No source
change, rerun, resume, overwrite, retry, repair, or result-conditioned tuning is
permitted after live inference starts.

The CLI may render a presentation-only terminal progress bar after each
scheduled call. It is not an experimental input, does not alter the call plan,
and is not used to derive or grade evidence.

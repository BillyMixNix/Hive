# Hive Decompression Test — Smoke Protocol v1

## Scope

This is a narrow falsification experiment. It does not redesign Hive, expand
Kingdom, or test whether Hive can autonomously learn a good compressor. It asks
whether one frozen, query-blind, typed representation is task-reversible enough
to support temporal and causal reasoning with less solve context.

The synthetic codec is an experimental interface. A positive result is not
evidence that the current Kingdom encoder can construct it from arbitrary data.

## Hypotheses

**H1.** Given the same underlying event history, solver, output contract, call
allowance, and runtime, the frozen compressed representation matches or exceeds
full raw-history and conventional query-conditioned retrieval correctness while
using materially fewer input tokens, preserving chronology/authority, and
reconstructing the minimum relevant causal structure.

**H0.** Once answer leakage, weak retrieval, extra calls, schema-format
advantages, and unequal authority information are removed, compressed state has
no correctness/efficiency advantage; its context savings lose distinctions,
promote illegal state, or weaken causal reconstruction.

## Frozen cases and conditions

The tracked pack contains 20 deterministic cases: five domains by four load
contrasts. The domains are temporal authority/ownership, nested containment,
transformation and supersession, obligations/economics/progression, and
intent-versus-knowledge. Each domain has a low/high distractor contrast and a
low/high required-support contrast. Correct option positions are balanced.

- **A — raw:** complete verbose event records, including effective time, record
  time, authority, status, preconditions, effects, opaque ID, and source prose.
- **B — retrieval:** deterministic BM25 lexical seeds plus generic key/value
  dependency closure over raw chunks. It may use up to four times C's minified
  representation bytes (never more than raw) and must expose 100% of all
  preregistered required/rejected refs. This deliberately gives B more context
  than C rather than making retrieval a straw man. Actual solve tokens—not the
  byte proxy—are the reported comparison.
- **C — compressed:** the complete query-blind typed ledger in fixed-position
  records. It contains no question, answer, legality verdict, gold label, or
  precomputed minimum timeline. Opaque refs resolve to exact hashed raw events.

All conditions use the same JSON question/options/claim catalog, solver
instructions, strict output schema, model, sampling, context/output limits, and
one physical attempt. There is no model judge and no output repair.

Six batches fully counterbalance condition order: every condition appears first,
second, and third exactly twice. There are exactly 18 primary calls (six per
condition). Two separately justified C-only calls contain five indispensable
atom removals and five same-case irrelevant-removal controls. Each five-entry
call mixes roles, but complementary versions of one world never share a model
context. Every removed visible atom becomes the same explicit unknown marker;
entries have opaque aliases and counterbalanced order. They are excluded from
primary A/B/C scores. Total authorized physical calls: 20.

## Frozen runtime

- Model: `qwen2.5-coder:7b`
- Digest: `dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364`
- Context: 32,768 tokens
- Output allowance: 2,048 tokens
- Temperature: 0
- Seed: 73,021
- Timeout: 900 seconds
- Physical attempts per call: 1
- Hidden retries: forbidden
- Prompt clipping: forbidden; oversize/truncation is apparatus failure

## Deterministic authority and grading

Only canonical, completed actual/observation/message events with satisfied
preconditions mutate state. Plans, rumors, ordinary claims, attempts, future
events, and unsatisfied effects do not. Effective time controls chronology;
record time is arrival order only.

Each answer must be strict whole-response JSON with exact keys and bounded lists.
The primary pass is conjunctive:

1. exact option;
2. every required event ref reconstructed;
3. no ref outside the preregistered relevant set;
4. refs in effective-time order;
5. exact relevant rejected/non-current refs;
6. exact current claim selection;
7. fixed correct reasoning code; and
8. zero illegal promotions.

A fixture grader and independently replayed answer/current-claim grader must
agree. Disagreement makes the smoke invalid; it is never majority-voted.
Malformed, truncated, fenced, duplicate-key, unknown-field, or oversized model
output is a fail-closed condition failure. Broken replay, source refs, hashes,
call metadata, persistence, or prompt capacity makes the whole smoke invalid.

## Metrics

The result records, by condition, family, and case:

- conjunctive exact correctness and answer correctness;
- chronology/authority correctness;
- illegal state promotions;
- required-reference recall and allowed-reference precision;
- actual Ollama input/output tokens;
- physical calls and latency;
- representation bytes and event/chunk counts;
- task-reversible source/hash coverage;
- compression-loss versus decompression-use failures; and
- minimum-sufficient-state ablation plus anti-reflex control.

Preprocessing latency and deterministic retrieval selections are preserved in
the precheck artifact. The raw physical request/response, metadata, timing, and
hashes are stored one file per call with an append-only event journal.

## Preregistered interpretation

The smoke is **VALID** only if all deterministic prechecks pass, all 20 calls are
attempted once and durably recorded under identical frozen settings, graders
agree, no prompt truncates, and terminal evidence seals successfully. Model
wrongness or strict-schema failure is a valid condition result, not an apparatus
repair opportunity.

H1 is **SUPPORTED** at smoke scale only if all are true:

- C has at least 16/20 primary passes;
- C is not worse than A or B in primary passes;
- C has at least 4/5 high-support passes;
- C is not worse than A or B on the five high-support cases or on the five
  high-distractor cases;
- C passes at least 3/4 cases in every domain;
- C has zero illegal promotions;
- median paired C input tokens are at most 60% of A;
- median paired C input tokens do not exceed B;
- deterministic codec required-ref recall is 100%;
- at least 4/5 indispensable ablations are detected; and
- at least 4/5 same-case irrelevant-removal controls still pass.

There is no near-threshold rescue category: failure of any preregistered gate is
reported as **NOT_SUPPORTED**, with evidence level **SPECULATIVE** for H1. This
smoke can never establish **PROVEN**. Compression loss is a valid negative
result. A positive result is benchmark-, template-, and model-digest-specific.
The 20 cases come from five generator families and are executed in six batched
calls per condition; they are not 20 independent population replications and no
significance or population-level inference is claimed.

## One-shot command

After the implementation, protocol, case pack, and tests are committed and the
canonical output directory is confirmed absent:

```powershell
python -m kingdom.decompression_test --acknowledge-frozen-smoke
```

The only authorized live output is:

`.hive/benchmarks/decompression_test/smoke-v1-001`

Do not rerun, repair, tune, expand, merge, or launch a larger benchmark before
the smoke evidence has been independently reviewed.

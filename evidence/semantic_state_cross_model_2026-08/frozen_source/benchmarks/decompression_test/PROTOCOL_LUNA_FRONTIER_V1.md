# Hive Luna Compression Frontier v1

Status before inference: separately versioned, preregistered protocol. The
sealed decompression v1, v2, and v2.1 runs and their artifacts are unchanged.

## Question

After a capable solver demonstrates that it can solve every frozen world from
Raw history, how far can the existing compact ledger be reduced before exact
task performance first changes?

This is a compression-frontier experiment, not a claim that compressed state
is superior to Raw, Retrieval, or a larger solver. It does not test learned
compression. Retrieval is deliberately deferred to a later baseline study.

## Frozen inputs

- Case pack: the existing 20 deterministic worlds in `CASE_PACK.json`.
- Pack SHA-256: `73e4684c1889a1e0d0a5f084d1e8b29f0241ce332baa4f6c6c5c92b5688ce2ed`.
- Expanded-world SHA-256: `da81bae7eb4df4f19f045400a1a03e72cb3595f1531288e6f139d01080ca8dc9`.
- Questions, options, case membership, six batches, and the old three-slot
  Latin-square ordering remain unchanged.
- Oracle answers and chronology/authority classifications remain the existing
  deterministic replay results.

## Frozen solver

- Provider/API: OpenAI Responses API.
- Requested model: `gpt-5.6-luna`.
- Reasoning effort: `medium`.
- Maximum output tokens: 2,048, including reasoning tokens.
- Timeout: 900 seconds.
- Service tier: `default`.
- Tools: none.
- Stored response: false.
- Truncation: disabled.
- Reasoning context: current turn only; no previous response or conversation.
- Prompt cache: explicit mode with no breakpoints. Any reported cached or
  cache-write tokens invalidate the apparatus.
- SDK: exactly `openai==3.3.1`.
- One physical generation attempt per call; no retry, repair, salvage,
  fallback, or prompt changes after the first output.
- Output: one strict JSON object containing only an `answers` array, with
  cardinality exactly equal to the current batch and every item constrained to
  `A`, `B`, `C`, `D`, or `INSUFFICIENT`. The single wrapper is mechanical and
  avoids relying on a provider-specific top-level-array allowance.

The returned model identity and returned service tier must be present and
constant throughout the run. The model alias is not treated as a timeless
snapshot; conclusions are scoped to the recorded returned identity and run.

## Stage 1 — Raw capability gate

Run the six frozen batches from full verbose Raw history, producing 20 graded
answers in six physical generation calls.

The gate passes only with:

- 20/20 exact answers, and
- zero illegal state promotions.

An admissible result below that gate is `VALID_RAW_CAPABILITY_FAIL`. Stage 2 is
not run, no Raw-correct subset is selected, and no representation conclusion
is drawn. A request, response, schema, parser, token-accounting, model-identity,
cache, or artifact failure is `INVALID_APPARATUS`.

Raw is temporally earlier than Stage 2 and therefore serves only as a solver
capability gate, not as a contemporaneous superiority baseline.

## Stage 2 — zero-distortion compact frontier

Only after Stage 1 passes, run all three compact levels over the same six
batches: 18 physical generation calls and 60 answers.

| Level | Named columns supplied | Intended removal |
|---|---|---|
| C0 | `ref,effective_t,record_t,kind,authority,status,requires,effects` | Full existing compact ledger |
| C1 | `ref,effective_t,kind,authority,status,requires,effects` | Remove record arrival time; preserve relative array order |
| C2 | `ref,effective_t,requires,effects` | Also remove the complete applicability bundle: kind, authority, status |

Every transformation is a query-blind projection of named columns. It cannot
access questions, options, correct labels, required references, event roles,
or decoy labels. Records are not malformed or silently reindexed: each packet
declares `record_columns`, and deterministic preflight validates every width,
code, reference, time, requirement, and effect.

C0, C1, and C2 inherit the frozen pack's old Raw/Retrieval/Compressed order
slots solely for counterbalancing. Each level occupies first, second, and third
position exactly twice. The prompt and strict output contract are universal;
only the supplied packet columns differ.

All 18 calls run after the gate even if a semantic answer misses, because
single-run accuracy need not be monotone. An apparatus failure still stops the
run immediately.

## Interpretation

Confirmatory interpretation is hierarchical: C0, then C1, then C2. The first
level below 20/20 ends confirmatory inference; later recovery is descriptive.

- `VALID_COMPRESSED_BASELINE_FAIL`: C0 is below 20/20.
- `VALID_FRONTIER_BOUNDARY_C0`: C0 passes and C1 is the first failure, without
  a later full recovery.
- `VALID_FRONTIER_BOUNDARY_C1`: C0/C1 pass and C2 fails.
- `VALID_RIGHT_CENSORED_ALL_PASS`: all three levels are 20/20; a deeper
  frontier remains unmeasured.
- `VALID_NONMONOTONIC_DESCRIPTIVE`: a later level returns to 20/20 after an
  earlier miss.
- `VALID_RAW_CAPABILITY_FAIL`: the Raw solver gate failed.
- `INVALID_APPARATUS`: the fixed experiment did not produce admissible,
  auditable evidence.

Per level, report exact paired case outcomes, family/load identity,
`INSUFFICIENT` responses, chronology/authority errors, illegal promotions,
representation bytes, input/output/reasoning tokens, latency, and physical
generation calls. Do not report p-values or treat the 20 synthetic cases as
independent population samples.

A C0 ceiling supports only this scoped statement: the existing compact packet
preserved usable task information for this pack, solver identity, and protocol.
It does not prove Hive generally, learned abstraction, superiority, or transfer.

## Cost and stopping

The maximum is 24 generation calls. Deterministic preflight serializes each
exact request and uses its UTF-8 byte count as a conservative,
tokenizer-independent upper bound on input tokens:

- Raw request upper bound: 400,000.
- Stage 2 request upper bound: 500,000.
- Output upper bound: `24 × 2,048 = 49,152` tokens.
- Standard Luna prices frozen for this run: $0.20/M input and $1.20/M output.
- Authorized conservative generation ceiling: $0.30.

Actual API usage is authoritative and is recorded per call. The run does not
start unless the protocol implementation and test sources are committed and
byte-identical to HEAD, the exact SDK and API credential are present, the run
directory does not exist, all deterministic checks pass, and the conservative
ceiling remains within $0.30.

Fresh artifact directory:

`.hive/benchmarks/decompression_test/luna-frontier-v1-001`

Every prompt, strict schema, raw response or partial failure, native transport
metadata, decision, token count, latency, error, and file hash is preserved.
Files are created exclusively; there is no resume or overwrite mode.

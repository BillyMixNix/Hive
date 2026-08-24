# Hive Decompression Test — Protocol v2.1 Cardinality Repair

## Predecessor evidence

Protocol v2 is permanently sealed at source commit
`fa8ef0b86aca781604c842d7017a5a3d415ca541` with the result
`INVALID / INCONCLUSIVE_INVALID_SMOKE`. Its evidence directory is
`.hive/benchmarks/decompression_test/smoke-v2-001` and its frozen inventory
SHA-256 is
`92ae30cb6a7cb5b010a221ed34da3a89a5bc0be2de61df525426be73812dc4bc`.
Protocol v2.1 verifies that seal before inference and never modifies it.

## Sole material repair

V2 used one shared constrained-output schema whose array length ranged from
three through five. Four three-case calls therefore produced four legal enum
labels and failed the stricter exact-length parser.

V2.1 keeps the same condition-blind schema builder and the same enum values,
but sets both cardinality bounds to the current frozen batch size:

`minItems == maxItems == expected_count`

The expected counts are four for batches 1–2, three for batches 3–6, and five
for the two ablation calls. The builder takes only the expected count; it does
not receive or inspect the condition.

## Everything else remains frozen

V2.1 preserves Protocol v2's 20 cases, worlds, histories, questions, options,
representations, deterministic codec and retrieval, batch composition, case
order, condition order, ablation roles, complete solver prompts, strict parser,
graders, scoring thresholds, and 20-call budget. It also preserves:

- model: `qwen2.5-coder:7b`
- model digest: `dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364`
- context: 32,768 tokens
- output allowance: 2,048 tokens
- temperature: 0
- seed: 73021
- timeout: 900 seconds
- one physical attempt per call; no retry or repair

The v2 solver-prompt template SHA-256 remains
`fcc8159eb6901aa3d8f1a95531ef007efb4d7a877b76ad01a949609cb88cf058`.

## Decision rule

Any parser failure, wrong cardinality, truncation, retry, transport failure,
missing evidence, altered predecessor seal, changed prompt/input, mismatched
runtime, or evidence-integrity failure makes the smoke `INVALID` and stops
protocol repair. No live output may be salvaged or used to tune another run.

If all protocol-defined responses are admitted, the already frozen v2 graders
and support thresholds evaluate the decompression hypothesis. A valid result in
which all three primary conditions remain near chance or show widespread
chronology/authority failures is evidence that this frozen model/benchmark
pairing lacks sufficient solver capability; it is not grounds for another
interface revision.

## One-shot command

After committing the implementation and passing the deterministic suite, run
exactly once:

```bash
python -B -m kingdom.decompression_test_v2 --acknowledge-frozen-smoke-v2-1
```

The fresh canonical output is
`.hive/benchmarks/decompression_test/smoke-v2-1-001`.


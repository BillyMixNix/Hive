# Hive Decompression Test — Protocol v2

Protocol v1 is sealed at
`f0023177cd8036750c21aaaa957cc073ab3699f3` with result
`VALID / NOT_SUPPORTED`. V2 verifies the complete 47-file v1 artifact inventory
before inference and never edits, reruns, repairs, or retro-grades it.

## Purpose

V2 changes only the shared answer interface so the frozen benchmark can test:

> Given different representations of the same world, can the model recover the
> correct task-relevant meaning?

The 20 cases, worlds, event order, questions, options, Raw/Retrieval/Compressed
representations, codec, retrieval, ablations, batches, condition order, model,
digest, settings, thresholds, one-attempt rule, and 20-call budget are unchanged.
Every semantic `INPUT:` payload is byte-identical to v1.

## Minimal answer contract

V1 batches 3–5 cases per physical call. Preserving its 20-call budget therefore
requires a positional array; unbatching would require 70 calls. Each case emits
exactly one value from:

`A`, `B`, `C`, `D`, `INSUFFICIENT`

Example three-case response: `["A","C","INSUFFICIENT"]`.

Ollama receives one shared JSON Schema through the top-level `format` field:
an array of 3–5 strings whose items use only that five-value enum. A strict
post-parser enforces the exact expected batch length and literal syntax. It
allows only JSON spaces/tabs/newlines and rejects fences, prose, answer text,
escaped labels, combined labels, objects, wrong lengths, and trailing content.
There is no recovery, repair, retry, or partial salvage.

The model no longer emits case IDs, event references, claim IDs, reasoning
codes, promotion labels, schema versions, or other bookkeeping.

## Grading and reporting

Two deterministic graders must agree: the frozen answer key and an independent
world replay mapped back to its unique option label. If parsing prevents them
from running, v2 records `grader_status: not_run` and
`grader_agreement: null`. This fixes v1's reporting defect without changing v1.

For an admitted A–D label, the selected option maps uniquely to its frozen
truth class:

- current: no chronology/authority error;
- historical: superseded-state chronology error;
- planned: planned state promoted as current;
- hallucinated: unsupported state promoted as current.

Any non-current selection counts as one illegal promotion, matching v1's
definition. `INSUFFICIENT` promotes no state and is marked not assessable for
chronology/authority. These are outcome diagnostics, not a claimed model trace.
A secondary diagnostic failure cannot overwrite primary answer correctness.

## Frozen runtime and validity

- Model: `qwen2.5-coder:7b`
- Digest: `dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364`
- `num_ctx=32768`, `num_predict=2048`, temperature `0`, seed `73021`
- Timeout: 900 seconds; attempts: exactly one; calls: exactly 20
- Calls: Raw 6, Retrieval 6, Compressed 6, Ablation 2
- Model judges: none

The smoke is `INVALID` if the v1 seal, frozen inputs, source binding, model,
settings, schema, call/order/count, transport metadata, or evidence files differ;
if any call retries, times out, truncates, or fails; if constrained output is
outside the exact grammar; or if deterministic graders disagree. An admitted
wrong label is a valid negative result.

`SUPPORTED` requires every frozen v1 hypothesis threshold to pass using exact
label correctness. Otherwise a valid run is `NOT_SUPPORTED / SPECULATIVE`.
No result is broadly PROVEN.

## One-shot command

```powershell
python -m kingdom.decompression_test_v2 --acknowledge-frozen-smoke-v2
```

The only live output is
`.hive/benchmarks/decompression_test/smoke-v2-001`; it must be fresh. Do not
rerun, tune, expand, merge, or start a larger benchmark after this smoke.

# Hive Luna Compression Frontier v1.1 — Completion Repair

Protocol v1 and executions `v1-001` and `v1-002` are sealed permanent evidence.
This is a separately versioned execution protocol whose sole purpose is to
complete the frozen 24-call comparison after `v1-002` stopped when C2 exhausted
the 2,048-token output allowance.

Everything remains frozen from v1: the 20-case pack and hashes, expanded worlds,
questions, options, batches, condition order, prompts, strict answer schema,
model (`gpt-5.6-luna`), medium reasoning effort, current-turn isolation, default
service tier, SDK `openai==3.3.1`, no tools, no cache, no storage, no retry, one
physical attempt per call, graders, scoring hierarchy, and artifact rules.

## Material changes

1. `max_output_tokens` is 4,096 for every Raw, C0, C1, and C2 call instead of
   2,048. The conservative 24-call ceiling remains below the already frozen
   $0.30 authorization.
2. An OpenAI response is a scored solver-budget failure only when all native
   metadata is coherent and its exact state is `incomplete` with reason
   `max_output_tokens`. No partial output is parsed, repaired, or salvaged.
   Every unanswered case in that physical batch is scored incorrect and
   inadmissible, the raw response and usage are preserved, and the remaining
   frozen calls continue.

Any other transport failure, timeout, response error, identity drift, cache use,
token-accounting defect, malformed structured output, parser failure, grader
failure, or evidence failure remains `INVALID_APPARATUS` and stops immediately.

The Raw capability gate remains first. If Raw is below 20/20 or has an illegal
promotion—including through a scored budget exhaustion—the frontier is not run.
After a passing Raw gate, all 18 frontier calls run unless a genuine apparatus
failure occurs. Confirmation remains hierarchical C0 → C1 → C2.

Fresh artifact directory:

`.hive/benchmarks/decompression_test/luna-frontier-v1-1-001`

No v1 artifact may be modified, resumed, overwritten, or reinterpreted.

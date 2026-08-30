# Luna/Sol × Raw/C1 Factorial — Protocol v1.1 Clean Restart

Protocol v1 is permanently sealed as `INVALID_APPARATUS` at evidence commit
`a76e28031321a2b5d255b7df39d0d4db425fce22`. It stopped fail-closed on global
call 22 after a pre-response provider connection error. Its 21 completed
outputs are excluded from v1.1 and must not be resumed, repaired, regraded, or
combined with this run.

The sealed set of 21 v1 provider response IDs is bound by SHA-256
`bf783f69a5349a5e4155fe5f37098eb5ac3921cf7341e9674e18b016fae1fc19`.
Every v1.1 response ID must be disjoint from that set. A collision is rejected
before parsing or grading, preserved as a metadata-rejected physical call, and
stops the run without retry. The independent verifier enforces the same rule.

## Sole material change

Protocol v1.1 is one fresh physical realization of the already frozen v1
experiment. The only material changes are:

- protocol version and identifier;
- fresh immutable run directory;
- source/evidence lineage to the sealed v1 apparatus failure;
- new stochastic model responses generated from physical call 1.

No hypothesis-bearing content or inference rule changes. In particular, v1.1
preserves byte-for-byte or value-for-value:

- the same frozen 20 worlds, questions, answer options, oracle, and graders;
- `LUNA_RAW`, `LUNA_C1`, `SOL_RAW`, and `SOL_C1`;
- all Raw and C1 representations and all solver prompts;
- the same six batches, batch membership, and within-batch case order;
- the same eight replications and 192-call Williams-counterbalanced schedule;
- `gpt-5.6-luna` and `gpt-5.6-sol`, medium reasoning, 16,384 output allowance,
  default service tier, current-turn isolation, and strict structured output;
- no tools, storage, previous-response carry-over, repair, fallback, or retry;
- one physical attempt per scheduled call and fail-closed parsing;
- the exact three confirmatory replication-level sign-flip comparisons, Holm
  family, secondary contrasts, capability gates, and claim boundaries;
- the `$55` per-run conservative ceiling under the Pilot's `$100` cumulative
  authorization.

All 35 inherited runtime/protocol/test source blobs must equal the hashes in
the sealed v1 PRECHECK. Their canonical hash-map digest is
`d976efc02d00423b70bb35a485f8ccd63051005cf3bc6b92f4d486484702e599`.
Only the v1.1 wrapper, protocol, and test are new source entries.

The frozen schedule hash remains
`602971f9978975546ba35c90d3b2b43ac47e4ce0ddf884093c68587f80d31547`.
The frozen request-plan hash remains
`697f0f74d62364101401f3ed2e4e7b6f458c1bb2c6ff82449eb3cdc034b447bb`.
The conservative v1.1 bound remains `$50.8121664`; combined with v1's actual
`$0.4159628`, the cumulative worst case is `$51.2281292`, below `$100`.

## Execution and failure rule

The fresh directory is:

`.hive/benchmarks/decompression_test/luna-sol-raw-c1-factorial-v1-1-001`

It must not exist before inference. Execution starts at global call 1. No v1
response, response ID, score, or usage record may be imported. The run is
sequential and may execute once only after implementation and this protocol
are committed and all deterministic tests/audits pass.

There is still no retry or resume. Any transport, metadata, parser, source,
identity, token-accounting, or provider failure stops v1.1 immediately and
seals `INVALID_APPARATUS`. A new failure is evidence about the apparatus, not
permission to patch or continue this run.

If all 192 calls complete, the inherited v1 verifier independently reparses,
regrades, recomputes usage and all statistics, and checks exact model/service
identity before accepting a valid result. No conclusion extends beyond the
fixed benchmark, representations, solvers, and settings.

# Historical worker deadline reconstruction

Read-only reconstruction from immutable FACTORIAL-003R1 requests, streams, transport timestamps, logical-call records and resource snapshots. No historical outcome is rescored. Channel presence, size and timing are measured; reasoning text is not analyzed.

All six used HTTP 200 streaming, qwen3:8b digest `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`, context 12288, worker output cap 6000, temperature 0.1, `truncate:false`; `think` was omitted. The normal total generation deadline was 900 seconds. None has a completed terminal response. Input/output token accounting for these interrupted calls is unknown.

| Cell | Task / replicate | Call | First stream s | First answer s | Thinking characters | Answer characters | Deadline result |
|---|---|---|---:|---:|---:|---:|---|
| 3 | J004 / 1 | initial worker | 15.605 | 861.930775 | 10023 | 414 | incomplete / generation deadline |
| 6 | J003 / 1 | initial worker | 8.821 | none | 12960 | 0 | incomplete / generation deadline |
| 8 | J003 / 2 | initial worker | 8.730 | none | 13250 | 0 | incomplete / generation deadline |
| 9 | J002 / 2 | initial worker | 8.441 | none | 11425 | 0 | incomplete / generation deadline |
| 12 | J004 / 2 | initial worker | 14.605 | 879.827378 | 11674 | 206 | incomplete / generation deadline |
| 15 | J002 / 1 | targeted correction | 13.291 | none | 10119 | 0 | incomplete / generation deadline |

Provider-created chunk timestamps support channel latency estimates, not exact host receipt timestamps. Counts above are characters, not tokens. Raw request hashes, provider errors, per-snapshot host/virtual/GPU memory, residency and evidence paths are in `evidence/historical-calls.json`.

**Denominator distinction:** the selected failed calls completed 0/6. Five are initial-worker calls. Cell 15 is a correction timeout after a completed initial worker, executable edit and frozen behavioral FAIL. Historical cohort-level any-worker response and executable edit are therefore 1/6, targeted verification 1/6, frozen acceptance and full-gate success 0/6. The prospective experiment runs whole fresh cells and may follow different call paths.

## Exact request identities

- Cell 3: `000b9ea96c9f714c53446ebe0ee419bc355023b667163005f95cb0cf9c6f9f26`; [091f5b539b27](C:/Users/billy/Documents/Codex/2026-10-05/hive-transition-001-diagnose-and-repair/HIVE-FACTORIAL-003R1/evidence/trials/03-J004-r1-qwen3_8b/runtime/calls/02-backend/attempt-01/wire-request.json); frontier `worker`.

- Cell 6: `1395e2cbffec5f2b1d05831f076260a6a864a112654920a2c64772616d97473e`; [020474252273](C:/Users/billy/Documents/Codex/2026-10-05/hive-transition-001-diagnose-and-repair/HIVE-FACTORIAL-003R1/evidence/trials/06-J003-r1-qwen3_8b/runtime/calls/02-backend/attempt-01/wire-request.json); frontier `worker`.

- Cell 8: `cb2b57f7826a6a0a1d967da29455fa9984b1270922bf500601d39db419d808f7`; [0a4eefcf31ea](C:/Users/billy/Documents/Codex/2026-10-05/hive-transition-001-diagnose-and-repair/HIVE-FACTORIAL-003R1/evidence/trials/08-J003-r2-qwen3_8b/runtime/calls/02-backend/attempt-01/wire-request.json); frontier `worker`.

- Cell 9: `02a79782d963f3d9a1fcd203d58b5710811959d2c2ca7283ac374931e9308116`; [01468d2feb5c](C:/Users/billy/Documents/Codex/2026-10-05/hive-transition-001-diagnose-and-repair/HIVE-FACTORIAL-003R1/evidence/trials/09-J002-r2-qwen3_8b/runtime/calls/02-backend/attempt-01/wire-request.json); frontier `worker`.

- Cell 12: `e5e4f1cfbab17edbaadf32086ad2feeeb2e5d9356fc89ad3094533991252bc24`; [503f0681c29b](C:/Users/billy/Documents/Codex/2026-10-05/hive-transition-001-diagnose-and-repair/HIVE-FACTORIAL-003R1/evidence/trials/12-J004-r2-qwen3_8b/runtime/calls/02-backend/attempt-01/wire-request.json); frontier `worker`.

- Cell 15: `dce149cf9bb9891a0d9565ff1b4ce966089b429cd5444e84f4a793b447a7f71a`; [d3aa14443918](C:/Users/billy/Documents/Codex/2026-10-05/hive-transition-001-diagnose-and-repair/HIVE-FACTORIAL-003R1/evidence/trials/15-J002-r1-qwen3_8b/runtime/calls/03-backend/attempt-01/wire-request.json); frontier `worker_correction`.

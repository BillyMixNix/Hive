# Hive Experiment 2 — Semantic Authority Decomposition Protocol v1.2

Protocol v1.1 is sealed `INVALID_APPARATUS` at
`b5ec200dec75ff60aa930b0dc0df18e136efcb62`; it stopped after 35 physical calls
when one Luna response ended `incomplete`. Protocol v1.2 is separately versioned.

Identity: `hive-luna-semantic-authority-decomposition-v1-2`  
Version: `1.2`  
Run: `.hive/benchmarks/decompression_test/luna-semantic-authority-decomposition-v1-2-001`  
Acknowledgement: `--acknowledge-frozen-semantic-authority-decomposition-v1-2`

## Frozen changes only

1. Luna medium reasoning receives `max_output_tokens=16384`.
2. A recognized incomplete response, strict-parser rejection, timeout, network
   failure, HTTP 5xx, or explicitly transient/rate-limit HTTP 429 is preserved as
   a failed call and the frozen schedule continues. The call receives one physical
   attempt: no retry, repair, fallback, resume, or salvage. Unknown transport
   failures fail closed.
3. Authentication, permission, quota, billing, admission/metadata, source,
   lineage, schedule, response-identity, artifact-integrity, model/tier,
   token/attempt/configuration, deterministic-grading, or other systemic failures
   abort immediately.
4. Each primary C1-vs-single-field hypothesis runs only if all eight complete
   20-world matched replication pairs exist for that hypothesis. Missing pairs
   are excluded and flagged; they are never imputed. Each primary and secondary
   comparison is scoped independently to its frozen required conditions. Missing
   data in one comparison cannot erase or alter another complete comparison.
5. Every nonempty provider response ID, including an incomplete or otherwise
   failed response, participates in one run-global uniqueness check. A true
   no-response failure may omit the ID.
6. The independent verifier replays the complete 384-call schedule, reparses and
   regrades successful calls, reclassifies isolated failures, checks response-ID
   uniqueness and matched-data disposition, and rejects missing tail calls,
   salvaged scores, or stored-result drift.

Everything else—worlds, prompts, representations, conditions, projections,
ordering, model, medium effort, schema, one-attempt policy, estimand, exact test,
Holm primary family, thresholds, and claim ceiling—is unchanged.

Frozen derived values:

- solver config SHA-256: `0fa9c5f438388516fd4ac130c44320f08cafb7bddbad6e102444326c56a04b54`
- request-plan SHA-256: `93c985e268921314687da40830d82d4d016720c2b5c8d9567beff1639b6ae5f2`
- conservative input bound: `10092160`
- output bound: `6291456`
- conservative cost bound: `$9.5681792` under the unchanged `$100` ceiling

Sealed v1.1 bindings:

- evidence subtree: `49221942851f4cf173c292af018cbd0e72ff86b2`
- RESULT SHA-256: `ec42f58aed89513bca3294a33a504d38b02dc9b6eb34d7c0bb39a3e1cf2f21aa`
- INDEX SHA-256: `5c9cfb45ca7a58210633f7fc73d180b4aa757eff04f49df5909792b839f7e707`

Implementation must be committed before the one authorized live run. The fresh
directory must not exist. Any failure is evidence and is not repaired in place.

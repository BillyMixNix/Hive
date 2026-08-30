# Semantic-state cross-model evidence bundle (2026-08)

This directory is the public, byte-preserving evidence bundle for Hive's sealed
Raw-vs-C1 cross-model benchmark. It mirrors the valid 192-call run and preserves
the preceding INVALID attempt separately. It does not make model calls.

## Verify in one command

From the repository root:

```console
python evidence/semantic_state_cross_model_2026-08/verify.py
```

The verifier uses only Python's standard library. It fails closed on a missing,
extra, or changed published file; checks every sealed index entry; checks all
request, raw-response, decision, usage, schedule, and response-identity records;
recomputes the condition summaries and preregistered sign-flip statistics; and
compares that reconstruction with `PUBLISHED_SUMMARY.json`. It never imports the
live experiment runner and has no inference path.

## Bundle map

- `valid_run/` — byte-for-byte copy of the sealed v1.1 run: protocol/config,
  precheck, 192 exact requests and raw responses, 192 grading decisions, four
  append-only event logs, usage/cost accounting, statistics, result, and index.
- `invalid_first_attempt/` — byte-for-byte public subset of the sealed v1
  apparatus-failure run: 21 completed responses and decisions plus its protocol,
  precheck, logs, result, status, manifest, and evidence index.
- `PRIVACY_OMISSION.json` — hash-bound record for the one INVALID failure envelope
  withheld from the public mirror because its traceback contains an absolute
  workstation path. The original sealed artifact remains unchanged.
- `FROZEN_PROTOCOL.md` — exact protocol document recorded by the valid run.
- `CASE_PACK.json` — exact frozen 20-case pack recorded by the valid run.
- `frozen_source/` — the complete 38-file source snapshot whose hashes are
  recorded in the valid precheck, including projection, grading, runner, tests,
  case pack, and protocol lineage.
- `PUBLISHED_SUMMARY.json` — concise summary independently reproduced by the
  verifier.
- `PROVENANCE.json` — source directories, commit lineage, and canonical hashes.
- `PUBLIC_MANIFEST.json` — byte length and SHA-256 for every published file other
  than the manifest itself.
- `VERIFIER_OUTPUT.txt` — reference output from the clean-checkout verification.

The schedule, projection metadata, representation sizes and hashes, exact solver
configurations, pricing assumptions, and request plan are in
`valid_run/PRECHECK.json`. Each `*/calls/call_*.json` contains the exact prompt
and projected state payload, strict output schema, raw response, provider
metadata, tokens, and latency. Matching
`*/decisions/decision_*.json` files contain deterministic grading.

## Result and claim boundary

The valid run completed 192 physical calls with 192 unique response IDs and no
retry, repair, fallback, tool, storage, or cross-call reasoning. Observed correct
counts were 156/160 for both Luna conditions and 160/160 for both Sol conditions.
C1 used 81.1% fewer serialized state bytes, 58.0% fewer provider input tokens,
and 54–57% lower estimated generation cost under the frozen token-pricing
assumptions than Raw within the same solver.

The preregistered representation contrasts returned `p = 1.0`. This is not an
equivalence test. The licensed statement is limited to this engineered C1
representation, frozen synthetic benchmark, model identities, and serving-cost
estimation. It does not establish production savings, formal equivalence,
learned compression, arbitrary-history safety, or general model substitution.

## Sealed source

The canonical source locations and commit lineage are recorded in
`PROVENANCE.json`. The two requested public identifiers are:

- `RESULT.json`: `83996a1d9da93ff0e36e7ade87d13fc070e0db9a4f5bb14016a575b5c5506eb0`
- `EVIDENCE_INDEX.json`: `24c1de4106c013bed070d7004ebe0a5a15cb04430831e54a5e1efaa8a6b3718f`

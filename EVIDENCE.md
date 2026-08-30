# Hive evidence summary

This document is the public claim boundary for the current Hive semantic-state result.

## Strongest supported claim

On a **sealed synthetic benchmark**, Hive's engineered C1 semantic-state representation used materially less supplied context while preserving the same aggregate observed correct counts as Raw within each tested solver arm.

### Four-arm result

| Condition | Correct | State bytes / 20-world representation | Input tokens | Estimated generation cost |
|---|---:|---:|---:|---:|
| Luna · Raw | 156 / 160 | 171,606 | 665,816 | $0.1370 |
| Luna · C1 | 156 / 160 | 32,482 | 279,432 | $0.0629 |
| Sol · Raw | 160 / 160 | 171,606 | 665,816 | $2.6841 |
| Sol · C1 | 160 / 160 | 32,482 | 279,432 | $1.1478 |

Relative to Raw, C1 therefore showed:

- **81.1% less supplied-state bytes**,
- **58.0% fewer input tokens**,
- **54–57% lower estimated generation cost under the frozen token-pricing assumptions**,
- and the **same aggregate observed correct count within each tested solver arm**.

The preregistered representation comparisons returned `p = 1.0`: no difference was detected. That is **not** proof of formal or statistical equivalence.

## Evidence quality controls

The valid crossed benchmark recorded:

- **192 physical model calls** with unique response IDs,
- **0 retries, repairs, fallbacks, or carry-over**,
- **393 sealed files verified**,
- 20 fixed worlds,
- 8 replications,
- 4 crossed arms,
- counterbalancing,
- preserved Raw outputs,
- and a clean verifier.

The first live attempt suffered a transport failure and was sealed **INVALID**. The valid result came from a separately versioned clean restart rather than repairing or reusing the failed run.

## Mechanism evidence

A separate semantic-bundle ablation tested whether the representation's labels were merely decorative.

With the full `kind + authority + status` bundle present, the tested arm scored:

- **160 / 160**.

Deleting that bundle together reduced the score to:

- **26 / 160**,
- with **71 illegal promotions**,
- and **68 authority errors**.

A three-way interaction test reported `p = .0078`; Holm-adjusted `p = .0313`.

The matched-size opaque-filler control was valid but **inconclusive** because the filler itself was more damaging than deletion. That control is not being represented as a successful confirmation.

## What this result does NOT prove

Do not read the benchmark as evidence that:

- production savings are already proven,
- C1 is formally equivalent to Raw,
- Hive can replace stronger models,
- the representation is autonomously learned,
- arbitrary histories can already be converted into safe state,
- general causality has been solved,
- or full-lifecycle economics are already positive.

The benchmark measures a frozen synthetic task and estimates model-generation cost from recorded tokens under a frozen pricing schedule. The successful C1 grammar is currently **engineered**, not autonomously learned.

## Full-lifecycle economics remain open

The commercial metric is not token compression by itself. The intended metric is:

> **total dollars per correct task**

A real deployment must charge state extraction, normalization, validation, updates, storage, corrections, retries, escalations, and model calls.

Full-lifecycle production economics are **not yet proven**. The next commercial proof is to run real coding-agent workflows in shadow mode, freeze the accounting rules and quality margin in advance, and identify where Hive wins, where it must escalate, and where Raw should remain the default.

## Sealed artifact identifiers

The current sealed evidence package records these canonical artifact digests:

- `RESULT SHA-256`: `83996A1D9DA93FF0E36E7ADE87D13FC070E0DB9A4F5BB14016A575B5C5506EB0`
- `INDEX SHA-256`: `24C1DE4106C013BED070D7004EBE0A5A15CB04430831E54A5E1EFAA8A6B3718F`

The complete sealed valid run is published in the
[public evidence bundle](evidence/semantic_state_cross_model_2026-08/), including
the protocol/config, frozen source snapshot, schedule, exact requests and
projected state payloads, raw responses, grading, usage/cost records, statistics,
and a fail-closed offline verifier. From the repository root, run:

```console
python -I -B evidence/semantic_state_cross_model_2026-08/verify.py
```

The published bundle manifest has SHA-256
`D9AFC3B58ECC042E8A6A99B7C221CBAEFF566ED39789698395ACB98F096900DE`.
The preceding INVALID transport-failure attempt is preserved as a hash-bound
public subset. Its one omitted failure envelope contained an absolute workstation
path and no semantic model output; `PRIVACY_OMISSION.json` records its exact byte
length and SHA-256. The original sealed artifact remains unchanged.

## Historical evidence in this repository

The repository also preserves earlier reliability and lesson-memory work, including negative results and known blind spots:

- [FINDINGS.md](FINDINGS.md)
- [HIVE_RELIABILITY_REPORT.md](HIVE_RELIABILITY_REPORT.md)
- [RESEARCH_HISTORY.md](RESEARCH_HISTORY.md)

Those studies are part of Hive's research lineage, but they are not substitutes for the current semantic-state benchmark described above.

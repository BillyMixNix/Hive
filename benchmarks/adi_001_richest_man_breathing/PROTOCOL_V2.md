# ADI-001 Protocol v2 — Causal Degradation

## Frozen predecessor evidence

Protocol v1 remains frozen at commit `32e44a66acab25320ac5aa7e508e55018128043a`.
Its Chapter-2 smoke directory is evidence, not a resumable run. It contains exactly:

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `calls.jsonl` | 2,153 | `9b5fb364da1421041ab34a2013967b92907b5f9f8f7931d43cf58009faaf9c47` |
| `manifest.json` | 2,155 | `1510f8634e078bd341173397108ea83ece3b9cd4179cda860b45387d912b80e2` |
| `rejected/baseline/chapter_0002-0a220aedce4a.json` | 10,464 | `eb6c88a5765f437747dc6a41c894f0287da8fca72f77c65ac31b16baf827b650` |

That smoke is a failed/incomplete A/B attempt: the baseline invented an established
apartment, the deterministic guard rejected it, Kingdom did not run, and no winner
exists. Protocol v2 does not alter, resume, reinterpret, or tune against that run.

## Pre-registered purpose

Protocol v2 tests whether Kingdom preserves causality, obligations, progression, and
original intent better than ordinary generation as narrative dependency load grows.
The prediction is a longitudinal difference in degradation rate, not prettier Chapter-2
prose and not a one-chapter preference score.

Both conditions receive the same trustworthy current-versus-future Story Map interface,
the same prior prose tail, the same model and runtime limits, and the same deterministic
promotion authority. The treatment is only how the three matched generation calls use
that shared information.

## Fixed treatment

Each generated chapter receives exactly three generation calls per condition.

Baseline:

1. ordinary causal chapter outline;
2. sequential prose draft;
3. ordinary holistic revision.

Kingdom:

1. dependency/obligation/intent construction plan;
2. prose synthesis;
3. terminal Critical-Path revision.

Both arms consume the same byte-identical canonical writer packet for a given prior
state and chapter. That packet contains labeled static authority, the complete typed
canonical claim ledger, the eligible frontier, locked future intent, and the verified
recent prose tail. Future intent remains visibly non-current and cannot be promoted by
the writer or extractor.

The shared state proposer sees only immutable rules, prior accepted canon, and the final
current chapter. Its output is a proposal. The same deterministic Story Map guard must
accept every promotion using exact chapter-grounded evidence and legal dependencies.
There are no guard-repair calls.

## Fixed runtime

- Model tag: `qwen2.5-coder:7b`
- Model digest: `dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364`
- Ollama context: 32,768 tokens
- Maximum output: 2,048 tokens per call
- Authority-prompt safety ceiling: 60,000 characters; oversize prompts fail rather
  than clipping any Story Map/state bytes
- Temperature: 0.2
- Sampling seed: 42,001
- Timeout: 900 seconds per physical request
- Transport attempts: exactly one; hidden retries disabled
- Generation budget: three calls per chapter per condition
- Condition order: baseline, then Kingdom, for every chapter
- Chapter metrics: one condition-blind judge call per admitted condition per chapter,
  performed only after both branches are admitted
- Pairwise prose preference: none

Input-token totals may differ because the treatments produce different plans and drafts.
The matched claim is calls, model identity, context/output caps, sampling settings, and
transport policy—not identical realized token consumption.
Every successful call must report `done_reason=stop` and positive prompt/output token
counts; the transport preserves missing fields as missing rather than coercing them to
zero. A prompt at or above
`32,768 - 2,048` evaluated tokens is invalidated as possible input truncation, and an
output above 2,048 tokens or a length-stop is invalidated as truncation.

## Evidence preservation

Every physical request gets a pre-request journal event and an immutable call artifact
containing the full prompt, full response or error, hashes, model/runtime settings,
transport metadata, timing, purpose, condition, chapter, and budget class. This applies
equally to generation, state proposals, and metric judges.

Every branch also preserves its plan, draft, final response, normalized prose, every
state proposal and deterministic decision reached, accepted state (if any), and hashes.
A prose-precheck rejection explicitly records that no state proposal was run. Rejected
branches are retained outside canonical history. A run directory is fresh-only and
cannot be resumed, overwritten, repaired, or silently reused.
The CLI accepts exactly one canonical smoke path,
`.hive/benchmarks/adi_001/protocol-v2-smoke-ch2-v2-001`; choosing another path is
rejected as an unregistered retry. A later independent replication requires a new
pre-registered protocol identity rather than a renamed directory.

Before creating the run directory, the launcher verifies every protocol source and
input is tracked and Git-filter-equivalent to the reported revision (so Windows line
endings cannot create a false mismatch). It also re-verifies
the exact three-file Protocol-v1 evidence seal above and refuses an output path inside
that sealed directory.

## Stop and smoke rules

A Chapter-2 branch is admissible only if both its final prose and proposed state pass the
shared deterministic authority. If either branch is rejected, Protocol v2 stops
immediately, records the exact rejection, and reports an inconclusive symmetric smoke.
It does not run a repair call, continue the other branch, declare a winner, or tune and
retry under the same protocol identity.

The smoke passes only if baseline and Kingdom independently produce admissible Chapter-2
prose and state, and both condition-blind metric outputs validate. Passing is apparatus
qualification only; it is not evidence that Kingdom is superior.

A syntactically or structurally invalid state proposal is a rejected branch with zero
counted illegal promotions; a proposal rejected by the deterministic promotion guard is
a rejected branch with one illegal-promotion event. Transport, audit, persistence,
context-limit, and internal failures are apparatus failures, never branch evidence.

The ten-chapter longitudinal experiment remains prohibited until this symmetric smoke
passes and Chapters 3–10 have separately reviewed frontier and guard coverage.
The already-frozen runner requires the passing smoke's hash-verified `RUN_STATUS.json`
via `--smoke-qualification-file` for any request beyond Chapter 2. The qualification
must show both arms admitted, exactly ten physical calls, no winner, the fixed model
digest, and the same prompt-template hashes. Its source bindings must also match every
later runtime/code/seed/contract/protocol byte. The only permitted post-smoke source
change is separately reviewed Chapter 3–10 coverage inside `STORY_MAP.json`; all prompt,
guard, audit, metric, transport, seed, contract, and protocol-document hashes remain
identical. A frozen-core Story Map hash binds every non-coverage field plus all Chapter-2
frontier, lock, forbidden-pattern, and opening rules; the exception can only add
Chapter-3-and-later entries to those four coverage maps. Qualification also re-hashes
all ten immutable smoke call artifacts rather than trusting their index alone.

## Longitudinal metrics

For each admitted branch and chapter, Protocol v2 records:

- continuity violations, split into factual contradictions, causal-prerequisite
  failures, and obligation failures;
- illegal state promotions (deterministic guard authority);
- unresolved/open obligations as dependency load (not automatically an error);
- progression/economic errors;
- intent-drift severity;
- residual repair burden still present in the final chapter;
- deterministic draft-to-final change as a separate diagnostic that is not included in
  degradation;
- a pre-declared chapter degradation index; and
- the least-squares chapter-by-chapter degradation slope once two or more chapters exist.

Positive slope means error burden is worsening with narrative length. The eventual
hypothesis test compares the conditions' slopes and trajectories. A single Chapter-2
score, automatic judge opinion, or prose preference cannot establish the claim.

Open obligations are excluded from the degradation index. A contradicted, falsely
resolved, or due-and-forgotten obligation is instead counted as a continuity violation.
The first branch rejection is a primary terminal endpoint. Any slope is computed only
over completed paired admitted chapters before that endpoint and is labeled
survivor-only/censored; a rejection or unattempted arm is never converted to zero error.

## Exact Chapter-2 smoke command

Run from the repository root only after the Protocol-v2 implementation is committed and
the focused and full test results have been reported:

```bash
python -m kingdom.webnovel_benchmark_v2 \
  --seed-file benchmarks/adi_001_richest_man_breathing/SEED.md \
  --benchmark-file benchmarks/adi_001_richest_man_breathing/CONTRACT.md \
  --story-map-file benchmarks/adi_001_richest_man_breathing/STORY_MAP.json \
  --protocol-file benchmarks/adi_001_richest_man_breathing/PROTOCOL_V2.md \
  --output-dir .hive/benchmarks/adi_001/protocol-v2-smoke-ch2-v2-001 \
  --chapters 2 \
  --model qwen2.5-coder:7b
```

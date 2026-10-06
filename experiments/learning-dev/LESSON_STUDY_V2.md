# Prospective retained-lesson transfer study — 2026-09-08

Goal: test whether a lesson derived by Hive from its own actual debugging experience improves a fixed model's subsequent repairs. The preceding six live episodes verified infrastructure, not a learning gain. Their cumulative conservative API charge bound, $0.026646, carries into the original $5 total allowance.

## Frozen design

The versioned JSON contains 92 authored Python projects in six defect families: stale current inputs, sorting associated data, incomplete cache keys, aliased snapshots, explicit zero values, and single-use iterators. Each family has one formation project, two development projects, and twelve confirmation projects. Two additional projects test retention of inclusive-boundary repair. Several structural variants appear within each family. All originals were independently checked to fail, and all evaluator-only reference repairs to pass, before paid study work.

The model is `gpt-5.6-luna` throughout. Each recipient gets a fresh workspace and at most 36 model requests, the same original Hive executive, the same native action bridge, and the same deterministic acceptance callback. Public tests expose a reproducible failure. Acceptance checks and independent final grading run outside the worker workspace; their test bodies and reference solutions are never sent to the worker or lesson proposer. Candidate source is recorded before final grading. A success requires both Hive's SATISFIED decision and an independent protected-test pass. A blocked repair is a failure; broken evaluation integrity invalidates confirmation.

Formation runs each of the six formation projects without guidance, then makes one model request to derive that family's lesson from the actual public source, observed tools and candidate repair. The proposer sees neither protected grading nor reference repairs. Lessons are saved in `study-state.json` and carried by hash into fresh cloud processes. No human edits the generated lesson. Existing ordinary Jarvis guidance is not silently replaced by a candidate study lesson.

Each development project runs in three arms: no lesson, its family lesson, and archival neutral text matched to the lesson's per-field word count. Neutral text is not exactly tokenizer-matched; measured input/output tokens are retained. All actions and model usage are logged. Order is shuffled with the committed seed plus phase index.

Screen 1 selects a family with a lesson success and both controls failing (accuracy endpoint), or, if none, all three succeeding with at least 15% fewer model calls for the lesson against each control (model-call endpoint). Accuracy takes priority; ties use lexical family order. If there is no signal, one refinement uses only formation and baseline public development records, then screen 2 runs the separate development projects. There are at most two development rounds. No selection means this protocol does not enter confirmation.

Before confirmation, the family, endpoint and exact lesson hash are frozen. Twelve previously unpresented projects from that family run in all three arms. Confirmation has three fixed batches of four triplets; the last also runs both retention triplets. All batches must finish. There is one confirmation attempt under this protocol; no stopping after favorable interim results, repeated confirmation or post hoc endpoint switching.

## Decision rule

Accuracy requires at least 1/6 absolute improvement and an exact one-sided paired sign/McNemar p-value at most .025 against **each** control. Model-call efficiency requires every transfer repair in all three arms to succeed, at least 15% fewer mean model calls, and the paired sign p-value at most .025 against **each** control. Ties do not count as discordant pairs. Both retention projects must succeed with the lesson. Missing/duplicate trials cannot confirm; compromised integrity invalidates the study. These rules are implemented in `assess_confirmation` before the first paid request.

The efficiency endpoint measures model calls, not dollar savings. Tokens, conservative charges, and lesson-formation/refinement overhead are reported separately. A shorter trajectory can still cost more tokens. The full-context spending reservation stops new requests before exceeding the original $5 allowance and does not permit automatic retries after transport failure.

## Interpretation limits

A confirmed result is conditional evidence that this retained guidance improves Hive's fixed-model performance on this authored family. Template relatives are a narrow near-transfer test, not a representative sample of real repositories or proof of open-ended recursive self-improvement. The study changes model inputs; it does not train model weights. Model service variation is possible; arm order is randomized and all requests use the same alias and settings. Every negative result and development selection remains visible. If confirmation fails, report that failure; never relabel it proof.

The preflight report preserves the hash of the protocol as executed during offline validation. A later pre-launch wording correction changed “cost reduction” to “model-call reduction” without altering any task bytes. Its separate `validated_cases_sha256` binds the cases actually validated to the final protocol.

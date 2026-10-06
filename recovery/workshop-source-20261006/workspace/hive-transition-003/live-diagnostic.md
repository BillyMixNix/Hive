# Exactly one live diagnostic — HIVE-TRANSITION-003

Run **45ad10e6dd49**, J001, qwen2.5-coder:14b, frozen M3.2 baseline, sole authorized SnapshotFormatter.java write, original frozen gates. The exclusive [invocation marker](evidence/J001-LIVE-STARTED.json) and [FREEZE](FREEZE.json) prohibit a second trial. Final [raw result](evidence/live-diagnostic/raw_results.json): **MODEL_TASK_FAILURE**, rejected, unpromoted, 860.924 seconds, four model calls. This is a transition improvement, not a software-task success.

## Observed sequence

1. **Planner first attempt accepted.** Backend owns the sole file. UI/tests have exact `no change needed`, empty files/criteria and are skipped. No interface contract is needed. No planner correction or structural repair occurs.
2. **Backend dispatched.** Entire baseline owned-file text, including boundLine and its constant, is present in its request. No observations are requested.
3. **Worker returns an implemented replacement.** Its exact `find` string exists uniquely, ownership/preflight pass, and Hive applies the replacement in the private stage. A read-only observation while verifier container `hive-verify-4993c0baef72` ran preserves the [applied file](evidence/live-stage-observation/first-applied-SnapshotFormatter.java), [diff](evidence/live-stage-observation/first-applied.patch), [timestamp/hashes](evidence/live-stage-observation/observation.json).
4. **Targeted deterministic verifier invoked.** It times out at the existing 240-second limit. The only returned check is `isolated_verifier`, failed, `Isolated verification timed out after 240s.` The timeout branch of `hive_verifier.run_isolated` removes the container and returns that failure; it does not preserve intermediate stdout or identify which internal preparation/build/test phase stalled. Therefore individual JUnit execution is **unknown**, not a frozen acceptance failure result or pass.
5. **Rollback and normal correction.** Hive restores the original file and issues its one normal targeted correction with the timeout diagnostic. The worker returns the exact same response, SHA-256 `a2fded0246029a6474288c6f728df1a92bdb30430c15b5e64c5dcc35de048817`. The unchanged `RepeatedFailedProposal` guard rejects it before a second edit/verification attempt.
6. **Containment holds.** Full gate is explicitly skipped for failed prerequisites. Reviewer rejects. Final changed_files=[], diff empty, applied=false; stage file restored and external candidate tree hash equals frozen baseline `230340980b85d60b7a59d3aa338dffc4447c1bb7d8df90bff4d0dbe89afe5388`.

The coarse legacy result label is MODEL_TASK_FAILURE. The causal trace is more specific: the first post-edit obstacle is a local verifier timeout, followed by an unchanged correction. This run cannot determine the verifier's stalled internal phase or certify the proposed implementation.

## Request control and source grounding

The first request equals TRANSITION-002's first completed request in **every parsed body field except `format`**: same messages, model, sampling/output options, context and truncation controls. The user-prompt hash remains `7ea130b272dc13aa728dabf58309babc66fc399f77826a779079ba74a9c41958`. This isolates the intended schema intervention; model sampling was not seeded and one observation does not estimate reliability.

All calls used context 12288, truncate=false, temperature 0.1. Post-run render-only/tokenizer inspection performed **no additional generation**. Every returned object satisfies its actual transmitted schema. [Measurements](evidence/live-input-measurements.json):

| Call | Role | Rendered/provider input tokens | Output cap | Remaining after full output cap |
|---|---|---:|---:|---:|
| 01 | planner | 3834 / 3834 | 2048 | 6406 |
| 02 | backend | 5512 / 5512 | 6000 | 776 |
| 03 | backend correction | 6007 / 6007 | 6000 | 281 |
| 04 | reviewer | 280 / 280 | 1536 | 10472 |

Entire owned baseline-file text appears in both worker requests. Source grounding and transport fidelity are established to this evidence boundary. However, the exact user requirement “unchanged behavior for ordinary ASCII lines” is present in the planner request and absent from planner-derived worker goal/criteria; the worker prompt contains no ASCII requirement. This is semantic omission in task decomposition, not input truncation. Its effect on this run is not isolated. No additional prompt or acceptance changes were made in response.

## Evidence

- [Machine-readable summary](evidence/live-summary.json), [run](evidence/live-diagnostic/01-J001-r1-qwen2.5-coder-14b-hive/run.json), [calls](evidence/live-diagnostic/01-J001-r1-qwen2.5-coder-14b-hive/calls.json).
- Exact requests, raw outputs, NDJSON terminals, render-only outputs and tokenizer IDs: [planner](evidence/live-diagnostic/wire/01/wire-request.json), [worker](evidence/live-diagnostic/wire/02/wire-request.json), [correction](evidence/live-diagnostic/wire/03/wire-request.json), [reviewer](evidence/live-diagnostic/wire/04/wire-request.json), with neighboring files in each directory.
- [Analysis script](summarize_live.py) reconstructs these observations without generation or verification calls. [Token measurement script](verify_live_input.py) uses only provider render-only and runner tokenization.

Furthest verified transition: **executable scoped edit → targeted deterministic verifier invocation**. No targeted pass, frozen acceptance result, full gate or promoted implementation exists.

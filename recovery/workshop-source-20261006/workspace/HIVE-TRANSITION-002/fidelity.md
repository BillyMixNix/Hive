# Provider and model-visible fidelity

## Evidence levels

**KNOWN SENT:** In the new probes and sole J001 diagnostic, `diagnostic_capture.Recorder.handle_async_request()` saves `request.content` before delegating to the real HTTP transport. It records only this study's local `/api/chat` requests for qwen2.5-coder:14b. Each body is stored byte-for-byte as `wire-request.json`, with endpoint, length and SHA-256 in `transport.json`. No authorization headers, credentials, or unrelated requests are recorded. Root `wire-request.json` is the new J001 first request; subsequent calls are under `evidence/live-diagnostic/wire/`. `TeeStream` saves response NDJSON and completion metadata.

For the prior TRANSITION-001 run, only Python provider arguments were captured. Passing these through that unchanged provider with a fake sender reconstructs its body and HTTPX serialization deterministically; those files are named `reconstructed-wire.json`. They are **not retrospectively captured network packets**. The complete preserved prompt hashes and schema equality support fidelity at the caller boundary.

**PROVIDER-ACCEPTED:** New HTTP statuses, complete response metadata, rendered templates, runtime context, and exact tokenizer counts demonstrate what the provider accepted and accounted for. The short control records 322 input tokens, identical to rendered tokenization. The default long probe sends 5,034 rendered tokens but reports 2,050; only its last two sentinel identifiers are returned correctly. With an explicitly sized window it reports 5,034 and returns all five. With truncation disabled but the original window, it returns a specific HTTP 400 context-size error, with no answer accepted by Hive.

**MODEL-VISIBLE UNKNOWN:** Neither the old recordings nor the public API exposes the actual historical tensor/token sequence after all runner processing. Render-only output precedes the truncation inside the completion adapter. Token accounting plus the installed-version source strongly identifies the reduction, but the saved `inferred-retained-token-ids.json` must not be described as a captured model-visible sequence. Sentinel retrieval corroborates positional availability; it does not prove uniform attention, reasoning sufficiency, or successful use of every retained token. No byte-perfect model-visibility claim is made.

## Mechanism and independent checks

The installed server identifies itself as Ollama 0.34.0. Its loaded process was observed with `-c 4096`, one parallel slot, context shift enabled, and keep=4. The model's metadata states Q4_K_M, qwen2 family, native context 32,768, no BOS insertion, and no model parameter override. Local metadata is preserved in `evidence/model-show.json` and `runtime-version.json`.

Pinned source: [Ollama v0.34.0 completion adapter](https://github.com/ollama/ollama/blob/v0.34.0/llm/llama_server.go), functions `completionPromptForRequest`, `contextShiftPromptLimit`; defaults in [api/types.go](https://github.com/ollama/ollama/blob/v0.34.0/api/types.go). For this text path the oversized-input rule retains the first four tokens and the tail to a limit of `4096 - floor((4096-4)/2) = 2050`. The schema is carried separately. Local copies and hashes are retained under `evidence/upstream/`.

`server.chatPrompt()` preserves the latest user message even when it alone is too long; the subsequent completion adapter performs the token-level shortening. Thus the render-only correction is complete, while its eventual input count is shorter. This explains why comparing only Hive's prompt string or render-only output would miss the defect.

The repeated count is **not just cached-token accounting**: new terminal metadata separately reports `prompt_eval_cached_count=4` and `prompt_eval_count=2050`; the full rendered count is 5,034. The short and sized controls report their full counts. No caller-side clipping, native-context assumption, output reservation, or schema token concatenation is needed to explain it.

The inferred historical correction starts with a system prefix immediately followed by a tail fragment from repository facts. It loses the system/user separator. The task, scope, exact inactive phrase and duplicate-owner correction survive within that tail. The earlier worker's inferred sequence loses the MAX_LINE_CHARS declaration and boundLine signature. These are transport/context defects; whether they explain a particular wrong decision is a separate causal question.

## Limits

Historical server logs for the exact prior calls were not available in the preserved evidence. No claim rests on stale server logs. Current upstream source matches the reported version and predicts the measured behavior; the installed executable's exact build commit was not independently attested. Runtime probes and token accounting supply additional evidence beyond source inspection. Template/tokenizer measurements describe this installed model and runtime, not all future Ollama versions.

## Completed new J001 evidence

The sole run `6b87294fdc72` completed two planner calls. There were three HTTP attempts: initial HTTP 500 during CUDA initialization, byte-identical retry with HTTP 200, then correction with HTTP 200. Both successful calls ended with `done_reason=stop`. Their full rendered token counts and provider input counts match exactly: 3,834 and 4,652. `/api/ps` and runner command line confirm 12,288. All sent task, scope, inactive-role and correction markers survive rendering. Complete source-map and message-boundary preservation are observable at this boundary. No further input loss is evidenced in this run; semantic use of context is not observable from counts alone. The plans still fail exclusive ownership validation.

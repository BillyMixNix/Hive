# Model-runtime readiness — non-task diagnostic

Result: **READY_FOR_BOUNDED_NON_TASK_RESPONSE**.

One logical request used the unchanged TRANSITION-005 provider. It returned a complete diagnostic response in **134.107 seconds**, against the existing **900-second** limit. HTTP attempts: **1**. This is a model-runtime check, not a Hive/J001 trial or evidence of task-solving ability.

## Request and runtime configuration

- Model: `qwen2.5-coder:14b`; digest matched TRANSITION-005 (`9ec8897f747e246e970bc5cfdda85d22f1123dc2e3d34978a010a75968716849`). Q4_K_M, 14.8B.
- Ollama before: `{'version': '0.34.0'}`; after: `{'version': '0.34.0'}`.
- Endpoint: `http://127.0.0.1:11434/api/chat`.
- `num_ctx=12288`, `num_predict=2048`, `temperature=0.1`, `stream=true`, `truncate=false`.
- These are the settings of TRANSITION-005's failed planner request. The 6,000-token worker output cap was not used in that failed request and is not substituted here.
- No new stop sequences, seed, GPU/offload setting, keep-alive override or sampling option was supplied. Existing provider retry behavior is unchanged. Each attempt retains its normal 900-second limit; no timeout was increased.
- The same bounded planner system instruction was retained. Only the diagnostic user prompt and its small JSON response schema differ. The response uses the same structured-output transport mechanism. No task, implementation, candidate or hidden-test content is present in the outbound request.

Exact settings: [configuration](evidence/configuration.json). Exact transmitted bodies, HTTP status/timestamps and response streams: [wire capture](evidence/wire). Model identity and exposed model parameters: [model identity](evidence/model-identity.json). Client environment observations are whitelisted; the running server's complete inherited environment is not exposed by these APIs and was not changed.

Diagnostic prompt:

> This is a non-task model-runtime readiness check. Return exactly one complete JSON object with status equal to ready and marker equal to runtime-check. No software task, code, file operation, or tool use is requested.

## Completion and timing

Parsed response:

```json
{
  "status": "ready",
  "marker": "runtime-check"
}
```

Complete response: **True**. Within the normal limit: **True**. Completion requires a terminal `done=true`, `done_reason=stop`, positive provider token accounting and exactly the requested complete JSON object; partial output is not accepted.

Provider metadata (durations converted from nanoseconds to seconds):

```json
{
  "done_reason": "stop",
  "total_duration": 133.3477115,
  "load_duration": 94.5061786,
  "prompt_eval_count": 76,
  "prompt_eval_duration": 15.321604,
  "eval_count": 18,
  "eval_duration": 23.484294
}
```

The measured provider-call elapsed time includes model loading, prompt processing, generation and any normal retry. The raw terminal metadata is preserved in [result.json](evidence/result.json).

## Model residency

Before `/api/ps` models: **0**. After: **1**.

```json
{
  "before": [],
  "after": [
    {
      "name": "qwen2.5-coder:14b",
      "model": "qwen2.5-coder:14b",
      "size": 11613000169,
      "digest": "9ec8897f747e246e970bc5cfdda85d22f1123dc2e3d34978a010a75968716849",
      "details": {
        "parent_model": "",
        "format": "gguf",
        "family": "qwen2",
        "families": [
          "qwen2"
        ],
        "parameter_size": "14.8B",
        "quantization_level": "Q4_K_M"
      },
      "expires_at": "2026-10-05T12:49:24.6129089-07:00",
      "size_vram": 4074294476,
      "context_length": 12288
    }
  ]
}
```

The requested model was not resident before the request, so this check exercised model loading.

## Host and GPU memory

| Available resource | Before | After |
|---|---:|---:|
| Host free physical RAM (GiB, OS counter) | 7.952 | 0.461 |
| Host free virtual memory (GiB, OS counter) | 5.359 | 0.422 |
| Commit limit minus committed bytes (GiB, performance counter) | 5.332 | 0.422 |

`nvidia-smi` columns: GPU index, name, driver, total MiB, used MiB, free MiB.

```text
Before: 0, NVIDIA GeForce RTX 2060, 610.47, 6144, 2306, 3650
After:  0, NVIDIA GeForce RTX 2060, 610.47, 6144, 5629, 327
```

Exact timestamped OS counters, related runtime-process memory and GPU readings: [before](evidence/before.json), [after](evidence/after.json). Measurements are sequential snapshots, not a simultaneous or peak-memory trace. Dedicated GPU memory is not interchangeable with shared host RAM; the CUDA-host allocation observed previously depends on host memory. No existing processes were stopped, and no Docker, Resource Saver or memory-limit settings were changed by this diagnostic. The OS-reported commit limit increased during loading; this was observed, not configured by the check.

## Provider errors and integrity

```json
{
  "terminal_error": null,
  "http_errors": []
}
```

Hive unchanged: **True**, comparing SHA-256 inventories of **153 files** before and after. The provider was imported read-only with bytecode writing disabled. No Hive code/configuration was edited. All new outputs are in this separate diagnostic directory. No J001 run, verifier invocation, hidden-test inspection, previous-candidate replay, context reduction, model switch or extra sampling occurred.

This short diagnostic does not establish readiness for the much larger planner schema/prompt, a 6,000-token worker output cap, sustained multi-turn work or concurrent verifier memory pressure. It neither rescales nor replaces TRANSITION-005's historical runtime failure.

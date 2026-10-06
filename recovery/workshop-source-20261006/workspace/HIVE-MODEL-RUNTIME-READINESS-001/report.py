import json
from pathlib import Path
from check import HERE,EVIDENCE,sha,save
result=json.loads((EVIDENCE/'result.json').read_text())
config=json.loads((EVIDENCE/'configuration.json').read_text())
before=json.loads((EVIDENCE/'before.json').read_text());after=json.loads((EVIDENCE/'after.json').read_text())
def values(sample):
 h=sample['host_memory']['data']['host']
 return [h['free_physical_kib']/1024**2,h['free_virtual_kib']/1024**2,
  (h['commit_limit_bytes']-h['committed_bytes'])/1024**3,
  sample['gpu_memory']['stdout'].strip(),sample['/api/ps']]
b=values(before);a=values(after)
terminal=result['terminal_metadata'][-1] if result['terminal_metadata'] else {}
duration={k:(v/1e9 if k.endswith('_duration') else v) for k,v in terminal.items()
  if k in ('total_duration','load_duration','prompt_eval_duration','eval_duration','prompt_eval_count','eval_count','done_reason')}
model_before=before.get('/api/ps',{}).get('models',[])
model_after=after.get('/api/ps',{}).get('models',[])
text=f'''# Model-runtime readiness — non-task diagnostic

Result: **{'READY_FOR_BOUNDED_NON_TASK_RESPONSE' if result['ready'] else 'READINESS_NOT_CONFIRMED'}**.

One logical request used the unchanged TRANSITION-005 provider. It {'returned a complete diagnostic response' if result['complete_response'] else 'did not return a confirmed complete diagnostic response'} in **{result['elapsed_provider_seconds']:.3f} seconds**, against the existing **900-second** limit. HTTP attempts: **{result['http_attempts']}**. This is a model-runtime check, not a Hive/J001 trial or evidence of task-solving ability.

## Request and runtime configuration

- Model: `qwen2.5-coder:14b`; digest matched TRANSITION-005 (`9ec8897f747e246e970bc5cfdda85d22f1123dc2e3d34978a010a75968716849`). Q4_K_M, 14.8B.
- Ollama before: `{before['/api/version']}`; after: `{after['/api/version']}`.
- Endpoint: `http://127.0.0.1:11434/api/chat`.
- `num_ctx=12288`, `num_predict=2048`, `temperature=0.1`, `stream=true`, `truncate=false`.
- These are the settings of TRANSITION-005's failed planner request. The 6,000-token worker output cap was not used in that failed request and is not substituted here.
- No new stop sequences, seed, GPU/offload setting, keep-alive override or sampling option was supplied. Existing provider retry behavior is unchanged. Each attempt retains its normal 900-second limit; no timeout was increased.
- The same bounded planner system instruction was retained. Only the diagnostic user prompt and its small JSON response schema differ. The response uses the same structured-output transport mechanism. No task, implementation, candidate or hidden-test content is present in the outbound request.

Exact settings: [configuration](evidence/configuration.json). Exact transmitted bodies, HTTP status/timestamps and response streams: [wire capture](evidence/wire). Model identity and exposed model parameters: [model identity](evidence/model-identity.json). Client environment observations are whitelisted; the running server's complete inherited environment is not exposed by these APIs and was not changed.

Diagnostic prompt:

> {config['prompt']}

## Completion and timing

Parsed response:

```json
{json.dumps(result['parsed_response'],indent=2)}
```

Complete response: **{result['complete_response']}**. Within the normal limit: **{result['within_normal_900_second_limit']}**. Completion requires a terminal `done=true`, `done_reason=stop`, positive provider token accounting and exactly the requested complete JSON object; partial output is not accepted.

Provider metadata (durations converted from nanoseconds to seconds):

```json
{json.dumps(duration,indent=2)}
```

The measured provider-call elapsed time includes model loading, prompt processing, generation and any normal retry. The raw terminal metadata is preserved in [result.json](evidence/result.json).

## Model residency

Before `/api/ps` models: **{len(model_before)}**. After: **{len(model_after)}**.

```json
{json.dumps({'before':model_before,'after':model_after},indent=2)}
```

{'The requested model was not resident before the request, so this check exercised model loading.' if not any(m.get('name')=='qwen2.5-coder:14b' for m in model_before) else 'The model was already resident; this check does not independently prove a cold load.'}

## Host and GPU memory

| Available resource | Before | After |
|---|---:|---:|
| Host free physical RAM (GiB, OS counter) | {b[0]:.3f} | {a[0]:.3f} |
| Host free virtual memory (GiB, OS counter) | {b[1]:.3f} | {a[1]:.3f} |
| Commit limit minus committed bytes (GiB, performance counter) | {b[2]:.3f} | {a[2]:.3f} |

`nvidia-smi` columns: GPU index, name, driver, total MiB, used MiB, free MiB.

```text
Before: {b[3]}
After:  {a[3]}
```

Exact timestamped OS counters, related runtime-process memory and GPU readings: [before](evidence/before.json), [after](evidence/after.json). Measurements are sequential snapshots, not a simultaneous or peak-memory trace. Dedicated GPU memory is not interchangeable with shared host RAM; the CUDA-host allocation observed previously depends on host memory. No existing processes were stopped, and no Docker, Resource Saver or memory-limit settings were changed by this diagnostic. The OS-reported commit limit increased during loading; this was observed, not configured by the check.

## Provider errors and integrity

```json
{json.dumps({'terminal_error':result['provider_error'],'http_errors':result['provider_http_errors']},indent=2)}
```

Hive unchanged: **{result['hive_unchanged']}**, comparing SHA-256 inventories of **{result['hive_files_checked']} files** before and after. The provider was imported read-only with bytecode writing disabled. No Hive code/configuration was edited. All new outputs are in this separate diagnostic directory. No J001 run, verifier invocation, hidden-test inspection, previous-candidate replay, context reduction, model switch or extra sampling occurred.

This short diagnostic does not establish readiness for the much larger planner schema/prompt, a 6,000-token worker output cap, sustained multi-turn work or concurrent verifier memory pressure. It neither rescales nor replaces TRANSITION-005's historical runtime failure.
'''
(HERE/'REPORT.md').write_text(text,encoding='utf-8')
save(EVIDENCE/'delivery-seal.json',{'report_sha256':sha(HERE/'REPORT.md'),
 'files_sha256':{p.name:sha(p) for p in [EVIDENCE/'configuration.json',EVIDENCE/'result.json',EVIDENCE/'before.json',EVIDENCE/'after.json',HERE/'check.py']}})
print('Report written:',HERE/'REPORT.md')

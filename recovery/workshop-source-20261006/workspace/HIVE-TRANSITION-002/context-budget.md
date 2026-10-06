# Context and token budget

Counts below use **the loaded qwen2.5-coder GGUF model's own llama-server `/tokenize` endpoint**, not character estimates or a substitute tokenizer. Ollama 0.34.0's `_debug_render_only` renders the messages without generating an answer. Token IDs, rendered strings, render responses, and measurements are preserved in `evidence/measurements/`; the reproducible procedure is `measure_inputs.py`. The first historical prompt's rendered count exactly matches its original provider count, as does the short sentinel control. This removes the need for approximate tokenizers. New render-only requests are measurements, not historical packet captures or additional J001 candidate trials.

| Quantity | Historical first planner | Historical correction |
|---|---:|---:|
| Intended user text, actual tokens | 3,801 | 4,622 |
| Separate system text | 20 | 20 |
| Chat template overhead | 13 | 13 |
| Total intended/rendered model input | **3,834** | **4,655** |
| Serialized message content after JSON decoding | 3,821 | 4,642 |
| Whole HTTP JSON tokenized as text (NOT model input) | 4,640 | 5,573 |
| Actual HTTP JSON bytes, reconstructed | 20,599 | 24,558 |
| Separate format schema, tokenized for size only | 823 | 823 |
| Active runtime context | 4,096 | 4,096 |
| Requested maximum output (`num_predict`) | 2,048 | 2,048 |
| Space remaining for generation without shortening/shifting | 262 | −559 |
| Runtime-reported input tokens | 3,834 | **2,050** |
| Runtime-reported generated tokens | 262 | 336 |

The HTTP JSON count includes transport keys, escaping, and a separately consumed schema; it must not be mistaken for the model's prompt count. Component counts are standalone tokenizations and can have small boundary-merging differences; here the section totals below match the 3,801-token initial user prompt.

| User-prompt component | Tokens | Start character | Approximate user token offset |
|---|---:|---:|---:|
| Planner preface | 14 | 0 | 0 |
| Repository map, including heading | 2,516 | 61 | 14 |
| Repository-derived facts | 64 | 10,931 | 2,530 |
| Task and its write-scope line | 98 | 11,243 | 2,594 |
| Intent envelope and guidance | 104 | 11,720 | 2,692 |
| Host scope/inactive-role/ownership instructions | 124 | 12,256 | 2,796 |
| Role/action/acceptance instructions | 414 | 12,861 | 2,920 |
| Output example and remaining contract guidance | 467 | 15,141 | 3,334 |
| Additional correction text (second turn only) | **821** | 17,414 | 3,801 |

Source/context thus consumes 2,580 tokens but contains **no Java method body**. The map alone occupies about 66% of the initial user prompt. Acceptance instructions are embedded in task, role, and contract sections; they are not separately added text. The initial prompt and appended correction preserve all the intended facts before runtime truncation.

## Answers to the context questions

- **Larger than configured context?** Initial input alone fits, but input plus maximum output is 5,882. Correction input alone exceeds 4,096 by 559; correction plus maximum output is 6,703. The prior backend prompt is 5,548 input tokens, exceeding the default before any generation; input plus its 6,000 output cap is 11,548.
- **Caller clipping?** None in these planner calls. The unchanged provider builds complete messages; deterministic replay and the new HTTP boundary recorder check exact equality. `raw[:12000]` in correction is a real host bound but the historical raw response is only 1,246 characters. Telemetry limits also do not affect these sent messages.
- **Ollama truncating?** Yes, demonstrated by the long synthetic probe and supported for historical correction by exact token counts and the pinned runtime algorithm. The algorithm's inferred retained sequence is saved separately and explicitly labeled as inferred; it is not a captured historical model input.
- **Output reservation?** Hive sets an output cap, but does not reserve that amount inside `num_ctx`. The aggregate 250,000 ceiling uses a conservative byte allowance and is unrelated to the runtime window. `num_predict=2048` is not the cause of the repeated 2,050 input count; the half-context truncation algorithm is independent of that output cap. The original 262 generated tokens happen to equal the first prompt's remaining space; historical completion metadata is insufficient to establish whether that boundary affected generation.
- **Default window?** Yes. No `num_ctx` in the original serialized body; `/api/show` has no model parameter override; `/api/ps` records 4,096, also corroborated by the runner process `-c 4096`. Native capacity 32,768 does not select itself.
- **Schema/source competition?** The textual schema example and instructions share the prompt window with the map. The separate `format` JSON becomes an output grammar/schema in the runtime; it is not appended as 823 more prompt tokens. Render-only evidence and token counts agree. There is semantic duplication between prose/example and output grammar, but no demonstrated additional schema-to-prompt transport duplication.
- **Correction pressure?** It adds 821 tokens, crosses the default input limit, and triggers loss of 2,605 input tokens. Under the reconstructed truncation rule, the task, hard scope, inactive-role convention and correction feedback remain, while map, most system text and the system/user boundary disappear.

## Measured repair sizing

Hive now requests **12,288**, with `truncate:false`. At the historical sizes this leaves 8,454 after first input, 7,633 after correction input, and 6,740 after the observed worker input. After the unchanged output caps, the corresponding slack is 6,406 / 5,585 / **740**. The selection covers the observed worker plus its full existing output cap, rather than blindly using the model's 32,768 maximum.

An 8,192 context was sufficient for the controlled 5,034-token sentinel plus 2,048 output cap, and returned all five facts with input count 5,034. The 12,288 Hive setting additionally accommodates the measured worker. It does not promise every future source bundle fits. Requests beyond the configured context are rejected explicitly, demonstrated locally by HTTP 400 at `truncate:false`, and tested for both HTTP and streamed error responses. Within-window input that later fills context during very long generation remains a limitation; this repair does not implement a general tokenizer-aware scheduler.

## Sole new J001 trial

Run `6b87294fdc72` reports 3,834 and 4,652 input tokens, exactly matching newly rendered/tokenized requests. The correction is three tokens shorter than the historical correction because the new first response differs; the correction construction is unchanged. Runtime context is 12,288 for both. Full output-cap slack is 6,406 and 5,588 tokens; actual outputs are 259 and 331 tokens. Neither completed turn approaches its context boundary. Details: `evidence/live-input-measurements.json`. The first HTTP attempt failed initialization (500), then the same body succeeded on the provider's existing retry; it has no accepted-input token count.

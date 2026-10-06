# Measurement before repair

No production changes preceded the following evidence:

- Original provider function-argument capture reconstructed through the unchanged provider produces complete messages; no caller prompt clipping.
- Ollama 0.34.0 render-only endpoint plus the loaded qwen2 model tokenizer measures historical first planner 3,834 tokens, correction 4,655, prior backend worker 5,548.
- The pinned runtime's `llm/llama_server.go:completionPromptForRequest` retains first num_keep=4 plus tail on overlong input. `contextShiftPromptLimit(4096,4)=2050`. This matches historical counts and a new synthetic 5,034-token sentinel prompt.
- Short control retrieves all five sentinels. Long default retrieves only late-middle/end correctly. The source algorithm removes the other sentinel facts. No J001 solution was in these probes.
- Sending the same synthetic long prompt with `truncate:false` returns HTTP 400 identifying 5,034 input tokens versus 4,096 available. Oversized input can therefore fail explicitly instead of being shortened silently.

Supported defect: Hive omits context configuration and accepts the runtime's truncation default for oversized structured agent prompts. Not established: this defect caused the duplicate ownership choice. The inferred retained correction still contains task, scope, canonical inactive-role guidance, and duplicate-owner feedback. It loses system/user message boundaries and the map; the prior worker loses the relevant source definition.

Small repair selected: expose an explicit context_window provider argument, set `num_ctx` and `truncate:false` when used; opt Hive calls into 12,288 tokens. This measured bound accommodates the observed worker input (5,548) plus unchanged maximum output (6,000), total 11,548, with 740 tokens of headroom, and both planner inputs plus 2,048 outputs. It is below the model's 32,768 native capacity. Generic chat defaults, prompts, schemas, validators, output caps, scopes, isolation, and deterministic gates stay intact. Larger prompts still fail explicitly; this is not a guarantee for arbitrary future source bundles. Preserve in-stream provider errors as failures too.

Falsification: if reconstructed rendered counts do not match provider accounting, if no-truncate still returns a shortened accepted prompt, or if the sized sentinel remains shortened, revisit the transport diagnosis. If full-input J001 still fails ownership validation, do not claim a planner reasoning repair. Exactly one new J001 trial will test that distinction.

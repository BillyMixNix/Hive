# HIVE-TRANSITION-002 — Planning Input Fidelity

**Classification: INPUT_FIDELITY_DEFECT_IDENTIFIED_AND_REPAIRED**

Hive omitted an explicit runtime context and allowed Ollama to shorten oversized planner/worker inputs silently. This defect is measured, reproduced, and repaired. **The sole new J001 diagnostic still fails planning with complete input.** There is no worker-dispatch, edit, verification, or frozen-acceptance improvement to claim.

## 1. Prior experiment state

TRANSITION-001's final run `75280298dd02` used the repaired scope/ownership validator, qwen2.5-coder:14b, frozen M3.2 baseline and J001's single production-file scope. It made two planner calls, exhausted one correction, and produced no edits or verification. The final prior regression was 237 passed / 2 skipped. The earlier revision-1 run's worker dispatch depended on an ownership defect and is not treated as a valid planning success.

All work here is in `HIVE-TRANSITION-002/`, using a separate repaired source copy. Inventory checks found **18,002 factorial files and 2,986 TRANSITION-001 files unchanged**, with no additions to those inventories. See [factorial integrity](HIVE-TRANSITION-002/evidence/factorial-integrity-after.json) and [prior-study integrity](HIVE-TRANSITION-002/evidence/prior-study-integrity-after.json).

## 2. Intended planner input

The chain is `diagnostic_runner.task_specs/run_one` → `factorial_runner_adapter.run_condition` → `hive.run_build/_run_build_impl` → `_planner_prompt` or `_plan_correction_prompt` → agent callback → `providers.ollama_chat/_ollama_chat_once` → HTTPX `/api/chat`.

The planner receives the complete J001 behavior request, exact authorized path `src/main/java/dev/atmcompanion/state/SnapshotFormatter.java`, role and ownership rules, canonical inactive-role convention, JSON output example, and a separately transported constrained schema. The correction repeats these plus the combined rejection, interface guidance, rejected response, and one-attempt limit. It receives a large repository filename map but **no Java method body or numeric MAX_LINE_CHARS value**. Framework facts report unknown/no HTTP interfaces; the immutable intent requirements array is empty. Frozen acceptance source remains host-side.

The 2,516-token map occupies about two thirds of the initial user prompt; task/scope information follows it. Generic three-role/web examples remain in the contract. Their possible influence is a representation hypothesis, not a demonstrated serialization defect. Exact construction, components, source functions, scopes and limits: [intended-input.md](HIVE-TRANSITION-002/intended-input.md).

## 3. Exact serialized request

[wire-request.json](HIVE-TRANSITION-002/wire-request.json) is the exact first outbound new-J001 body, captured before transmission by a diagnostic-only HTTP transport wrapper. [Metadata](HIVE-TRANSITION-002/wire-request-metadata.json) records endpoint, method, byte count and SHA-256. Every attempt and complete response stream is preserved in [live wire evidence](HIVE-TRANSITION-002/evidence/live-diagnostic/wire/).

New body: model `qwen2.5-coder:14b`; separate system and user messages; `stream:true`; `format` holds the full scoped planner schema; `options.temperature:0.1`, `num_predict:2048`, `num_ctx:12288`; `truncate:false`. No explicit stop, top-k/top-p, seed, or other sampling override is added. Historical bodies omitted num_ctx and truncate. No schema or task text was shortened. Wire capture records no credentials or unrelated requests.

The first HTTP attempt returned 500 during CUDA initialization; the provider's existing retry sent **identical body bytes** and succeeded. The correction is HTTP attempt 03. Historical TRANSITION-001 captured provider arguments, not packets: its `reconstructed-wire.json` files are deterministic reconstructions through the unchanged historical provider, clearly labeled accordingly.

## 4. Context/token budget

The actual loaded model tokenizer was available. Ollama render-only output and llama-server `/tokenize` supplied exact counts; no character-to-token heuristic was used.

| Input | Full rendered tokens | Recorded input tokens | Active context | Output cap |
|---|---:|---:|---:|---:|
| Prior first planner | 3,834 | 3,834 | 4,096 | 2,048 |
| Prior correction | 4,655 | **2,050** | 4,096 | 2,048 |
| Prior revision-1 backend, supplemental measurement | 5,548 | **2,050** | 4,096 | 6,000 |
| New first planner, successful HTTP attempt | 3,834 | **3,834** | 12,288 | 2,048 |
| New correction | 4,652 | **4,652** | 12,288 | 2,048 |

Prior first input left only 262 tokens before context filled; correction exceeded context by 559 before output. The correction adds 821 input tokens. Native capacity 32,768 was not the active window. The separate format schema is 823 tokens if tokenized as text, but is used as an output constraint rather than appended prompt content. Textual schema/example instructions do compete with the map. The runner's byte-based aggregate cost reservation does not reserve context space.

The repair's 12,288 setting covers the observed 5,548-token worker plus its unchanged 6,000-token output cap, with 740 tokens spare. It is measured sizing, not a move to the model maximum. Full breakdown, original and new generation headroom, bounds and limitations: [context-budget.md](HIVE-TRANSITION-002/context-budget.md).

## 5. Provider/runtime behavior

Ollama reports version 0.34.0. Model digest matches the frozen inventory; Q4_K_M/native context 32,768. The original runtime used 4,096 and keep=4. The installed-version completion adapter's overlong-input rule retains a prefix and tail to `4096 - floor((4096-4)/2) = 2050` tokens. It is independent of the 2,048 output cap. The chat rendering stage can still return the full latest message before that later reduction.

Pinned primary source: [Ollama completion adapter](https://github.com/ollama/ollama/blob/v0.34.0/llm/llama_server.go), `completionPromptForRequest` and `contextShiftPromptLimit`; copies and hashes are preserved under `evidence/upstream/`. Runtime metadata and controlled probes corroborate the source mechanism. The long probe's terminal metadata reports input=2,050 and cached=4 separately, ruling out “2,050 is merely uncached-token accounting” for that probe.

We distinguish **KNOWN SENT**, **PROVIDER-ACCEPTED**, and **MODEL-VISIBLE UNKNOWN**. Rendered text and accepted token counts are available; historical internal token tensors are not. Inferred retained token IDs are labeled as inference, not a historical capture. See [fidelity.md](HIVE-TRANSITION-002/fidelity.md).

## 6. Sentinel experiment

Four synthetic probes were run separately from J001. Five harmless identifiers were distributed across beginning, early-middle, middle, late-middle and end. Deterministic prompts, schema, expected identifiers, exact request bodies, raw responses, terminal metadata and runtime state are in [sentinel-results.json](HIVE-TRANSITION-002/sentinel-results.json).

| Probe | Full input | Reported input | Result |
|---|---:|---:|---|
| Short, original configuration | 322 | 322 | 5/5 identifiers correct |
| Long, original configuration | 5,034 | 2,050 | Only late-middle/end correct; 2/5 |
| Same long input, truncate=false, default context | 5,034 | No completion | HTTP 400: 5,034 exceeds 4,096 |
| Same long input, explicit 8,192, truncate=false | 5,034 | 5,034 | 5/5 identifiers correct |

These observations establish positional availability under this configuration. They are not semantic reasoning scores or reliability estimates. The final Hive window is 12,288 to additionally accommodate the measured worker/output budget.

## 7. Repaired-J001 turn reconstruction

In prior run `75280298dd02`, both raw planner responses parse as JSON. The first assigns the same production path to backend and tests with no interface contract. The repaired validator reports duplicate ownership **and** missing multi-role interface contract. Correction repeats the full error and instructions. The model adds an interface contract but keeps both owners; HostWriteScopeError exhausts correction. Worker dispatch is never entered.

The inferred shortened correction still contains **task, authorized path, one-owner rule, canonical inactive-role convention and exact rejection**. It loses the map, most separate system text, and the system/user message boundary. Therefore it would be incorrect to attribute this ownership error to missing scope feedback alone. Java source is absent before serialization. Full side-by-side trace and fact classifications: [j001-turn-reconstruction.md](HIVE-TRANSITION-002/j001-turn-reconstruction.md).

## 8. Truncation hypothesis result

**Real runtime truncation is established; truncation as a sufficient explanation for J001 planning failure is not supported.**

The 2,050 plateau is predicted exactly by the installed-version truncation rule, reproduced with synthetic input, separated from cache accounting, and removed by the controlled context intervention. Caller clipping, schema-to-prompt concatenation, and output reservation are not supported explanations for that plateau.

The sole new trial has matching full input counts and ample generation headroom yet repeats the ownership error. This falsifies the stronger claim that simply restoring the complete delivered context resolves this observed planning failure. It does not prove source representation or planner instructions are sufficient for every task.

## 9. Root cause, if established

**Supported input-fidelity root cause:** the Hive call path supplied an output limit but omitted runtime context and truncation policy. Its longer structured prompts exceeded the active default window; the provider silently shortened them. The earliest confirmed loss for the historical correction occurs after serialization/rendering and before generation.

**Separate remaining failure:** the first planner already chooses invalid duplicate ownership with a complete input count, and does so again after repair. The remaining observed frontier is planner role/ownership representation or reasoning. This is not a general “model quality” conclusion. The current evidence does not distinguish generic three-role examples, inactive-role representation, schema incentives, or semantic reasoning limitations. No further prompt modification is justified by this transport study.

Falsification checks: full input accepted at default despite overlength would contradict the truncation diagnosis; a shortened accepted input with truncate=false would invalidate the fail-closed assumption; mismatch between tokenizer and provider counts would require reevaluating the accounting; a valid new plan could show frontier movement but would still not estimate reliability. Current probes support the transport mechanism; the new trial demonstrates its limited causal reach.

## 10. Repair, if justified

Production changes relative to final TRANSITION-001:

- `workshop/providers.py`: keyword-only context_window; validates it, sends `options.num_ctx` and `truncate:false`; propagates streamed provider errors as failures. Non-opted-in generic chat defaults remain unchanged.
- `workshop/hive_protocol.py`: shared measured `LOCAL_CONTEXT_WINDOW=12288`.
- `app.py:hive_agent_call`: passes that window. The diagnostic runner uses the same setting.

No planner prompt/schema semantics, Hive validator, edit executor, write authorization, isolation, frozen tests, deterministic gates, model, or cloud policy changed. In particular, **hive.py is byte-identical to final TRANSITION-001**. No J001 implementation was inserted.

The repair is in [repaired-workshop](HIVE-TRANSITION-002/repaired-workshop/), with [repair.patch](HIVE-TRANSITION-002/repair.patch) and [hash manifest](HIVE-TRANSITION-002/repair-manifest.json). `git apply --check` against the prior source copy passed without modifying it. Diagnostic-only capture, measurement, sentinel, replay and reporting scripts are outside production.

## 11. Regression results

**253 passed, 2 skipped**. The two skips are the existing Windows symlink privilege restrictions. [Command/result](HIVE-TRANSITION-002/evidence/regression.json), [full log](HIVE-TRANSITION-002/evidence/regression.log).

Sixteen new cases cover preserved historical messages/schema at actual HTTP serialization, explicit context propagation, invalid window/output combinations, unchanged correction construction, HTTP/streamed context failures without retry or acceptance, and historical ownership rejection. The existing suite covers malformed plans, forbidden scope, correction exhaustion, dispatch eligibility, isolation and gate ordering. The real app callback test also checks the configured context argument. An initial targeted invocation failed because fixtures were copied from the wrong working directory; after correcting that setup, targeted tests passed 36/36 and the full selected suite passed as above. No production behavior was changed to resolve that setup error.

[Historical replay](HIVE-TRANSITION-002/evidence/historical-input-replay.json) uses zero model calls: both input messages and schemas are unchanged, only num_ctx/truncate differ; both historical invalid outputs remain rejected with exactly the prior errors. These regressions use synthetic verification where appropriate and do not count as frozen acceptance.

## 12. New live diagnostic

Exactly **one** new J001 trial: run **6b87294fdc72**, study HIVE-TRANSITION-002. [Freeze](HIVE-TRANSITION-002/FREEZE.json), [preflight](HIVE-TRANSITION-002/evidence/live-diagnostic/preflight.json), [result](HIVE-TRANSITION-002/evidence/live-diagnostic/01-J001-r1-qwen2.5-coder-14b-hive/result.json), [run trace](HIVE-TRANSITION-002/evidence/live-diagnostic/01-J001-r1-qwen2.5-coder-14b-hive/run.json).

Frozen baseline hash: `230340980b85d60b7a59d3aa338dffc4447c1bb7d8df90bff4d0dbe89afe5388`. Model digest, single-file write scope, sealed verifier image/cache and gates matched the frozen study. An exclusive start marker prevents repeating this diagnostic accidentally.

Outcome: MODEL_TASK_FAILURE; two completed planner calls, one correction; 8,486 input / 590 output tokens; 451.874 seconds overall; $0 API cost. Three HTTP attempts include the initial CUDA initialization 500 and the unchanged retry. Successful responses both end with `done_reason=stop`. Provider counts exactly match full rendered/tokenized input, 3,834 and 4,652, at 12,288 context. [Live input measurements](HIVE-TRANSITION-002/evidence/live-input-measurements.json).

Both plans assign the production path to backend and tests. The correction adds a contract but leaves overlap. The validator correctly terminates before dispatch. No worker was available to assess new source grounding. No edit exists; candidate hash remains baseline-identical; verification and review are null; frozen acceptance was not reached. No second J001 trial was run.

## 13. Failure-frontier comparison

| Measurement | Final TRANSITION-001 | TRANSITION-002 |
|---|---|---|
| First planner valid | No | No |
| Correction required | Yes | Yes |
| Full correction input accounted for | No: 2,050 / 4,655 | **Yes: 4,652 / 4,652** |
| Duplicate ownership corrected | No | No |
| Worker dispatch | No | No |
| Worker source grounding in this trial | Not exercised | Not exercised |
| Scoped candidate edit | No | No |
| Executable deterministic verification | No | No |
| Frozen acceptance | No | No |

Input transport improves; **the execution frontier does not move**. Full task, scope and correction delivery no longer explain away the remaining observed ownership error. No success-rate improvement is inferred from this adaptive diagnostic.

## 14. Remaining uncertainties

- Exact historical model-internal token visibility is unavailable; retention is source-based inference corroborated by counts and probes. Complete current provider accounting does not prove attention to every instruction.
- The planner never receives the Java method body. Whether that omission matters for valid ownership planning remains untested; source access for an actual worker is not tested by this new run.
- Generic multi-role examples and contract guidance may interfere with single-file planning. Their causal effect is unmeasured; prompts were deliberately left intact.
- The 12,288 setting covers observed budgets, not arbitrarily long future bundles. Longer inputs now fail explicitly on the tested runtime; very long generation from a nearly full but admissible input can still encounter context shifting.
- The initial CUDA failure and increased runtime allocation are operational costs to monitor, not grounds for another J001 trial here. The existing retry recovered; it does not establish runtime reliability.
- No candidate reached deterministic verification, so this study says nothing new about J001 implementation quality or acceptance success.

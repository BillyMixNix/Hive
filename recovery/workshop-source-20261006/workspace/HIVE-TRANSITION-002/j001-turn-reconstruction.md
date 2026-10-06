# Repaired TRANSITION-001 J001 reconstruction

Target: run **75280298dd02**, final ownership repair; qwen2.5-coder:14b; frozen M3.2 baseline. This is not the earlier revision-1 run that dispatched workers through an ownership hole.

Authoritative historical files: `../HIVE-TRANSITION-001/evidence/live-revision2/02-J001-r2-qwen2.5-coder-14b-hive/{run,calls,result}.json` and `../HIVE-TRANSITION-001/evidence/live-revision2/model-boundary/{01,02}/{request,response}.json`. Self-contained copies of the latter and run.json are in `evidence/planner-input-fixtures/`. No new model response substitutes for either historical response.

| Observable | First planner | Correction |
|---|---|---|
| Intended prompt | request.json `messages[0].content`; 17,413 chars | 21,147 chars, full original plus rejection/correction |
| Intended prompt SHA-256 | `7ea130b272dc13aa728dabf58309babc66fc399f77826a779079ba74a9c41958` | `392cade502ddd9e550efdfbc565d81d822e0ea9604b12811a93667e6fc519f67` |
| Serialized request | `evidence/measurements/historical-planner-1/reconstructed-wire.json` | corresponding `historical-planner-2/reconstructed-wire.json` |
| Endpoint/options | `/api/chat`, stream true, JSON schema, temperature .1, num_predict 2048, no num_ctx/truncate/stop override | same; no forced interface minItems for this HostWriteScopeError |
| Provider metadata | 3,834 input / 262 output; context 4,096 | 2,050 input / 336 output; context 4,096 |
| Exact newly rendered/tokenized input | 3,834 tokens | 4,655 tokens |
| Raw response | `planner-input-fixtures/01/response.json` | `planner-input-fixtures/02/response.json` |
| JSON parser | `_extract_json` succeeds | `_extract_json` succeeds |
| Plan | backend and tests both own SnapshotFormatter.java; ui inactive; no interface contract | same overlapping ownership; adds interface contract from backend to tests |
| Validator | HostWriteScopeError: duplicate ownership **and** missing multi-role interface contract | HostWriteScopeError: duplicate ownership |
| Correction decision | one correction available; `_plan_correction_prompt` receives the full combined error | `MAX_PLAN_CORRECTIONS=1` exhausted |
| Dispatch / candidate / verification | none | none; stage and candidate baseline-identical; verification null |

The first error is exactly: `file 'src/main/java/dev/atmcompanion/state/SnapshotFormatter.java' is assigned to both backend and tests; keep exactly one owner and deactivate roles without authorized work; multi-role plan requires at least one interface contract`.

The corrected plan removes neither owner. The final exception is `Planner correction budget exhausted; file 'src/main/java/dev/atmcompanion/state/SnapshotFormatter.java' is assigned to both backend and tests; keep exactly one owner and deactivate roles without authorized work`. `_run_build_impl()` never enters worker execution after this validation failure.

## Required-fact fidelity

“Present” below means present in the intended/serialized/rendered string. “Retained” is inferred from the pinned completion algorithm and original count, not a historical internal-token capture.

| Fact | First input | Correction input | Inferred correction retention |
|---|---|---|---|
| Complete task behavior, ASCII/sanitization/suffix/bound | Definitely present | Definitely present | Present |
| Exact allowed production path | Definitely present in task, scope and schema | Definitely present | Present |
| One owner per file | Definitely present | Definitely present | Present |
| Canonical inactive goal and empty lists | Definitely present | Definitely present | Present |
| Role distinctions and output example | Definitely present | Definitely present | Present |
| Correct rejection and single remaining correction | Not applicable | Definitely present | Present |
| Original rejected response | Not applicable | Definitely present, uncut | Present |
| Repository map | Present, structurally dominant | Present, structurally dominant | Truncated away |
| System role instructions | Definitely present | Definitely present | Mostly truncated |
| System/user message boundary | Present | Present in rendered input | Truncated away |
| Java source method and numeric constant | Absent | Absent | Absent by construction |
| Frozen test implementation | Absent by design | Absent by design | Host-side only |
| Generic HTTP interface examples | Present | Present and expanded | Present; relevance to Java plan ambiguous |

The map dominates the beginning, while useful task/scope instructions are late in the initial prompt. Correction adds 821 tokens at the end. For this particular corrected input the drop boundary happens just before the task, so it would be false to say Ollama erased the required scope instruction. The source representation is shallow from the outset; that alone is not proven insufficient for choosing a single authorized worker.

## Falsifiable conclusion

There is a concrete loss of input fidelity at **runtime context admission before generation**. There is also an independently observed invalid ownership choice on the first attempt, whose input token count matches the complete rendered input. A transport repair cannot be credited with fixing that choice without live evidence. If the sole new diagnostic has matching full counts but again chooses overlapping roles, the remaining observed frontier is planner role/ownership representation or reasoning; further transport defects must not be invented.

That condition occurred in the sole new trial `6b87294fdc72`: complete 3,834/4,652-token inputs, followed by the same two ownership rejections. The correction adds an interface contract without removing duplicate ownership. This narrows the remaining failure to planning/representation, while preserving the independently demonstrated transport repair.

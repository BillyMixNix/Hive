# Repaired Hive replication — HIVE-FACTORIAL-003R1

Authorized by “Freeze it. Run the 16.” This is a new study. FACTORIAL-003 remains invalid, with zero valid completed cells; its first cell is not reused. FACTORIAL-002 remains 0/16 Hive and 0/16 single.

Sixteen fresh serial Hive cells: four unchanged tasks × two unchanged local models × two replicates. Recover `random.Random(20261004)` task/replicate block and model/controller shuffle from FACTORIAL-002, then retain Hive cells in the original relative order. Freeze all cells before inference. No current single-agent condition is requested.

Use the byte-identical final NFRT-ATTESTATION-002 production tree in a new isolated copy and explicitly pin its v2 manifest. No controller, schema, prompt, gate, scope, provider, cache or model repair during the study. The recorder and candidate-capture/context wrapper are byte-identical to HARNESS-QUALIFICATION-001. The assembled executor is tested using scripted responses before freezing; those are not trials or model context.

The first local harness test command lacked its temporary-directory parent and failed test setup; its log/XML are preserved. The parent was created by JUnit output setup, then the complete harness tests ran in a fresh temp directory. No production changes or inference were involved.

## Runtime policy

One bounded non-task readiness call for each model before cells, in order qwen2.5-coder:14b then qwen3:8b. No later warmups, explicit load/unload, keep-alive tuning, GPU changes, process closure, parameter changes or failed-cell replacements. Observe actual residency and resources. Short readiness success does not imply workload readiness; readiness failures are preserved separately and do not erase or replace cells.

Ollama localhost only, `num_ctx=12288`, `truncate=false`, temperature 0.1. Production role output caps: planner 2048, workers 6000, reviewer 1536. Existing provider retry policy (maximum two HTTP attempts), 900-second generation setting, one planner correction, one structural worker correction, one targeted worker correction; unchanged historical 3600-second decision wall cap and 250000 aggregate reservation/usage ceiling. The reservation estimator uses prompt UTF-8 bytes plus 1000 plus output cap; it is not an exact tokenizer. Full serialized requests, responses and provider usage are retained separately.

Targeted verification deadline 240 seconds; full outer/inner deadlines 660/600 seconds. Pinned Java/image, offline, attested private intermediates, fresh compilation, `--rerun-tasks` and `--no-build-cache` remain unchanged. Frozen tests stay outside model-visible roots. No previous implementation is supplied to any trial.

## Outcomes and containment

Verified software success requires a model candidate, exact scope, frozen acceptance, full gate and candidate/source integrity. Semantic review disposition is independent. Unavailable/rejected model review cannot erase deterministic PASS; neither authorizes promotion. All external candidates remain non-promotable, and every study row has `promotion_authorization=not_authorized`.

Every verifier wrapper invokes its original exactly once and returns/raises unchanged. Recorder failures are separate MEASUREMENT_FAILURE and stop scoring; missing timing cannot fabricate a verdict. Measurement failure or integrity failure stops the study, preserving the compromised cell without replacement. Provider/model/verifier failures within the normal production protocol are trial data; subsequent frozen cells continue unchanged.

Record requests, attempts, outputs, normalization, ownership, edits, verification/correction, review, identities and resource/timing evidence. Applied-source snapshots from each invocation preserve transient proposals even after rollback. No candidate is applied. Observe resources before/after trials, at request/attempt boundaries and periodically.

## Analysis

Report all 16 cells; successes by task/model/replicate; transition reachability; failure/runtime/review distinctions; corrections/repeats/malformed output; logical calls, HTTP attempts, known tokens, model/verifier/wall seconds; successes per call and trial-hour. Missing token accounting remains unknown. Report Clopper–Pearson 95% exact interval and two-sided Fisher exact comparison with historical 0/16. Different dates and multiple intentional repairs prevent attribution to any single repair; faster failure is not efficiency improvement.

Rehash source, baseline, tests, attestation, approved cache/image identities and prior evidence at completion. No historical rescore. No follow-up repair or extra trial in this study.

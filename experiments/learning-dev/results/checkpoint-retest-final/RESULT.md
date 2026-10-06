# Hive redesign and retest — 8 September 2026

**No confirmed lesson gain.**

In the repaired-interface run, retained lessons produced the same audited correctness as both controls, used more calls, and had no lower audited effort on any transfer task.

The context revision and explicit memory checkpoint were implemented and exercised in 63 new recipient runs. The intended confirmation stopped after 18 runs because the new interface imposed a fragile long-ID copying requirement. The remaining 45 untouched recipients ran after that interface was repaired and are reported separately as descriptive evidence. These batches are not pooled into a rescued confirmation.

## Repaired interface: 45 completed runs

Twelve transfer tasks and three unrelated retention tasks each ran once with empty memory, the unchanged V4 model-generated lesson bank, and word-matched unrelated notes. All arms received complete selected-callable context, the public objective and the same short, schema-constrained memory choices.

| Guidance | Original transfer checks | Full-contract transfer checks | Actual transfer calls | Audited penalized calls | Retention passed |
|---|---:|---:|---:|---:|---:|
| No lessons | 9/12 | 8/12 | 154 | 220 | 2/3 |
| Retained lessons | 9/12 | 8/12 | 165 | 230 | 2/3 |
| Unrelated notes | 9/12 | 8/12 | 154 | 220 | 2/3 |

An unsuccessful repair receives 36 in the effort score. Actual calls and dollar estimates remain separate. A fast incorrect answer does not earn an efficiency win.

| Audited comparison | Effort reduction with lessons | Lower / higher / tied effort |
|---|---:|---:|
| Lessons versus no lessons | -4.5% | 0 / 3 / 9 |
| Lessons versus unrelated notes | -4.5% | 0 / 3 / 9 |

These are descriptive differences after a protocol departure, not confirmatory significance claims. No alpha was reassigned after seeing results.

| Guidance | Transfer input tokens | Transfer output tokens | Conservative transfer charge |
|---|---:|---:|---:|
| No lessons | 290,503 | 35,534 | $0.2092127 |
| Retained lessons | 388,227 | 41,902 | $0.2695371 |
| Unrelated notes | 344,709 | 36,407 | $0.2378871 |

## Original interface: 18 completed runs, then stopped

| Guidance | Original passes | Passes after cache audit | Actual calls |
|---|---:|---:|---:|
| No lessons | 5/6 | 4/6 | 80 |
| Retained lessons | 1/6 | 1/6 | 58 |
| Unrelated notes | 5/6 | 4/6 | 76 |

Four lesson recipients stopped when the model omitted one character from a 64-character advisory memory ID. The native action and its bad ID remain recorded; nothing was repaired retrospectively or credited as executed. This was an avoidable interface design flaw. One rejected action also predicted that it would violate the cache contract, so fixing its ID would not automatically make it a correct repair.

The original protocol did not predeclare this stop. Its confirmation remains incomplete. The repair gives the model memory_1, memory_2, memory_3 or none, constrained by the native schema. The remaining original tasks were used without replay, replacement, new lesson formation or lesson edits.

## Additional correctness finding

Two original-version cache candidates passed the original tests with key = self.identity(locale), dropping item identity. An independent full-key audit was committed after observing that defect, before inspecting any repaired-interface outcome. It tests distinct and equivalent names, tuple-valued hooks, each key dimension separately, shared stores and repeated keys with changed values. Reference repairs pass; incomplete keys fail.

All cache candidates receive the same audit after their source hashes are fixed. Original scores remain visible. The audit withdrew the three follow-on passes on the operation-cache task, one in every condition. This audit can withdraw correctness credit but cannot rescue a positive confirmation.

The filtered-pairs task failed in all three original-version arms. Its recorded checkpoints identified association problems, but the controller repeatedly offered narrow reference substitutions and rejected causal locations. The final candidates remained unchanged. This shows a remaining gap between describing a principle and producing an accepted repair; it does not establish that lessons caused the failure.

In the repaired-interface top-k task, all three conditions produced patches that mutated the caller's payload list despite the public input-preservation requirement. Hive returned SATISFIED, but the frozen protected tests correctly failed the patches. A saved concrete counterexample confirms the mutation. On stable partition, all three conditions used 30–32 calls and left the source unchanged. These shared failures identify repair and review limitations that retained advice did not overcome; they do not isolate whether broader edit authority would fix them.

## Spending and scope

This redesign/retest used **774 new provider requests**. Its conservative added token-charge bound is **$1.1546903**. Across every earlier Hive attempt, the cumulative conservative bound is **$3.4695976 of the original $5**. The total permanently carries the earlier $0.5323728 unknown-usage reservation. It is not an invoice and does not reset or refund earlier failures.

The model alias is gpt-5.6-luna throughout actual requests and responses. The provider alias does not independently pin a weight snapshot. The three lesson texts are exactly the earlier model-generated bank; weights were not trained. These small authored tasks cover three mechanism families, and several cache tasks share a source skeleton. All arms received both context and checkpoint changes, so this does not separately estimate their effects. The original V4 negative confirmation remains preserved.

Verification reconciled all 774 new provider requests, 63 recipient records and 58 saved candidate hashes, with visible tests unchanged. Repository-wide CI passed 515 tests, skipped two and passed five additional subtests after the test-import fix; the reliability gate also passed. The final experiment gate passed 180 tests, skipped two and passed five additional subtests. Exact CI commits and runs are recorded in final-audit.json.

The branch contains the revision, the failed outputs, the protocol departure, complete usage evidence and independent audits. No further paid run is scheduled by these protocols.

[Hive PR 35](https://github.com/BillyMixNix/Hive/pull/35). Protocols: LESSON_BANK_V5.md, CHECKPOINT_INTERFACE_REPAIR.md and CACHE_AUDIT_AMENDMENT.md in experiments/learning-dev. Exact launch commits and raw archive hashes are included in the evidence index.

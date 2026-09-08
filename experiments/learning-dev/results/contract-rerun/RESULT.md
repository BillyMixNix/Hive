# Hive input-contract rerun

Status: **COMPLETED**. 45/45 recipient results recorded; 565 provider requests.

The outcome is mixed: all three conditions passed **11 of 15 tasks overall**. On the 12 transfer tasks, lessons matched the no-lesson condition at 9 correct repairs and used 10.65% less failure-penalized effort. Against neutral notes, lessons repaired one more transfer task and used 12.67% less penalized effort, but passed one fewer retention task. Raw calls across all 15 tasks were 208 without lessons, 182 with lessons, and 175 with neutral notes. This is a modest descriptive transfer signal, not confirmed learning.

This reran the same 15 tasks and the same three retained model-generated lessons after the input-contract repair. The comparison is descriptive because the tasks were already evaluated and the repair used an observed failure.

| Condition | Correct transfer repairs | Correct retention repairs | Transfer calls | Transfer calls with failure penalty | False completions | All calls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| No lessons | 9/12 | 2/3 | 176 | 216 | 1 | 208 |
| Retained lessons | 9/12 | 2/3 | 150 | 193 | 1 | 182 |
| Neutral notes | 8/12 | 3/3 | 148 | 221 | 2 | 175 |

A false completion is a controller SATISFIED verdict that fails the independent final checks. Failed repairs receive a fixed 36-call effort penalty; finishing incorrectly or stopping early cannot earn an efficiency advantage.

Against no lessons, lessons used less penalized effort on 3 transfer tasks, more on 0, and tied on 9. The aggregate reduction was 10.65% (negative means more effort).

Against neutral notes, lessons used less penalized effort on 2 transfer tasks, more on 1, and tied on 9. The aggregate reduction was 12.67% (negative means more effort).

## Input check

The controller used explicit argument-preservation declarations on eleven tasks, identically across conditions. Four tasks require consuming iterators and retained their original adapter. The public input checker does not inspect protected tests. All original acceptance tests remained in place; all cache tasks received the previously defined full-cache audit at final scoring only.

The saved controller traces recorded input mutations in 3 recipients. These are reports from the checker on observed public-test calls, not a universal proof of input preservation.

| Task | Condition | Distinct mutation candidate hashes | Final decision | Final correct |
| --- | --- | ---: | --- | --- |
| top_k_pairs | Neutral notes | 1 | SATISFIED | True |
| top_k_pairs | Retained lessons | 2 | SATISFIED | True |
| top_k_pairs | No lessons | 3 | SATISFIED | True |

All three top-k recipients encountered the new mutation check and ultimately produced correct repairs using local variable rebinding. The gate recorded six distinct rejected mutation candidates: three without lessons, two with lessons, and one with neutral notes. Final top-k effort was 30, 13 and 10 calls respectively. The neutral condition was fastest on this task, so its repair success cannot be attributed specifically to retained lessons.

Remaining false completions were the operation-cache task in all three conditions and the shared-namespace cache task with neutral notes. These passed input preservation but failed the existing full-key final audit; the new gate does not check every aspect of a cache contract.

## Spending

Prior cumulative bound: $3.4695976. Added measured-usage bound: $0.8543316. New unresolved reservation: $0.0000000. Cumulative bound: **$4.3239292 of the original $5**.

The cumulative bound retains the earlier $0.5323728 unknown-usage reservation. These are conservative token-charge bounds, not a provider invoice or the account's balance. The same full-context reservation was retained before every request; no retry or new authorization resets prior spending.

| Condition | Input tokens | Output tokens | Added charge bound |
| --- | ---: | ---: | ---: |
| No lessons | 394303 | 54381 | $0.2950373 |
| Retained lessons | 422406 | 44044 | $0.2904822 |
| Neutral notes | 389279 | 41207 | $0.2688121 |

Conservative rates remain 500 nanoUSD per input token and 1800 per output token, reverified on September 8 against [official OpenAI pricing](https://developers.openai.com/api/docs/pricing).

## Evidence and limits

[Cloud run](https://github.com/BillyMixNix/Hive/actions/runs/34287133344); launch commit `2e5b24939dfe764a3eed39ed2bd694aec8406de5`; retained-bank hash `53e959ee24c1c0fca0be1f899ce711f2636f01c3925ed5e9df3cd4d5cb6936a4`.

The independent audit verified 1494 artifact files, reconciled all charge records, checked the exact supplied guidance and tool schemas, and rescored 45 saved final candidates. Original public tests remained unchanged. Original and supplemental private-test filenames were absent from captured requests; this is a scoped check, not a general proof of isolation.

The same provider model alias was used once per task and condition. Model weights were not trained. There is no statistical confirmation, pooling with prior runs, task replacement, or evidence here of broad recursive self-improvement. The prior study remains unchanged and is reported separately.

The exact launch passed the experiment suite (204 passed, 2 skipped, 5 subtests passed) and repository CI (539 passed, 2 skipped, 5 subtests passed). The independent audit/reporting code was committed before outcome inspection at `df5f2da736c1aed1412cafd6b69b5ccb82dfbf18` and also passed 539 repository tests and the reliability gate. See `ci-launch.json` and `ci-code.json`.

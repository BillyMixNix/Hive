# Real-bug capsule comparison — September 9, 2026

The frozen experiment completed all 12 episodes and failed its advance gate: **DO_NOT_ADVANCE**. Capsules showed a useful descriptive efficiency signal, but did not provide reliable state acknowledgement or verified completion.

| Condition | Correct repairs | Conservative API cost | Correct/API dollar | False completions | Missing required first-action state |
|---|---:|---:|---:|---:|---:|
| Full raw history | 1/4 | $0.1829849 | 5.465 | 3 | 4 |
| Hive compiled capsule | 2/4 | $0.0312667 | 63.966 | 2 | 4 |
| Ordinary summary | 1/4 | $0.0825512 | 12.114 | 3 | 3 |

Summary cost includes all four construction calls. Capsule construction used no API calls and took 0.0741 CPU seconds; CPU has no assigned dollar price. These are conservative metered API costs, not invoiced or full economic costs. No condition introduced a tested regression.

## What happened

Capsules repaired the zero-IQR histogram and None-valued combination-index bugs. Raw history repaired the iteration-TypeError bug. The ordinary summary repaired the zero-IQR histogram bug. No condition repaired the Unicode line-splitting bug.

Both capsule failures immediately returned `complete`, without editing or testing the restored buggy revision. All four capsule recipients omitted the mandatory first-action `state` object. The required state was present in every compiled capsule and verified offline. Thus the audit field `lost_required_state` means failure to acknowledge the declared state in the required response; it does **not** establish that compression deleted that information or that the model forgot it. The same omission affected all raw-history recipients and three summary recipients.

The capsule achieved 11.71 times raw history's and 5.28 times the summary's correct repairs per API dollar in this sample, and met the numerical accuracy/cost thresholds. It nevertheless failed the predeclared hard vetoes. Even disregarding the state-response requirement, its two false completions independently prevent advancement. No criteria were relaxed and no paid retry was performed.

## Keep, publish, stop

- Keep the generic capsule compiler, frozen fixtures, revision-aware editing, evidence records, and replay/cost audit.
- Publish this as a completed exploratory comparison with an efficiency signal and a failed reliability gate.
- Stop this version from advancing to a larger paid replication or being presented as proven improvement.
- Before further paid work, test an enforced state acknowledgement and completion gate offline: the executor should require current verification before accepting completion. This is a proposed next engineering change, not a result of this experiment.

## Scope and verification

Four public upstream bugs newly used in Hive, each tested once per condition. Histories were constructed from executed reads, failures, failed edits and rollbacks; they were not organic long-running agent histories. File and symbol locators were supplied. Public bugs may have been seen by the model before. This is descriptive evidence, not statistical confirmation or proof of general capability growth.

Capsules contained 2,901–3,716 UTF-8 bytes; raw histories 33,728–183,619 bytes. Ordinary summaries contained 1,421–1,703 bytes under the same per-task byte ceiling as capsules. This was budget matching, not equal realized length or token count.

The workflow passed 262 tests (2 skipped, 5 subtests passed), completed 34 paid requests, then replayed and rescored all saved repairs. A separate local replay reproduced the cloud audit exactly using the same evaluator implementation. All 39 uploaded files were preserved; the downloaded original ZIP SHA-256 was checked before extraction. No unresolved spending reservations remain.

This run cost $0.2968028. Including prior packet work, the fresh $5 budget's cumulative conservative bound is **$1.2254010**, leaving **$3.7745990**. The earlier lesson budget is separate.

## Frozen evidence

- Run: https://github.com/BillyMixNix/Hive/actions/runs/34373375672
- Experiment commit: `9c1525332e84b68d1e379f43e2fbcac4eb2bcfd0`
- Plan SHA-256: `2d413c6a907c06931a1de497f2a0dafb20ce194bbc712ecf82a9d99fba25cf08`
- Fixture ZIP SHA-256: `c1432348781fd53d08a26c66cba58148d4c0ae1a289df12360186e2406991c55`
- Original evidence ZIP: `examples/heldout-capsule-evidence-20260909.zip`
- Original evidence ZIP SHA-256: `6b61c9322b98a16d1e45db901906b0e73ed14ae85e62eee334ce8e2a7b8e93c9`

Replay from `experiments/learning-dev`, after extracting the evidence ZIP:

```sh
python analysis/heldout_trial.py audit examples/heldout-real-bugs-v1-20260909.zip /path/to/heldout-evidence --sha256 2d413c6a907c06931a1de497f2a0dafb20ce194bbc712ecf82a9d99fba25cf08
```

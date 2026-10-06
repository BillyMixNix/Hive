# Timing comparison — verifier-only, no model generation

All durations below are seconds. Five fresh isolated candidates/containers were measured sequentially: three initial controls and two post-regression repeats. There was no behavioral runtime/performance repair between batches; the tested observability code is the same. Neither cache contents nor candidate code were tuned. The source manifest and exact invocation are recorded for every run.

| Replay | Host preflight | Launch to container | Project copy | Wrapper copy | Native inputs | Before Gradle (inside budget) | Gradle exposure to timeout | Outer time | Post-timeout work |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| measured-baseline | 24.954 | 27.057 | 12.194 | 11.119 | 98.599 | 149.348 | 90.703 | 240.051 | 16.934 |
| measured-preserved | 13.838 | 1.123 | 6.908 | 9.391 | 78.480 | 96.140 | 143.965 | 240.105 | 22.085 |
| measured-known-good | 16.268 | 2.161 | 10.035 | 12.226 | 115.700 | 140.482 | 99.594 | 240.077 | 23.444 |
| post-regression-baseline | 16.678 | 1.680 | 6.967 | 10.815 | 81.798 | 101.566 | 138.477 | 240.043 | 20.795 |
| post-regression-preserved | 22.236 | 3.063 | 8.049 | 11.474 | 102.581 | 125.471 | 114.594 | 240.065 | 18.583 |

Host preflight occurs before the 240-second Docker deadline; post-timeout removal/cache validation/cleanup occurs after it. “Before Gradle” overlaps the listed setup subphases and must not be added to them. Cross-boundary launch latency uses host receipt time; within-container copy durations use the container's own monotonic clock. Gradle exposure is a censored interval ending at the outer timeout, not Gradle completion time. No inner Gradle duration or frozen test result is invented.

Every run's last task marker is `createMinecraftArtifacts`; the baseline and preserved-candidate repeats expose the native artifact reconstruction substeps in child-stdout.log. None records `compileJava`, `compileTestJava` or a `test` task marker. The accepted control was historically verified under the same frozen gate, but this measurement is a new timeout and does not change that history.

The major measured preparatory cost is the manifest-verified private copy of 3,895 native input files / 914,224,273 bytes. The baseline /proc sample observes filesystem waiting on an asset during this phase. Later active JVM/tool trees and advancing output locate continued work, not a demonstrated deadlock. Variation in setup/host state prevents treating these five observations as a general latency distribution or causal estimate of a particular environmental fault.

Full raw phase/output/process evidence is beneath `evidence/verifier-replays/<replay>/diagnostics/`; each result includes source/baseline integrity, candidate hash, exact frozen manifest and a no-model/no-promotion disposition. Preserved edits are labeled POST_HOC_CANDIDATE_VERIFICATION. No acceptance pass was obtained.

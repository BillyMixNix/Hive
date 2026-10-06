# Pre-behavioral-repair timeout diagnosis

**Causal classification: INSUFFICIENT_EVIDENCE**

This classification concerns a specific underlying verifier/environment defect or invalid budget, not whether the timeout was reproduced or localized. The diagnostic-loss defect is established and repaired by observability instrumentation. No behavioral/performance repair or timeout change follows from this diagnosis. This artifact is sealed before post-regression replay and is not revised to fit later results.

## Established evidence

All three sequential instrumented controls timed out at the unchanged outer 240 seconds: frozen baseline, exact preserved TRANSITION-003 edit, and the compatible independently accepted Astra candidate (historically frozen acceptance and full gate passed). They used fresh isolated candidate trees, the same pinned image/runtime, same approved read-only inputs, identical selectors/assertions/resource limits, and identical instrumentation.

| Control | Before Gradle, inside outer budget | Native-input copy | Gradle exposure before timeout | Last observed task |
|---|---:|---:|---:|---|
| Baseline | 149.348 s | 98.599 s | 90.703 s | createMinecraftArtifacts |
| Preserved Hive edit | 96.140 s | 78.480 s | 143.965 s | createMinecraftArtifacts |
| Historically accepted candidate | 140.482 s | 115.700 s | 99.594 s | createMinecraftArtifacts |

The baseline first launch had about 27 seconds before the first container event; later launches took about 1–2 seconds. Source materialization and wrapper copying took another 16–23 seconds. The required manifested native input set contains 3,895 files / 914,224,273 bytes. Its private copy dominates pre-Gradle time. Host cache validation before launch and cleanup/cache validation after timeout add wall time outside the 240-second budget.

At a baseline setup sample, only verifier Python was alive, blocked in `p9_client_rpc`, with descriptors open on an approved mounted asset and its tmpfs destination. This directly observes filesystem waiting during copy. Later samples show the wrapper JVM, single-use Gradle daemon and active NeoForm tool JVM descendants. Logs keep advancing. No OOM kill or external network I/O is recorded by sampled container state. Successful exact-container removal, subsequent `no such object` and removal of sanitized temporary input are recorded after all three timeouts.

The deadline fires while Gradle is constructing shared Minecraft artifacts, **before any observed compileJava, compileTestJava or test task marker**. The preserved edit reaches the `binaryWithNeoForge` substep but not its completion. It is not executing SnapshotFormatter or the frozen test at that boundary. These controls strongly reject the candidate edit as a necessary cause of the reproduced timeout. They also distinguish the timeout from malformed action execution, planner failure and a frozen behavioral assertion failure.

## What remains unsupported

The historical TRANSITION-003 stdout/stderr cannot be recovered. Its exact internal deadline phase is therefore still unknown; these are new controlled reproductions, not retroactive timestamps. Substantial setup plus shared artifact reconstruction explains the observed outer deadline exhaustion. It does **not** establish which remediable infrastructure/environment defect, if any, causes current latency.

`p9_client_rpc` demonstrates a filesystem wait, not by itself a defective filesystem, permanent deadlock or measured disk-throughput root cause. The cost varies substantially across fresh containers despite unchanged inputs. Host snapshot shows 16 GiB physical RAM and about 2.1 GiB free, but no historical or controlled pressure experiment establishes contention as causal. No model was generated during these replays. Page-cache/model-residency/host-load conditions differ from the original live trial and were not manipulated.

The same accepted candidate previously completed its Gradle targeted subprocess in 161.382 seconds, under the same frozen gate. That historical inner-command time excludes setup and does not prove today's total fits 240 seconds. Conversely, three current timeouts do not prove 240 seconds is intrinsically an invalid budget after all remediable defects are excluded. No incorrect cwd/selector, network resolution loop, pipe deadlock or leaked container was demonstrated. Known expensive bootstrap work is required by the frozen fresh-workspace/rerun policy; skipping it or changing gates is not a justified repair.

## Competing explanations and falsification

- Environment-sensitive filesystem/cache/CPU/memory latency plus setup sharing the deadline is supported as a mechanism. A controlled same-input transport/resource comparison that removes the latency while retaining every integrity check would distinguish a repairable runtime issue from expected workload cost; that larger intervention is not performed here.
- Candidate-induced timeout would gain support if baseline/accepted controls promptly reached results while only the preserved candidate stalled during its test execution. The current three controls contradict that pattern; no candidate test was observed executing.
- A concrete verifier bug would require, for example, a wrong selector, blocked process/pipe dependency or leaking descendant trace. Current logs/process samples do not show one. Absence of sampled evidence is not proof that every possible defect is excluded.
- Budget inadequacy would require representative correct expected verification timing after remediable defects have been excluded. Increasing the deadline is neither a diagnostic proof nor permitted in this study.

## Decision

Retain the minimal observability/output-preservation repair. Make **no runtime/performance, candidate, model, scope, acceptance or timeout change**. Complete regression, repeat baseline/preserved verification under the unchanged instrumentation/budget, and do not run a model unless the stated live-entry conditions become supported. Keep planner-to-worker ASCII semantic fidelity as a separate TRANSITION-005 hypothesis.

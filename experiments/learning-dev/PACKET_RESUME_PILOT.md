# Synthetic packet continuation pilot

Three hand-authored interrupted Python tasks: explicit zero handling, stable
deduplication, and reversing a one-shot iterator. Each has history, packet-only,
and objective-only conditions, independently started with no provider conversation
ID. There are nine episodes, in a seeded shuffled order, with at most three JSON
actions each. The local executor applies edits and runs real public tests.
Completion also requires separately withheld correctness tests and a public test
pass on the latest revision. Those withheld results are not returned to the model.

History includes the old files and ordered events; the packet includes current
files and typed events but no original conversation. Both conditions include the
same failure observation, rejected test edit, current file-write event, and
unsupported assistant success claim. This tests a small synthetic reconstruction
and continuation task, not compression of a long natural conversation. Packet
construction uses trusted explicit state, not automatic history extraction.

The objective-only condition is an information-removal control. Asking for missing
context is safe abstention, not a safety failure. Measure verified completion,
false completion, abstention, invalid actions, and whether the model correctly
reports that the latest checkpoint revision is unverified. Small counts do not
establish generality, significance, or long-horizon reliability.

Eight focused offline tests passed, including real evaluator checks and a mocked
provider run whose traces and spending were replayed end-to-end. Mock results
are harness tests, never empirical model results. The audit reuses the deterministic
executor; it is a replay/accounting check, not an independently implemented scorer.

Plan: examples/packet-resume-pilot-20260909.json
SHA256: 22dae503e3c6a2ae73f3f7fac3a4a6d026040cf9069070220fac4bd157155934

The original $5 authorization covers this continuation. The guard starts with
$0.919758800 already spent (conservative bound from run 34321642028), leaving
$4.080241200. It retains the September 9 verified Luna rates and September 10 UTC
expiry, with at most 27 requests and no retries. The pinned-parent push and first
attempt gates prevent ordinary subsequent pushes or reruns from launching again.
The key stays in the provider object; candidate test processes do not inherit it.
This is a trusted synthetic code bench, not a hostile-code security sandbox.

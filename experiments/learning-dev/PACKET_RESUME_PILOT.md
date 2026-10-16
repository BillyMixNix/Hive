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

Ten focused offline tests passed, including real evaluator checks and a mocked
provider run whose traces and spending were replayed end-to-end. Mock results
are harness tests, never empirical model results. The audit reuses the deterministic
executor; it is a replay/accounting check, not an independently implemented scorer.

Replacement plan: examples/packet-resume-pilot-v2-20260909.json
SHA256: 4743ae6c73154f4d5f36bf4066f9d81af7a4126399312fdc9bb33a847aa1cad9

The first launch (34365575353) aborted after one settled request and zero complete
episodes. The provider returned two byte-identical final JSON answers. The pilot
now records the original response and collapses only identical final message
objects before decoding, executing one action. Conflicting answers still fail.
Regression tests exercise the real transport decoder with both variants.
The original launch is not an experiment outcome; the replacement preserves the
same tasks and shuffled schedule, and includes its $0.000482200 charge. The audit
step now propagates Python failures instead of masking them through a tee pipeline.

The original $5 authorization covers this continuation. The guard starts with
$0.920241000 already spent (run 34321642028 plus the aborted pilot), leaving
$4.079759000. It retains the September 9 verified Luna rates and September 10 UTC
expiry, with at most 27 requests and no retries. The pinned-parent push and first
attempt gates prevent ordinary subsequent pushes or reruns from launching again.
The key stays in the provider object; candidate test processes do not inherit it.
This is a trusted synthetic code bench, not a hostile-code security sandbox.

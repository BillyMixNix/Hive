# Recovery of the ninth episode

Run 34366080331 completed eight episodes and stopped on the first response of the
ninth. The saved response contains identical final action content; opaque message
IDs can differ and are not action content. The normalizer now ignores only that
ID field when checking identical finals, while retaining original response traces.
Conflicting content still fails. Both variants are covered at the actual decoder.

The eight outcomes are preserved without resampling. The ninth response is pinned
in the original archive, parsed only after all saved final messages agree, and its
run_tests action is replayed locally. Only the remaining two actions can call the
model. Three-action limits, task content, and scoring stay unchanged. This is a
documented transport repair and interrupted-run continuation, not an untouched
single-run experiment.

The original evidence ZIP is committed with SHA256
a8ec53eeffb4bf7f6ea49083317b24e4630c5bb42212101780c300a235273683.
The recovery commitment is examples/packet-resume-recovery-20260909.json, SHA256
8953f77f9b19afbd226e6fcd9cacb9273d13b063541ea14af6ff2eef386db86f.
The guard starts at $0.928159800 cumulative conservative spending. No unresolved
reservation remains. Combined reports preserve separate old/new guard snapshots
and journals; their sums are checked against every saved response's usage.

Eleven focused tests passed, including a mocked final-episode continuation using
the real saved archive and full nine-episode replay. Mocked outcomes are not model
results. Evaluate the actual recovery artifact before reporting empirical totals.

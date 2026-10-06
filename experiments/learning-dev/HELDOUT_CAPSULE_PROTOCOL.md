# Frozen real-bug capsule comparison — September 9, 2026

Four upstream defects new to Hive's experiments, twelve recipient episodes:

| Task | Upstream source |
|---|---|
| Unicode line separators | https://github.com/mahmoud/boltons/pull/475 |
| Zero-IQR automatic histogram bins | https://github.com/mahmoud/boltons/pull/467 |
| TypeError during value_chain iteration | https://github.com/more-itertools/more-itertools/pull/1251 |
| None in combination-with-replacement indexing | https://github.com/more-itertools/more-itertools/pull/1261 |

Source and reference commits are pinned in the archive, with upstream licenses.
Preflight verified each pre-fix module fails the new bug test, each reference
repair passes, and original upstream API regression tests pass before repair.
The recipient never receives the reference repair or withheld tests.

Histories are constructed from actually executed reads, smoke tests, failed bug
tests, a deliberately abandoned edit, failed tests of that edit, and rollback.
They are controlled interruptions around real bugs, not organically collected
long-running sessions. File and symbol locators are supplied in every public task.
The compiler is generic across tasks and sees only the public history. It resolves
the rollback, retains typed actions/outcomes/uncertainty, and selects exact source
segments for the active symbol plus referenced top-level dependencies. A module
can be inspected later through the identical tool interface in every condition.

Conditions: full recorded raw history; automatically compiled Hive capsule; ordinary
prose summary produced by Luna from the identical raw history. Each prose summary
has exactly the capsule's UTF-8 byte ceiling (2.9–3.7 KB), with no padding or silent
truncation. This matches available size budgets, not realized text lengths or
token counts. Actual byte lengths and charged tokens are reported. An oversized
summary aborts the comparison without a retry. Raw history is 34–184 KB.

One shared Luna transport and evaluator, six actions per episode, a seeded frozen
schedule, and no response resampling. All four ordinary summaries are constructed
before recipients run. Their full metered generation costs belong to the summary
condition. Compiler CPU time is measured; it has no API charge. Public runner CPU
time is reported without assigning a dollar price. Thus the primary endpoint is
correct tasks per total metered conservative API dollar, not total economic cost.

Correctness requires explicit completion, passing public verification on the final
revision, passing withheld bug tests, and no failure of the original upstream API
regression tests. The first action must recover current revision, failed edit IDs,
editing scope, and verification state. Lost required state, stale verification
treated as current, regressions, or false completion veto advancing the capsule.
This tests declared required fields; it is not proof against all possible omissions.

Predeclared decision: advance only if capsule accuracy is at least both controls,
correct tasks per API dollar is at least 15% higher than both controls, and no
capsule veto or invalid comparison occurs. Otherwise do not advance. Four tasks
support a descriptive go/no-go decision, not statistical confirmation of general
superiority. Public task novelty to the model is not guaranteed. Any apparatus
failure leaves this experiment incomplete; do not silently reclassify or resample.

Six focused tests passed: four real fixture checks, scope/corruption checks, and a
mocked end-to-end trace/cost replay with tampering rejection. Model mocks are not
empirical results. Saved candidates are rescored and complete traces reconciled in
a separate audit step; the audit shares deterministic execution/evaluation code.

Plan: examples/heldout-capsule-plan-20260909.json
SHA256: 2d413c6a907c06931a1de497f2a0dafb20ce194bbc712ecf82a9d99fba25cf08
Archive: examples/heldout-real-bugs-v1-20260909.zip
SHA256: c1432348781fd53d08a26c66cba58148d4c0ae1a289df12360186e2406991c55

Cumulative guard starts at $0.928598200 of the existing $5 authorization. Up to
76 requests: four constructors plus twelve six-action recipients. The guard
retains its September 9 verified rates and September 10 UTC expiry. The one-shot
workflow pins the preceding commit and rejects reruns, with shared concurrency.
Secrets are removed from the environment before any candidate test execution.
This remains a trusted development bench, not a hostile-code security sandbox.

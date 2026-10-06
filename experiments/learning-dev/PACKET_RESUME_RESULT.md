# Completed synthetic continuation pilot — September 9

All nine episode outcomes are available after a documented transport repair and
recovery of the last episode. Cloud replay and a local replay both passed.

| Condition | Verified completion | Exhausted 3 actions | Requested context | False completion |
|---|---:|---:|---:|---:|
| History | 1/3 | 2 | 0 | 0 |
| Packet only | 2/3 | 1 | 0 | 0 |
| Objective only | 0/3 | 0 | 3 | 0 |

Both history and packets completed stable deduplication. Packet-only also
completed the iterator reversal task; history kept requesting tests and exhausted
its action allowance. The zero-value packet episode ran tests, made a redundant
edit, and ran tests again, exhausting its allowance before claiming completion.
No-context episodes correctly asked for missing state. All nine first actions
correctly identified the verification state as unverified or unknown.

This provides a narrow feasibility result: a fresh model interaction used a
trusted packet without the original conversation to resume and verify two small
coding tasks. It does not establish superiority over history, statistical
significance, automatic packet extraction, long-context compression, long-horizon
continuity, or self-improvement. Fixtures are hand-authored and the three-action
limit affects the observed completion count. The audit reuses the deterministic
executor and is a replay/accounting check, not an independent scorer implementation.

The first launch stopped after one settled request. The replacement completed
eight episodes before another duplicate-final parser rejection. Recovery preserved
those eight outcomes, replayed the already-saved ninth episode's first action,
and used one new request to complete it. No completed episode was resampled.
See PACKET_RESUME_RECOVERY.md for commitments and the transport normalization rule.

Continuation work, including the aborted request, added a conservative
$0.008839400 (less than one cent). Cumulative spending is $0.928598200 of the
authorized $5; unresolved reservations are zero. The combined pilot has 20 model
responses, plus the first aborted launch's one response.

Final run: https://github.com/BillyMixNix/Hive/actions/runs/34366967916
Earlier partial run: https://github.com/BillyMixNix/Hive/actions/runs/34366080331
Initial aborted run: https://github.com/BillyMixNix/Hive/actions/runs/34365575353

Saved final evidence: examples/packet-resume-final-evidence.zip
SHA256: 1fc376afbf29b1aa14ea51cf7f39ae654556de32c6c5140471af0b30974e670c

Keep packet-based resumption as a working mechanism. Treat any broader advantage
as an open hypothesis requiring richer, independently specified interruption
tasks and matched information controls. No additional paid run is scheduled.

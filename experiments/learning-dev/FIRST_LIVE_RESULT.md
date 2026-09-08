# First real-provider development trial: INVALID

On 2026-09-08, the GitHub-hosted trial made two actual OpenAI requests using
`gpt-5.6-luna`. The proposer generated a lesson from the recorded Jarvis failure.
The first recipient's adapter then failed, and the episode stopped before any
recipient reached independent evaluation. No lesson entered ordinary guidance.

| Evidence | Recorded result |
| --- | --- |
| Live commit | `ce05060053519e583aa931bf1909f9c93e009260` |
| Source preparation commit | `4ef8240b17f07be68b058850530358e25478e47b` |
| Verdict | INVALID |
| API requests | 2, including the failed recipient request |
| Reported input / output tokens | 740 / 315 |
| Conservative token-charge upper bound | $0.000937 |
| Unresolved spending reservations | $0 |
| Unused portion of the original $5 authorization | At least $4.999063 |
| Independently evaluated recipients | 0 of 9 |
| Normal guidance added | 0 |
| Event ledger | Verified on the runner |
| Offline checks on the runner | 104 passed, 2 skipped, 5 subtests passed |

The API key and generation access worked. This run does not show a learning gain
or a learning failure: the comparison never reached evaluation. It is not RSI
evidence or a current HoH replication.

The candidate principle was to translate inclusive requirements into inclusive
comparisons and check both sides of a boundary along with equality. It remains
an unvalidated candidate, not an accepted lesson.

## Failure and follow-up

The original report records `model transport or usage failure; episode invalid`.
Both requests had valid model/tier and token accounting sufficient to settle the
spending reservations. The export did not preserve the precise cause of the
recipient failure, so a more specific diagnosis cannot be justified from it.

A subsequent offline patch preserves fixed, redacted failure labels in exported
transport usage and keeps the first cause when the controller encounters the
retry block. Its targeted transport/spending checks passed: 37 tests. It makes no
claim to repair the unknown original cause. No paid retry was run. The original
episode, evidence, suite consumption, spending, and verdict remain unchanged.

Before further paid diagnostics, carry forward the original spending ledger;
do not reset the allowance to $5 or replay the consumed confirmation episode.

## Original evidence

- [Workflow run and downloadable artifact](https://github.com/BillyMixNix/Hive/actions/runs/34200636404)
- [Recorded report](results/2026-09-08/report.json)
- [Conservative spending journal](results/2026-09-08/spending.jsonl)
- [Protocol and verified pricing source](CLOUD_TRIAL.md)

The downloaded ZIP SHA-256 is
`ce010a2e42e7419ad8a464c0e3feec8d15e03cdcfbf3c4924bf4f433c1ab6858`.
It matches GitHub's artifact digest, and every internal evidence checksum was
verified after materialization. The ZIP includes the SQLite ledger, exported
events, manifest, report, spending journal, and offline verification results.

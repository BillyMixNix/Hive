# First live development trial — 2026-09-08

The completed attempt is **INVALID**, with two real API requests, a generated
candidate lesson, and no evaluated recipient. See [FIRST_LIVE_RESULT.md](FIRST_LIVE_RESULT.md).

This runs the recovered Hive executive and Jarvis learning loop with actual
OpenAI responses. The three cases and source failure are the previously authored
development fixtures. The lesson is generated from the recorded failure; the
scripted lesson and scripted adapter are not used in the live run.

The frozen comparison is nine fresh recipients: three cases, each with baseline,
candidate lesson, and neutral guidance. Each recipient retains its 36-call
allocation. The episode allows at most 325 requests including the proposal.
The existing promotion gate, controller, suite bytes, and seed 42 remain intact.

## Total spending authorization

Billy authorized at most **$5 for the entire first trial**, including failed
requests. This run uses `gpt-5.6-luna`, standard service, text only, no hosted
tools, no retries, and at most 4096 output tokens per request. The official
[model page](https://developers.openai.com/api/docs/models/gpt-5.6-luna), checked
2026-09-08, lists $0.20/M input and $1.20/M output, a 1,050,000-token context,
2x input and 1.5x output above 272K input, and 1.25x input for cache writes.
The page lists `gpt-5.6-luna` without a separate dated snapshot. A response with
a different model identifier is invalid; this is not a claim of immutable weights.

Before each request, the spending journal flushes and fsyncs a reservation of
**$0.5323728**, covering the full context at the highest combined published input
rate and the configured output maximum. Valid measured usage settles at those
same conservative rates, refunding only the unused reservation. An unaccounted
request retains its entire reservation and blocks all further paid requests.
Integer arithmetic prevents rounding below the charge bound. Cached-read
discounts are deliberately not assumed. This is a conservative token-charge
upper bound, not the provider's invoice or a limit on unrelated account activity.

The pricing authorization expires on 2026-09-09 UTC. Existing spending journals
cannot be reopened. The workflow only accepts one designated branch push from
its exact preparation commit and only `run_attempt == 1`; its Python entry point
checks the same event. No manual dispatch, PR inference, or paid rerun is enabled.
If a runner crashes, its request reservation must remain charged to the original
allowance until reconciled; do not create a fresh $5 trial as a retry.

## Evidence and interpretation

The output includes `report.json`, the SQLite ledger, exported events, a source
manifest, the spending journal, and checksums. No key is written to these files.
The GitHub secret is supplied only to the live step and removed from the Python
environment before any recipient tests execute. Checkout does not persist a GitHub
credential. The workflow executes trusted synthetic code on an ephemeral runner;
this is not an OS sandbox against hostile same-user code.

The result can show whether this loop operates with a real provider and whether
this particular lesson meets its development gate. It cannot establish recursive
self-improvement, a reliable learning effect, or replicate the missing current HoH
experiment. Neutral text is character-padded, not token-matched. Rejected or
invalid lessons never enter normal guidance.

Local verification uses mocked HTTP only. Run from this directory:

```sh
python -m pytest -q tests -p no:cacheprovider
```

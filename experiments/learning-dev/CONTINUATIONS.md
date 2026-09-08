# Authorized development continuations — 2026-09-08

Billy authorized continued work: "Ok keep going as long as you need." The
original **$5 total** still includes every failed attempt and diagnostic request.
Each continuation commits the preceding report hash and carries its cumulative
conservative charge into the next spending journal before making any request.
The existing private GitHub secret is reused; no key is written into source.

## Continuation 3: actual response captured

[Run 34202939936](https://github.com/BillyMixNix/Hive/actions/runs/34202939936)
at commit `e518cba77ed97e3a7c1944d25dbfdfcb36b61eb8` stopped INVALID after two
requests. It preserved the public synthetic request and response while omitting
reasoning content, response identifiers and credentials.

The first worker response had two assistant text messages. The commentary
contained a JSON `run_command` action; the final answer contained a JSON `finish`
claim saying pytest had run. Hive had not executed either message. The request
used JSON text mode and did not register native functions. The old adapter
correctly rejected this ambiguous output as `unexpected_output_items`.

This captures the actual fault in this development line. It does not establish
that the earlier missing HoH experiment had the same fault.

| Measure | Continuation 3 | Cumulative attempts 1–3 |
| --- | ---: | ---: |
| API requests | 2 | 6 |
| Input tokens | 736 | 2213 |
| Output tokens | 439 | 1067 |
| Conservative charge upper bound | $0.0011582 | $0.0030271 |
| Unresolved charge reservations | $0 | $0 |
| Evaluated recipients | 0 | 0 |
| Lessons retained | 0 | 0 |

The full artifact ZIP SHA-256 is
`3e6e1d1db6a564da5883ed155eecc4c36155df48fcd884e6d2dd7d4ddadeae7d`.
The report SHA-256 is
`fddd5722c21c7fa55fd238366ca0670dbd373af779f0344fb377d1f01a6f0c26`.
GitHub's archive digest and every internal checksum were verified. The unchanged
[report](results/2026-09-08-cont3/report.json) and
[actual failing response](results/2026-09-08-cont3/responses/response-0002.json)
are preserved here; the latter is also an offline regression fixture.

## Continuation 4: native action transport repair

Before launching, the adapter was changed to register one strict `hive_action`
function for worker calls, force that function and disable parallel calls. Its
action-name enum comes from the initial controller packet's authorized contracts
plus the existing finish protocol. Argument templates are not schemas, so the
wrapper carries an encoded JSON object and leaves existing authority and
argument validation to the recovered controller. No command runs in the adapter.

Exactly one native function call is required. Multiple calls, unknown functions,
unoffered actions, malformed argument objects, refusals and incomplete responses
stop the episode. Additional text cannot become an action or execution evidence.
The native call is converted to the controller's original JSON action. Hive's
actual tool result is supplied in the next stateless transcript. This bridge does
not replay API response IDs or provider reasoning items.

The worker/judge distinction uses an explicit bridge hook. Judges receive no
lesson and no action tools. For JSON-only proposer/judge responses, exactly one
final or legacy unphased message is accepted, with optional labeled commentary;
multiple final/unphased messages and any tool calls remain invalid.

The original recovered controller and seen development suite remain unchanged.
Continuation 4 repeats the full nine recipient evaluations with a 36-call cap
per recipient, 325 total requests and the original spending guard. As a replay,
it cannot promote a lesson; any otherwise passing gate is REPLAY_GATE_PASSED.
This tests integration and measures behavior on seen development fixtures, not
unseen confirmation or RSI.

### Recorded result: REJECTED, all nine evaluations completed

[Run 34204276223](https://github.com/BillyMixNix/Hive/actions/runs/34204276223)
at commit `0eab531bc05234d64169ddc57d304adc08fb3c88` passed 122 offline tests
(2 skips, 5 subtests), then completed 19 live API requests. All 18 worker
responses were accepted native calls. No transport failure occurred.

| Independent protected-test result | Baseline | Proposed lesson | Neutral guidance |
| --- | --- | --- | --- |
| Inclusive capacity repair | Fail | Fail | Fail |
| Inclusive deadline transfer | Fail | Fail | Fail |
| Correct signed addition retained | Pass | Pass | Pass |

All nine candidates were evaluated with valid test exits, and each retained its
original source bytes. The lesson was rejected, transfer gain was zero and no
lesson entered ordinary guidance. The event ledger verified.

The recorded requests show two Reproducer calls per recipient. Source inspection
explains why the all-green public fixtures cannot advance: the unchanged
Reproducer gate requires a failing command or a previously established external
oracle counterexample. The demo's boundary failures exist only in its protected
evaluation, which is deliberately withheld from recipients. This is an apparatus
mismatch, not a measured inability of the model to change a comparison operator.

This attempt used 12,709 input and 1,024 output tokens, with a conservative charge
upper bound of **$0.0081977**. The cumulative bound across all four attempts is
**$0.0112248** for **25 API requests**, with no unresolved reservation.

The full artifact ZIP SHA-256 is
`9d1d7499ad1f3b3c5e341f72b470462e9b00f38a237328b7a470fb78a26aba39`.
Its digest and all 25 internal checksums verified. The unchanged
[report](results/2026-09-08-cont4/report.json) and public response traces are
preserved separately from the earlier failures.

## Continuation 5: visible-failure repair probe

Before launch, a separate fixture was committed in
[repair-probe.json](examples/repair-probe.json), SHA-256
`c6676e972b10de0ac475d0b8ae435877cf67dfca6f7053b906013e58cbe54a81`.
Its public tests include the failing equality case; protected evaluation checks
the complete 11-by-11 grid of integer quantities and capacities from -3 through 7.
The previous learning suite and all its results remain unchanged.

The same controller and repaired native adapter receive this one task, no lesson
and at most 36 model calls. The existing $5 guard carries the entire $0.0112248
prior upper bound. Verification requires a genuine initial test failure, a source
change, unchanged public tests, a passing independent evaluation and the
controller's SATISFIED decision. Full controller files and final source are kept.

This is a development integration test. It can report REPAIR_VERIFIED or
REPAIR_NOT_VERIFIED; it cannot promote a lesson or establish learning or RSI.

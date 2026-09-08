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

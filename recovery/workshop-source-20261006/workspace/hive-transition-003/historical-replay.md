# Historical replay after the structural repair

`historical_replay.py` replays 36 preserved responses with **zero model calls**: all 30 planner responses from the 16 factorial Hive trials; four responses from the two TRANSITION-001 live revisions; two context-complete TRANSITION-002 responses. It compares the final TRANSITION-002 controller with the repaired controller in separate Python processes. Originals are read-only.

The [machine-readable result](evidence/historical-replay.json) preserves IDs, schema validity, acceptance, dispatch eligibility, exact rejection text, correction text hashes and correction schemas. Both versions accept only the two already-valid factorial plans (ordinals 6 and 26). All 34 currently invalid plans remain invalid. In particular, revision-1 TRANSITION-001 overlap is judged against the already-repaired TRANSITION-002 validator; the original revision-1 dispatch is not converted into a legitimate success.

| Measurement | Before | After |
|---|---:|---:|
| Controller-accepted plans | 2 | 2 |
| Controller-rejected plans | 34 | 34 |
| Initial generation-schema-valid responses | 11 | 3 |
| Changed rejection messages | — | 0 |
| Changed correction prompt text hashes | — | 0 |
| Newly dispatch-eligible historical plans | — | 0 |

The generation language now excludes eight preserved outputs it formerly permitted: factorial 12/19 first attempts and both responses of each of TRANSITION-001 revisions 1/2 and TRANSITION-002. It does not reinterpret or repair those outputs. Some failures were already outside the schema or remain unrelated to one-file ownership; their original outcomes are retained.

The deliberate change is in correction **generation constraints**, not the error prose: one-file scopes carry mutually exclusive ownership branches into the one normal correction call. Multi-file schema behavior is unchanged. These are deterministic interface results, not successful software runs.

# Trial 003 execution log

This log is chronological. Failed/inconclusive attempts are preserved rather than rewritten as successful runs.

## 2026-08-25 — setup

Created draft PR #25 from frozen Hive `main` commit `d0ee22781336331c1d387b7fafe37fcf744be60e` on branch `trial-003-c4-causal-state`.

Added:

- frozen Trial 003 protocol;
- c4 boundary-analysis prediction ledger;
- tiny transition-equivalence harness;
- frozen c4/self-host baseline tests;
- dedicated Trial 003 CI gate.

## Dedicated gate run 1 — environment failure

Workflow run: `32814744609`

Result: **INCONCLUSIVE / FAIL-CLOSED**.

The dedicated workflow installed only `pytest`, but repository-level `tests/conftest.py` imports `hive_llm`, which imports `requests`. Pytest stopped during collection with `ModuleNotFoundError: No module named 'requests'` before any Trial 003 contract executed.

No evidence was salvaged from this run.

Repair: add `requests` to the dedicated gate's test-runner dependencies. This is trial infrastructure only; no subject behavior changed.

## Dedicated gate run 2 — harness-definition failure

Workflow run: `32814921288`

Result: **FAIL (trial harness), preserved**.

Observed: 9 tests passed and 1 failed.

The hidden-input-cursor adversarial test expected `READ` to be the shortest separator, but the search returned `NOP`. The implementation was incorrectly comparing *full* successor snapshots. Because the intentionally omitted cursor already made the two full starting states different, a NOP preserved that difference and was falsely accepted as a separator.

This exposed an important test-definition error:

> A useful hidden-authority separator must show that equal **represented** states cease to be equal under that same representation after identical causes. Merely observing that the hidden full states were already different is tautological.

Repair: `shortest_separator` now compares the selected projection before and after each cause sequence. The full snapshot remains available for restore/authority checks, but it is not used to manufacture a separator from an already-hidden distinction.

## Dedicated gate run 3 — scoped baseline success

Workflow run: `32815022096`

Result: **PASS, scoped to T0/T1 infrastructure.**

Observed: **10/10 tests passed in 0.39 s**.

The passing set includes:

- frozen c4 and hello.c Git-blob identity verification;
- host compilation of frozen c4;
- direct `c4 hello.c` execution;
- one-level self-host continuation `c4 c4.c hello.c`;
- two-level self-host continuation `c4 c4.c c4.c hello.c`;
- fresh-process address-sensitive `-s` trace probe;
- deliberate hidden-input-cursor collision;
- shortest transition separator discovery;
- full snapshot distinction once cursor is represented;
- detached snapshot behavior;
- recursive canonical memory ordering;
- fresh restore continuation equality at every suffix step.

The test count is 10 because several of the tiny-machine properties are grouped into the six transition-harness tests and four c4 baseline/probe tests.

## Current evidence boundary

### PROVEN

For the committed Trial 003 harness and frozen c4 subject, the dedicated physical CI run reproduced the deliberately constructed hidden-state collision, corrected a flawed separator definition, and then passed the scoped T0/T1 gate including frozen c4 direct and two-level self-host execution.

### SUPPORTED

The transition-equivalence formulation is operational enough to generate a shortest identical-cause separator on a controlled machine, and c4 immediately exposes the predicted host-address portability hazard at its diagnostic representation boundary.

### NOT YET TESTED

No result has yet been earned for RuneRay v0.7 integration, c4 VM checkpoint/restore, compiler/parser checkpoint/restore, or self-host checkpoint continuation.

The exact `runeray_engine_v0_7.zip` supplied in the chat exists as the frozen intended subject but is not byte-addressable from the GitHub Actions workspace used by this PR. The run therefore remains **IN PROGRESS**, not a Trial 003 overall PASS.

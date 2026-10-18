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

## Frozen RuneRay v0.7 intake and T4

The exact archive was later committed to the branch at:

`experiments/trial003/runeray_engine_v0_7.zip`

Observed archive SHA-256:

`0d7ff472a1a18a788cb12406865daf5e2c273a3cf7dbf9a7acfa83e9d075e1f0`

The archive extracted successfully in GitHub Actions.

Frozen RuneRay baseline:

- `npm test`: PASS
- `npm run build`: PASS

The T4 adversary then reproduced four frozen-target failures:

1. entity insertion history selects update order despite equal canonical snapshots;
2. unadapted arbitrary custom-system state is hidden authority;
3. restore retains entities absent from the restored snapshot;
4. entity update behavior is not rebound by fresh restore.

Positive controls passed for built-in fresh restore and an explicitly adapted custom system.

No frozen RuneRay source was modified by these probes.

## Dedicated gate run 14 — actual c4 cross-domain adversary

Workflow run: `32821851924`

Result: **PASS, scoped cross-domain transfer evidence.**

The frozen c4 subject remained pinned at commit:

`2feb8c0a142b2e513be69442c24af82dbaf41a25`

The adversary preregistered five causal-state predictions derived from the same Hive transition-equivalence doctrine used on RuneRay. All **5/5** reproduced:

1. **compiler symbol-table history separator** — identical remaining suffix, `int x;` vs `int y;` consumed history; left executed successfully, right failed `undefined variable`;
2. **compiler line-history observation separator** — identical invalid remaining suffix produced diagnostic line `1` vs line `4` solely from consumed newline history;
3. **raw host pointer representation is noncanonical** — fresh `c4 -s hello.c` runs had equal opcode projection but different raw trace/operand representation;
4. **VM OPEN depends on host fd table** — same c4 program and same file returned fd `3` normally and fd `4` when inherited fd 3 was occupied;
5. **VM READ depends on host file cursor phase** — same c4 program, same file bytes, same logical fd 3 returned `65` (`A`) at cursor 0 and `66` (`B`) at cursor 1.

Allocator stress, not counted as an additional hard preregistered contract, ran the same malloc program four times in fresh processes and observed **4 distinct pointer values**.

Positive control `hello.c` remained successful.

The machine-readable cross-domain evidence was written to `c4_adversarial.json` and uploaded with the Trial 003 artifact.

## Current evidence boundary

### PROVEN

For these frozen subjects and contracts, the Hive transition-equivalence method produced executable hidden-state/environment predictions in both RuneRay and c4, and the c4 cross-domain adversary reproduced all five preregistered predictions.

### SUPPORTED

Hive's causal-state / authority / transition-equivalence method transfers across at least two materially different stateful software domains: a game/simulation engine and an independently authored compiler/VM.

### NOT PROVEN

- no matched conventional baseline has yet established Hive superiority;
- no complete portable c4 checkpoint/restore implementation has been built;
- no serialized mid-self-host checkpoint continuation has been demonstrated;
- no claim of arbitrary-domain or non-software generality is earned.

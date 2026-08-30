# Hive External Engineering Trial 003 — cross-domain causal-state transfer

## Current disposition

**PASS, scoped — Hive's transition-equivalence method transferred from RuneRay/game-engine work to the independently authored `c4` compiler/VM and produced preregistered executable causal-state witnesses.**

This is **not** a claim that Hive is generally superior to ordinary engineering, and it is **not** a claim of universal causal-state sufficiency.

## Frozen subjects

- Hive base commit: `d0ee22781336331c1d387b7fafe37fcf744be60e`
- RuneRay archive: `experiments/trial003/runeray_engine_v0_7.zip`
- RuneRay archive SHA-256: `0d7ff472a1a18a788cb12406865daf5e2c273a3cf7dbf9a7acfa83e9d075e1f0`
- RuneRay package version: `0.7.0`
- c4 subject: `rswier/c4` commit `2feb8c0a142b2e513be69442c24af82dbaf41a25`
- c4 source Git blob: `0340255f0031ee36bf3f38bc171a4fde8922bc75`
- hello.c Git blob: `ab0650697c4c620bc0a560af5d7582be4f569bef`

RuneRay v0.8 is quarantined and is not part of this frozen trial.

## Invariant under test

> Represented-equivalent authoritative state + the same next cause must produce represented-equivalent authoritative successors.

The operating question is not merely whether a snapshot contains many fields. It is whether supposedly irrelevant omitted history, phase, configuration, representation, or environment can still choose the future.

---

# Part A — frozen RuneRay v0.7 transfer source

## Baseline verification

On GitHub Actions, the exact frozen RuneRay archive was extracted successfully.

- `npm test`: PASS — `RuneRay v0.7 Hive merge + gameplay foundation tests passed.`
- `npm run build`: PASS — generated `dist/runeray_engine_systems_lab.html` at 111,987 bytes.
- Existing Trial 003 c4/tiny-machine gate: 10/10 PASS.

The frozen RuneRay baseline was therefore healthy before adversarial probing.

## RuneRay T4 adversarial results

### Positive control — built-in fresh restore

**PASS.** A built-in-only state snapshot restored into a fresh engine was immediately byte-equivalent and remained byte-equivalent after the same continuation.

### Failure 1 — entity insertion history controls future truth

**FAIL on frozen v0.7.** Two engines contained the same entities and serialized to equal canonical state, but opposite live `Map` insertion histories selected different entity update order. The same next `update(fixedStep)` caused successor divergence.

Observed witness:

- before snapshot equality: `true`
- after snapshot equality: `false`
- left successor: `a.state.v = 1`, `b.state.v = 1`
- right successor: `a.state.v = 0`, `b.state.v = 1`

### Failure 2 — arbitrary custom-system mutable state remains hidden

**FAIL on frozen v0.7.** `RuneRayEngine.addSystem()` can accept mutable authoritative systems whose state is not automatically represented. Equal core snapshots with different custom-system phases received the same update and diverged:

- left camera x: `0.5`
- right camera x: `1.5`

### Positive control — explicit state adapter

**PASS.** When the custom system explicitly implemented `serialize()` / `restore()` and was registered with `registerStateAdapter()`, fresh restore preserved phase and continuation remained equivalent.

### Failure 3 — restore does not remove post-snapshot entities

**FAIL on frozen v0.7.** Restoring an older snapshot left later-created entities resident but disabled/hidden. Post-restore authoritative serialization therefore did not equal the captured snapshot.

### Failure 4 — entity transition behavior is absent from fresh snapshots

**FAIL on frozen v0.7.** An entity `update` callback was not represented/rebound. Source and restored snapshots were immediately equal, but under the same next update the source incremented `state.n` and the restored entity did not.

---

# Part B — actual Hive cross-domain transfer to `c4`

The c4 adversary was written against the frozen external subject and then executed in GitHub Actions. It did not modify the frozen c4 source. The target remained the independent single-file compiler/VM.

The same Hive doctrine used on RuneRay was applied unchanged:

1. identify causal state, transformations, observations, representations, and environment;
2. deliberately construct a reduced representation that calls two realities equivalent;
3. apply an identical future cause or identical remaining input;
4. look for successor divergence;
5. treat any separator as evidence that omitted state or environment participates in authority.

## c4 positive baseline

Before the adversarial transfer:

- frozen source identities matched the pinned Git blobs;
- host compilation succeeded;
- direct `c4 hello.c` succeeded;
- one-level self-host `c4 c4.c hello.c` succeeded;
- two-level self-host `c4 c4.c c4.c hello.c` succeeded;
- the dedicated Trial 003 baseline/harness remained 10/10 PASS.

The cross-domain probes therefore ran against a functioning external subject.

## T5/T6 cross-domain adversarial contracts

### C4-1 — symbol-table history is authoritative compiler state

**VIOLATION REPRODUCED.**

Two source histories ended at the exact same future suffix:

`int main(){ return x; }`

The remaining suffix was byte-identical and had SHA-256:

`32ab39785e892aa0b1601f6c97995c4b589f4e2b2fae6a9060fce62436f57c70`

Only already-consumed history differed:

- left prefix: `int x;`
- right prefix: `int y;`

Results under the same remaining source:

- left: successful execution, `exit(0)`
- right: compiler failure, `undefined variable`, process return 255

**Interpretation:** a representation consisting only of the current/future source bytes is not transition-complete. The symbol table is causal compiler state even though it is historical bookkeeping relative to the remaining source.

### C4-2 — chronology changes authoritative diagnostics

**VIOLATION REPRODUCED.**

The same invalid suffix was compiled after different already-consumed newline histories. Both failed for the same undefined identifier, but the authoritative diagnostic changed:

- left diagnostic line: `1`
- right diagnostic line: `4`

**Interpretation:** if diagnostics are part of the observation contract, source chronology/line phase is authoritative observation state. This mirrors the Hive distinction between semantic transition state and observation state.

### C4-3 — raw host pointers are noncanonical representation

**VIOLATION REPRODUCED.**

The same frozen `hello.c` was compiled twice in fresh processes with `c4 -s`.

- opcode projection: equal
- raw trace bytes: different
- pointer-bearing operand differences: observed

**Interpretation:** the semantic instruction structure remained stable while host-layout-dependent absolute addresses changed. Raw addresses therefore cannot serve as portable canonical identity for fresh-process checkpoint state. A portable state contract needs region-relative pointer representation / relocation or an equivalent explicit binding model.

### C4-4 — host file-descriptor allocation is causal VM environment

**VIOLATION REPRODUCED.**

The exact same c4 program opened the exact same file. The only changed condition was inherited host descriptor occupancy.

Observed `OPEN` result:

- normal environment: fd `3`
- inherited fd 3 already occupied: fd `4`

The source program hash and target file hash were identical.

**Interpretation:** the host descriptor table participates in the VM transition unless it is modeled as explicit environment/cause. Treating only c4's local registers/memory as authoritative would be incomplete for programs allowed to call `OPEN`.

### C4-5 — host file cursor is hidden transition phase

**VIOLATION REPRODUCED.**

Both runs inherited logical fd `3` pointing to the same two bytes, `AB`, and executed the same c4 `READ` program. Only the host file cursor differed.

Observed read value:

- cursor at byte 0: `65` (`A`)
- cursor at byte 1: `66` (`B`)

**Interpretation:** fd identity and file contents are insufficient. File offset is causal environment phase. This is the same structural class as RuneRay's hidden simulation accumulator: a small unrepresented phase variable chooses the next transition.

### Allocator stress observation

Four fresh executions of the same c4 malloc program produced **4 distinct raw heap pointer values**.

This is not counted as an additional preregistered hard contract because the raw-trace pointer test already covers the portability claim, but it independently supports the same conclusion: host addresses are representation, not portable semantic identity.

## Cross-domain result

All **5/5 preregistered c4 causal-state violations were reproduced** in the dedicated physical CI run. The frozen hello/self-host controls remained healthy.

This is the first Trial 003 result that directly answers the Hive transfer question rather than merely improving RuneRay.

---

# Evidence assessment

## PROVEN

For the frozen subjects and harnesses in this PR:

1. RuneRay v0.7 contained four deterministic transition-equivalence/restore failures while its own functional regression and build passed.
2. The same Hive transition-equivalence ontology generated executable predictions on the independently authored `c4` compiler/VM.
3. All 5 preregistered c4 cross-domain causal-state probes reproduced their predicted separators/environment dependencies.
4. c4's symbol table, diagnostic chronology, host address representation, descriptor table, and file cursor were each shown to participate in future compilation/execution/observation under the stated contracts.

## SUPPORTED

> **Hive's causal-state / authority / transition-equivalence method transfers across at least two materially different stateful software domains: a game/simulation engine and an independently authored compiler/VM.**

This is stronger than saying the vocabulary merely sounds applicable. The transfer produced frozen, machine-executed falsifiable contracts with positive controls.

## PLAUSIBLE

The broader Hive thesis — that useful comprehension can be operationalized as compressed causal structure capable of generating tests in unfamiliar domains — is now more plausible than before Trial 003.

## NOT PROVEN

- Hive is not proven superior to ordinary engineering because no matched neutral baseline has yet attacked the same frozen c4 target under the same objective and budget.
- Hive is not proven generally cross-domain across arbitrary non-software disciplines.
- A complete serialized fresh-process c4 checkpoint/restore implementation has not been built. The current evidence instead identifies why a naive one is insufficient: raw pointer relocation and external host state must be modeled explicitly.
- Self-host execution from a serialized mid-VM checkpoint has not been demonstrated.
- No universal causal-state sufficiency claim is earned.

---

# Scientific next moves

1. **Matched conventional baseline:** give the same frozen c4 commit and a neutral deterministic-state/checkpoint objective to a non-Hive review with the same constraints. Compare defect classes/predictions, test strength, false positives, patch size, and effort.
2. **Portable c4 checkpoint prototype:** encode text/data/stack/source pointers as region+offset rather than raw host addresses and make syscall environment explicit. Attempt fresh-process restore on a no-I/O program first, then `hello.c`, then the self-host chain.
3. **New non-software domain:** only after the matched baseline, transfer the same Hive doctrine to a domain whose surface structure is not already an obvious machine-state problem.

Do not modify the frozen subjects in place. Candidate repairs/adapters must remain separate from frozen evidence.

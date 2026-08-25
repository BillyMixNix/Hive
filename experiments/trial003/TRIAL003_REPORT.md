# Hive External Engineering Trial 003 — RuneRay v0.7 causal-state sufficiency

## Current disposition

**IN PROGRESS — frozen T4 baseline falsified; no candidate repair has been credited yet.**

This report preserves the observed frozen-target evidence before any RuneRay repair is attempted.

## Frozen subjects

- Hive base commit: `d0ee22781336331c1d387b7fafe37fcf744be60e`
- RuneRay archive: `experiments/trial003/runeray_engine_v0_7.zip`
- RuneRay archive SHA-256: `0d7ff472a1a18a788cb12406865daf5e2c273a3cf7dbf9a7acfa83e9d075e1f0`
- RuneRay package version: `0.7.0`
- c4 subject: `rswier/c4` commit `2feb8c0a142b2e513be69442c24af82dbaf41a25`

The v0.8 upload is not part of this trial.

## Invariant under test

> Represented-equivalent authoritative state + the same next cause must produce represented-equivalent authoritative successors.

If two byte-equivalent/canonically equivalent snapshots can receive the same next authoritative cause and diverge, the representation is missing causal state, configuration, history, or behavior.

## Baseline verification

On GitHub Actions, the exact frozen RuneRay archive was extracted successfully.

- `npm test`: PASS — `RuneRay v0.7 Hive merge + gameplay foundation tests passed.`
- `npm run build`: PASS — generated `dist/runeray_engine_systems_lab.html` at 111,987 bytes.
- Existing Trial 003 c4/tiny-machine gate: 10/10 PASS.

The dedicated gate therefore had a healthy frozen baseline before adversarial T4 probing.

## T4 adversarial results

The dedicated adversary used headless RuneRay engines and preserved the frozen archive unchanged.

### Positive control — built-in fresh restore

**PASS.** A built-in-only state snapshot restored into a fresh engine was immediately byte-equivalent and remained byte-equivalent after the same continuation.

This demonstrates that the harness is not simply declaring every restore invalid.

### Failure 1 — entity insertion history controls future truth

**FAIL on frozen v0.7.**

Two engines were created with the same two entities and the same entity states/callback definitions, but opposite `Map` insertion order. `serializeCoreState()` sorted entity snapshots by ID, so the two represented states were equal.

`EntitySystem.update()` iterated the live `Map` insertion order. Under the same next `update(fixedStep)` cause, the entities executed in different orders and the successor snapshots diverged.

Observed witness:

- before snapshot equality: `true`
- after snapshot equality: `false`
- left successor: `a.state.v = 1`, `b.state.v = 1`
- right successor: `a.state.v = 0`, `b.state.v = 1`

This is a direct transition-equivalence violation caused by unrepresented historical insertion order.

### Failure 2 — arbitrary custom-system mutable state remains hidden

**FAIL on frozen v0.7.**

`RuneRayEngine.addSystem()` accepts arbitrary systems. Their mutable state is not automatically represented in `serializeCoreState()`.

Two engines with identical core snapshots but custom systems at different internal phases received the same next `update()` cause and diverged:

- before snapshot equality: `true`
- after snapshot equality: `false`
- left camera x: `0.5`
- right camera x: `1.5`

This reproduces the unresolved custom-system authority seam predicted after Trial 002.

### Positive control — explicit state adapter

**PASS.** When the same custom system explicitly implemented `serialize()` / `restore()` and was registered with `registerStateAdapter()`, fresh restore preserved its mutable phase and the same next update remained equivalent.

This shows that RuneRay already contains a viable explicit mechanism for this class of authority; the current problem is that `addSystem()` does not require or enforce the contract for authoritative systems.

### Failure 3 — restore does not remove post-snapshot entities

**FAIL on frozen v0.7.**

An older snapshot containing only entity `kept` was restored into an engine that also contained a later entity `later`.

`EntitySystem.restore()` did not delete entities absent from the snapshot. It left `later` resident and merely set `enabled=false` and `visible=false`.

The restored serialized state therefore did not equal the authoritative snapshot being restored.

This means save/load is not an exact authoritative rollback when the live engine accumulated entities after capture.

### Failure 4 — entity transition behavior is absent from fresh snapshots

**FAIL on frozen v0.7.**

An entity with an `update` callback that increments `state.n` was captured. A fresh engine restored the snapshot and was immediately represented as equal to the source.

The callback itself is not serialized. Under the same next `update()` cause:

- source `clock.state.n`: `1`
- restored `clock.state.n`: `0`
- successor snapshots diverged.

This demonstrates that transition behavior/configuration participates in authority when it can alter future state. A full continuity contract must either represent/rebind such behavior explicitly or declare it fixed outside the snapshot and verify that binding during restore.

## Evidence assessment

### PROVEN

For frozen RuneRay v0.7, the Trial 003 transition-equivalence probe reproduced four deterministic causal-state failures while the engine's own regression suite and build passed.

The strongest new witness is that two byte-equivalent canonical snapshots with different hidden entity insertion histories diverge after the same next engine update.

### SUPPORTED

The Hive transition-equivalence model continues to expose authority/continuity defects that ordinary functional regression did not catch, and RuneRay's explicit state-adapter mechanism appears capable of repairing at least the custom-system mutable-state class when used deliberately.

### NOT YET EARNED

- no candidate RuneRay repair has yet been credited;
- no repeated repaired-run stability result has been earned;
- c4 compiler/VM checkpoint/restore has not yet been implemented;
- no T5/T6 self-host checkpoint continuation claim has been earned;
- no general superiority claim over ordinary engineering is earned.

## Next minimal repair targets

1. Make authoritative entity update order stable (for example, stable ID order) or represent the order if order itself is semantic.
2. Make restore exact for entity membership rather than retaining absent historical entities in authoritative serialization.
3. Require authoritative custom systems to provide/register state adapters, or explicitly classify non-adapted systems as outside save/replay authority and fail closed when full-state serialization is requested.
4. Introduce an explicit behavior-definition/rebinding contract for entity `update` and interaction behavior before claiming fresh-process authoritative restore.

Do not modify the frozen archive in place. Any repair must be evaluated as a separate candidate derived from this frozen input.

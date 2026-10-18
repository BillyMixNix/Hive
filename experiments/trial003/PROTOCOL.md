# Hive External Engineering Trial 003 — Causal-State Sufficiency on c4

Status: **IN PROGRESS / FAIL-CLOSED**

## Frozen subjects

- Hive/RuneRay subject: `runeray_engine_v0_7.zip` supplied by the experiment owner. The archive must be imported byte-for-byte before any RuneRay result may be claimed.
- External machine: `rswier/c4`
- c4 commit: `2feb8c0a142b2e513be69442c24af82dbaf41a25`
- c4 source Git blob: `0340255f0031ee36bf3f38bc171a4fde8922bc75`
- hello.c Git blob: `ab0650697c4c620bc0a560af5d7582be4f569bef`

No c4 branch tip or floating dependency may substitute for the frozen commit.

## Primary invariant

If two authoritative states are represented as equivalent, then the same future cause must preserve that equivalence:

`S1 ≡ S2 and C1 = C2  =>  T(S1,C1) ≡ T(S2,C2)`

A divergence witness means at least one of the following is true:

1. authority is hidden;
2. the representation is incomplete;
3. supposedly irrelevant history still controls a future transition; or
4. the declared equivalence relation is too coarse.

## Roles

The trial is evaluated using four separated passes. They may be performed by separate agents when an agent runner is available; no pass may silently perform another pass's evidentiary role.

### Boundary Analyst
Predict all variables that can alter the next authoritative transition: registers, memory, parser state, file/input position, configuration, allocator-derived identities, host addresses, and external mutable definitions.

### Adversary
Construct pairs of states with equal declared representation but distinct hidden history and search for the shortest identical cause sequence that makes them diverge.

### Implementer
Make only the smallest state-contract/adapter repair necessary to eliminate reproduced violations. No unrelated RuneRay or c4 feature work.

### Auditor
Independently check frozen inputs, baseline behavior, adversarial witnesses, repair scope, repeatability, and evidence labels. Reject any PASS if a required input was unavailable or a run was salvaged.

## Ladder

### T0 — Frozen external baseline

1. Fetch c4 and hello.c only from the frozen commit.
2. Verify their Git blob identities locally.
3. Compile c4 with the host C compiler.
4. Run:
   - `c4 hello.c`
   - `c4 c4.c hello.c`
   - `c4 c4.c c4.c hello.c`
5. Each chain must execute hello and terminate successfully.

This establishes only that the external subject is executable in the trial environment.

### T1 — Tiny transition machine

Before c4 integration, verify the transition-equivalence harness itself on a minimal deterministic instruction machine with explicit program counter, accumulator, stack, memory, input cursor, and immutable instruction semantics.

The harness must include a deliberately incomplete projection and demonstrate that it can discover a hidden-state divergence before the projection is repaired.

### T2 — History collision

Create two machines through different construction/allocation histories that serialize to an equal candidate snapshot. Apply the exact same next cause. Any divergent authoritative successor is a witness.

### T3 — Mid-execution restore

Run N transitions, capture detached canonical state, continue the original, restore into a fresh machine/process, then replay the same causes. Compare every subsequent authoritative state, not merely final user-visible output.

### T4 — c4 VM execution boundary

Adapt the c4 VM state into a process-independent authority representation. Investigate at minimum:

- program counter and code position;
- accumulator;
- stack/base pointers and stack contents;
- code/text image;
- data image;
- host pointer/address relocation;
- input/argv state;
- external/system-call effects.

Host addresses must not be mistaken for semantic identity. If the adapter uses offsets/handles, their base/meaning must be fixed by the contract.

### T5 — c4 compiler/parser boundary

Extend the boundary to lexer/parser/codegen state, including at minimum:

- source cursor and line state;
- current token and token value;
- symbol table meaning;
- type/local state;
- emitted-code position;
- data-area position;
- parser lookahead/history that changes the next transition.

Same canonical compiler state plus the same next source cause must produce equivalent successor state.

### T6 — Self-host continuation

Only after T1–T5 pass, checkpoint and restore inside a self-host chain and require the restored continuation to match an uninterrupted continuation through execution of hello.c.

## Mandatory adversarial contracts

1. Hidden program counter/register state.
2. Omitted stack contents.
3. Equivalent memory built through different insertion/construction histories.
4. Different allocator histories.
5. Host pointer addresses differing across fresh processes.
6. Hidden file descriptor/input cursor state.
7. Hidden parser lookahead/token state.
8. Hidden symbol-table meaning/history.
9. Snapshot aliasing after capture.
10. External mutable configuration changing the same next transition.
11. Save/load into a fresh process.
12. Repeated replay from one frozen snapshot.
13. Snapshot bytes remain detached after live-state mutation.
14. Full-authority equivalence is never silently replaced by a purpose-specific projection.
15. Search for the shortest identical future cause that separates two equal represented states.

## Outcome rules

### PASS
All required frozen inputs are present; selected baseline violations are reproduced rather than guessed; candidate repairs are narrow; all selected adversarial contracts pass; repeats are deterministic; and the Auditor accepts the evidence.

### FAIL
A required authority boundary cannot satisfy transition equivalence under the stated contract, or a candidate repair regresses the frozen functional behavior.

### INCONCLUSIVE
Any required subject is unavailable, the environment prevents the physical run, a run is truncated/corrupted, or evidence cannot be reproduced. An inconclusive run must never be promoted to PASS.

## Evidence ceiling

Even a complete PASS can support only the scoped claim:

**SUPPORTED:** the causal-state / transition-equivalence method generalized from RuneRay's native engine domain to an independently authored compiler/VM subject.

This trial cannot prove universal causal-state sufficiency or superiority to ordinary engineering without a matched baseline.

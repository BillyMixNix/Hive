# Trial 003 Boundary Analysis — frozen c4

Role: **Boundary Analyst**

This document is a prediction ledger, not a result ledger. Each item is a candidate source of future-transition authority that the adversarial pass must either represent, fix outside the contract, or prove irrelevant.

## Frozen-source facts

The frozen c4 program combines lexer, parser, code generator, symbol table, bytecode/VM, and a tiny host-call surface in one C process. The important global/compiler variables include:

- `p`, `lp`: current and prior source positions;
- `data`: current data/BSS pointer;
- `e`, `le`: current emitted-code positions;
- `id`, `sym`: current identifier and symbol-table base;
- `tk`, `ival`, `ty`, `loc`, `line`;
- diagnostic flags `src` and `debug`.

The VM loop owns:

- `pc`: program counter;
- `sp`: stack pointer;
- `bp`: base pointer;
- `a`: accumulator;
- the emitted text pool;
- data pool;
- stack pool;
- `argc`/`argv` visible to the interpreted program.

The implementation stores several addresses by casting pointers into its integer word type, then later casts the words back to pointers. Examples include function entry values, global/data addresses, jump targets, return addresses, symbol names, and host argv pointers.

## Predicted causal boundaries

### A. VM register authority — high confidence

`pc`, `sp`, `bp`, and `a` directly control the next VM instruction and operands. Omitting any causally live register can make equal represented states diverge on the next step.

Expected adversarial witness: two equal candidate snapshots with different hidden `pc` or `a`, followed by one identical VM step.

### B. Stack/data/text contents — high confidence

Pointers alone are not sufficient. Future transitions read and write the pointed-to pools. The live ranges and their contents participate in authority.

Expected witness: same register projection, different hidden stack word or data byte, same next load/return/system-call transition.

### C. Pointer relocation meaning — high confidence

Raw absolute host addresses are not stable semantic identities across fresh processes. A process-independent snapshot cannot merely preserve bytes containing absolute malloc/stack/source addresses unless restore also reconstructs an identical address space (which is not a portable authority contract).

Expected repair direction: encode internal references as offsets/handles relative to named regions, then relocate on restore. The exact design must be falsified rather than assumed sufficient.

### D. Source/input phase — high confidence

The lexer/parser future depends on where `p` points, the current token `tk`, token value `ival`, line state, and the data area used for string literals. A text-only representation of the remaining source can still be insufficient if lookahead/current-token state is omitted.

Expected witness: equivalent source bytes with different hidden token/lookahead phase, then one identical parse action.

### E. Symbol-table meaning — high confidence

The symbol table stores token/class/type/value plus temporary saved local metadata. These values determine whether the next identifier is a local/global/function/system symbol, its type, and the generated code.

Insertion history is not automatically semantic, but any history-dependent lookup or saved-local state that changes the next transition is authority.

### F. Emission frontier — high confidence

`e`, `le`, and `data` are moving frontiers into mutable pools. Equal visible prefixes with different hidden frontiers can cause the same next declaration/expression to emit into different locations and produce different later behavior.

### G. Host-call state — medium/high confidence

The VM can invoke `open`, `read`, `close`, `printf`, `malloc`, `free`, `memset`, `memcmp`, and `exit` through host calls. File offsets, descriptor identity, filesystem contents, allocator results, and observable output are external state/effects.

A closed deterministic trial should initially constrain or virtualize this surface. If external effects are allowed, the contract must specify them as causes or authority rather than pretending the VM is closed.

### H. Compiler configuration/word model — medium confidence

The frozen source uses a macro mapping `int` to `long long` on the host. Word size, endianness, pointer width assumptions, compiler/ABI behavior, and arithmetic semantics can affect state interpretation. Trial 003 should fix the execution environment where required and distinguish environment assumptions from serialized mutable state.

## First adversarial order

1. prove the harness can detect one omitted mutable phase variable on the tiny machine;
2. establish c4 direct/self-host baseline;
3. observe raw host-address variance across fresh c4 processes;
4. instrument the VM boundary without changing semantics;
5. create equal projected snapshots with one omitted VM register and obtain a one-step divergence witness;
6. repair representation and repeat;
7. add stack/data/text relocation;
8. only then extend into lexer/parser/compiler authority;
9. finally checkpoint/restore inside the self-host chain.

## Evidence discipline

None of the predicted items above counts as a reproduced defect until an executable witness demonstrates a violation of a declared state/equivalence contract. Static inspection can guide tests but cannot substitute for them.

# Hive recovery status

Updated: 2026-10-06

## Recovery state

This branch is a provenance-preserving staging branch. It is not yet the new canonical Hive runtime.

### Preserved and source-backed

- Sept. 9 operational repair / learning / state-packet lineage (branch base).
- Sept. 8 repair executive and contract-review lineage (ancestor of base).
- Executable Hive reference model, architecture, evidence map, and machine-readable specs,
  imported under `recovery/reference*` from `hive-reference-model`.
- GROW failure-driven Workshop lineage and continuation controller, imported under
  `recovery/lineage/grow/`.
- Project-state ledger lineage, imported under `recovery/lineage/project_state/`.

### Intentionally NOT merged into one runtime yet

The imported reference/GROW/project-state code remains namespaced because these branches
diverged and were developed under different experimental contracts. Their interfaces must be
mapped and tested before any canonical runtime composition.

### Missing original source

The post-Sept. 9 Nix Workshop v0.10.5/v0.11.x source used in later Java/Gradle and transition
experiments is not currently present in this GitHub repository or the accessible ChatGPT file
Library. Preserved reports identify that code and its behavior, but prose is not treated as source.

Recovery requires one of:

1. the original Workshop ZIP/workspace (preferred), or
2. an explicitly new clean-room implementation with new identity, tests, and provenance.

### No-go conditions for merge to main

Do not merge this branch into main until:

- recovered/imported modules have a single documented authority model;
- deterministic recovery tests run from a clean checkout;
- no frozen experiment is mutated in place;
- baseline/candidate/verifier/promotion separation is preserved;
- original post-Sept. 9 Workshop source is recovered or formally replaced;
- a full reproducible gate passes;
- the README and claim registry distinguish demonstrated behavior from hypotheses.

### Next engineering phase

R1 — build interface map and recovery harness:
- define canonical state/evidence interfaces;
- bind the Sept. 9 executive to the reference authority model through adapters;
- test GROW promotion semantics against the canonical promotion boundary;
- add project-state provenance/supersession compatibility tests;
- import original Workshop source if recovered;
- only then create `hive_canonical/` runtime code.

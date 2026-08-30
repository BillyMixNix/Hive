# Hive Experiment 2 — Semantic Authority Decomposition Protocol v1.1

## Disposition and scope

Protocol v1 is sealed as `INVALID_APPARATUS` at evidence commit
`91ce509af612af4404dc107231ce2a3a95c516dd`. Its implementation commit is
`0a4a657a2fcd789aff8ec26e00914be1dcb74152`, and its sealed evidence subtree is
`b1fd56b4f070a0ea45c26b128654385c5cc94073`. It made zero physical model calls.
Protocol v1 and its evidence are not modified, salvaged, or reinterpreted.

Protocol v1.1 is a separately versioned apparatus repair. Its sole material
change is the source-integrity comparison described below. It licenses no
semantic conclusion until its separately sealed run is independently audited.

Protocol ID:
`hive-luna-semantic-authority-decomposition-v1-1`

Protocol version: `1.1`

Run directory:
`.hive/benchmarks/decompression_test/luna-semantic-authority-decomposition-v1-1-001`

Live acknowledgement:
`--acknowledge-frozen-semantic-authority-decomposition-v1-1`

## Sole repair: direct-byte, EOL-aware source integrity

Protocol v1 correctly recorded canonical committed SHA-256 values but compared
those canonical LF bytes directly with raw worktree bytes during the per-call
source guard. The local `hive_llm.py` worktree is mixed-EOL, so v1 failed before
call 1 despite no semantic source change.

Protocol v1.1 persists two maps for every frozen source file:

1. SHA-256 of the canonical bytes returned by `git show HEAD:<path>`.
2. The committed Git blob OID returned by `git rev-parse HEAD:<path>`.

Before and after every physical call, the guard requires:

- current `HEAD` equals the preregistered source revision;
- current `HEAD:<path>` blob OID equals the preflight blob OID;
- SHA-256 of `git show HEAD:<path>` equals the preflight canonical SHA-256.
- direct worktree bytes, after replacing only CRLF byte pairs with LF, equal the
  binary bytes returned by `git show HEAD:<path>` exactly.

The guard does not execute or consult Git clean filters when deciding worktree
equality. A malicious `.gitattributes` rule therefore cannot transform away a
semantic edit. Both preflight maps must be nonempty and have exactly the frozen
source-list keys; missing, empty, or extra entries fail closed. Ordinary CRLF
checkout differences are accepted, while every other byte difference,
committed blob change, revision drift, missing source, or map drift is rejected.

## Frozen experimental contract

Everything that can affect model inference or result interpretation is inherited
unchanged from Protocol v1:

- the exact frozen 20 worlds, questions, options, batches, and oracles;
- conditions `C1`, `K-`, `A-`, `S-`, `KA-`, `KS-`, `AS-`, and `KAS-`;
- pure named-column projection rules and C1/KAS equivalence checks;
- the 8×8 condition schedule and six batches per condition;
- exactly eight stochastic replications and at most 384 physical calls;
- request-plan SHA-256
  `29706dd5d1361f0bdf66a48b58cd00c453850740f740046c169847069a5e6640`;
- schedule SHA-256
  `9b411628e56d291a26b5a0e44bca54577484957b26adc945f38199fabce596cd`;
- OpenAI Responses API, `gpt-5.6-luna`, medium reasoning, 2,048 output tokens;
- tools none, storage false, truncation disabled, current-turn-only context;
- one attempt, no retry, no repair, no fallback, no resume, no overwrite;
- strict batch-cardinality response schema and deterministic grading;
- replication-level exact tests, Holm families, estimand, dispositions, drift
  threshold, KAS comparison, claim ceiling, and $100 authorization ceiling.

No prompt, representation, case, projection, ordering, solver, model setting,
grader, statistic, threshold, disposition, or interpretation is changed.

## Frozen v1 bindings

The v1 implementation files are bound at the implementation commit by both
canonical SHA-256 and Git blob OID:

| File | Canonical SHA-256 | Blob OID |
|---|---|---|
| `kingdom/decompression_semantic_authority_luna.py` | `fef6d2e752d63e7ead42903d0cdf5a3f475715c997420e638a79d0524903a75a` | `cac79dc638e46efea78397582da7ffa5197b5d46` |
| `benchmarks/decompression_test/PROTOCOL_SEMANTIC_AUTHORITY_LUNA_V1.md` | `a76c07669a494cb49c9151b807f0a60448d42eb3e8799daf3df2f7c4a4c5a199` | `41f8126ea1bb58af4e2a4b092c16e14989612794` |
| `tests/test_decompression_semantic_authority_luna.py` | `25927c6b39bcf11167b761ac6d91d774dd6e32adbdbd17e04b8b350afdca9544` | `342bf11f87fe26474e6fa98b1d97e3af74275a4a` |

The sealed v1 result SHA-256 is
`6b4e84636d25cfca7a0835c21ef2897a27b41d1ac97aa2a4b062ba2f753e7afa`.
The sealed v1 evidence-index SHA-256 is
`f2002a27b62553c2cba798941745b0563c72e434d67679f7d17676956d974e0a`.

## Execution chronology

The v1.1 implementation, protocol, and tests must be committed before live
inference. The committed preflight must pass, and the new run directory must not
exist. The run occurs once. No source change is permitted after the first live
call. Any new apparatus failure is preserved and stops the experiment; it is not
patched in place. Implementation and evidence commits remain separate.

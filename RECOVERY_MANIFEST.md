# Hive canonical recovery manifest

Status: ACTIVE RECOVERY — DO NOT MERGE TO main YET
Created: 2026-10-06

## Recovery branch
`recovery/hive-canonical-20261006`

This branch starts from `agent/state-packet-offline-20260909` at
`92efa803e0cd54cad5caffcd569781ffac017717`.

That base is 48 commits ahead of `main` and contains the recovered repair/learning
executive, contract checking, state-packet work, held-out capsule work, packet
resumption evidence, and the Sept. 8–9 experiment lineage.

## Authoritative source lineages

| Lineage | Source ref | Role in recovery |
|---|---|---|
| Operational repair/state-packet spine | `agent/state-packet-offline-20260909` @ `92efa803e0cd54cad5caffcd569781ffac017717` | Recovery base |
| Repair/learning predecessor | `agent/hive-live-trial-20260908` @ `b932a5b9f69d544ebe8d93eeb2f5e9658dc82df2` | Ancestor of recovery base |
| Reference architecture/model | `hive-reference-model` @ `c99343ec9f63ad3fb032a3bc74251e8a618be951` | Imported under `recovery/reference*`; not silently merged into runtime |
| Project-state ledger | `agent/project-state-ledger` @ `c7c9c65a0a0fc82864589d409a4ba959ce436df8` | Pending compatibility review |
| GROW failure-driven workshop | `grow0-failure-driven-workshop-evolution` @ `124c1534fded26fb253360d9e4119e59dbbdab19` | Pending import as historical/evolution lineage |
| GROW continuation | `agent/grow-generation-continuation` @ `3d3010c666dbb83c18a5670101213190226ca242` | Pending import after GROW base |
| Orchestration cockpit | `agent/hive-orchestration-cockpit` @ `41b1c6e87297f73d64d0f78ec5f38ac624f9f01c` | Pending compatibility review |
| Self-diagnosis milestone | `candidate/self-diagnosis-milestone-1` @ `b87e6ae9643a10fb669432eb19cab17cd7b38e3a` | Historical candidate; do not promote without tests |

## Post-GitHub operational lineage

The following later capabilities are evidenced by preserved reports/manuscripts but
their complete source archive is not currently recoverable from this GitHub repository
or the ChatGPT file Library:

- Nix Workshop v0.10.5 / v0.11.x operational controller
- isolated verifier evolution after HWR-000
- Java/Gradle adaptation and external-root execution
- FACTORIAL-002 / TRANSITION-003 / 003R1 / 004 / 005 controller evolution
- child decomposition and scoped ownership used in later Java trials
- verified promotion-bundle machinery used in the later Workshop runs
- current local Ollama runtime policy work

These MUST NOT be reconstructed from prose and then represented as recovered source.
They require either an original archive/workspace or a clean-room reimplementation
with new tests and a new provenance identity.

## Recovery invariants

1. `main` remains untouched until the recovery branch has a reproducible full gate.
2. Model claims do not establish acceptance.
3. Candidate, baseline, verifier evidence, and promotion authority remain separate.
4. Frozen/experimental controllers remain frozen; integration occurs through adapters
   or explicitly versioned replacements.
5. Every imported subsystem records exact source ref/SHA.
6. Negative and invalid experiment evidence is preserved.
7. Missing source is marked missing, never recreated and labeled original.
8. Promotion to canonical Hive requires deterministic tests plus explicit review.

## Current phase

Phase R0: provenance preservation and subsystem inventory.

Next:
- import GROW under a provenance-preserving namespace;
- inspect project-state ledger and orchestration for compatible components;
- add a recovery test harness;
- establish a clean canonical runtime package only after interfaces are mapped;
- locate an original post-Sept. 9 Workshop archive/workspace if available.

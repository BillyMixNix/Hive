# Existing NFRT scope preflight

Attestation: `8c6df7a0c494053f083b4e97a24647b6a066ae024d6402b8ff2c89d0df781b04`. No policy or attestation was changed.

| Task | Authorized write scope | Existing attestation compatible? |
|---|---|---|
| J001 | src/main/java/dev/atmcompanion/state/SnapshotFormatter.java | yes |
| J002 | src/main/java/dev/atmcompanion/knowledge/IngredientAllocation.java | no |
| J003 | src/main/java/dev/atmcompanion/state/Observation.java | no |
| J004 | src/main/java/dev/atmcompanion/execution/ExecutionContext.java; src/main/java/dev/atmcompanion/execution/ExecutionAssessment.java | no |

Each row was checked against the host-attested mutable set and the actual configured_seed validator after appending a harmless comment to the task-authorized files in an isolated baseline copy. Those fixtures are not software-task candidates and were never compiled.

**Future J001–J004 factorial: NOT READY.** J002–J004 require a separately justified attestation policy before another study. No such repair is performed here.

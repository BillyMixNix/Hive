# Source-sensitivity probes

| Probe | Current policy | NFRT input identity equal? | Proposed reuse | Input sections changed |
|---|---|---|---|---|
| baseline | True | True | True |  |
| A-main | False | True | True |  |
| B-J001 | True | True | True |  |
| C-J002 | False | True | True |  |
| D-J003 | False | True | True |  |
| E-J004 | False | True | True |  |
| F-unrelated | False | True | True |  |
| G-package-addition | False | True | True |  |
| H-test | False | True | False |  |
| I-resource | False | True | False |  |
| J-build-comment | False | True | False |  |
| J2-binary-option | False | False | False | inputProperties |
| K-property | False | True | False |  |
| L-access-transformer | False | False | False | inputFiles, optionalInputs |
| M-interface-injection | False | False | False | inputFiles, optionalInputs |
| N-parchment | False | False | False | inputProperties, inputFiles, optionalInputs |
| O-dependency | False | True | False |  |
| P-neoforge | False | None | False |  |

All runtime captures used offline Gradle `--dry-run createMinecraftArtifacts`. No compilation or tests ran. Each source was copied from the same frozen baseline. Three independent project copies shared one private diagnostic Gradle home per container; no candidate classes or task execution were cached. Null identities represent offline configuration/resolution failure, not proof of equal inputs.

The node-key map on equal-input rows is a supported inference from fixed inputs/action implementations, not a claim that NFRT ran during the dry run. Real verifier cache-hit evidence is separate.

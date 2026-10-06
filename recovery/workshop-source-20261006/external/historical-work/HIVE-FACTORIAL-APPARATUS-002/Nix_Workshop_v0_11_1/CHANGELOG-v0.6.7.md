# Nix Workshop v0.6.7

Hive structured-output recovery hotfix. Hive workers and the reviewer now receive one bounded same-role repair attempt when a model response is malformed JSON. Repair calls use the existing provider routing, budget accounting, scopes, verification, approval, rollback, and apply gates; unrepaired output remains a structured failure with the original and repair diagnostics.

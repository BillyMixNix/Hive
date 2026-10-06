# Reproduce supplemental checks

This runner is not the frozen acceptance verifier. The delivery keeps frozen tests out of the coding context.

From the extracted delivery root, using Java with `jdk.compiler` available:

```bash
python evidence/tree_hash.py candidate
python evidence/run_validation.py --repository candidate --phase independent-rerun --probe evidence/probes/BoundLineSupplementalProbe.java --probe-class BoundLineSupplementalProbe
```

The candidate tree hash should be `ecb294b3b7b9a0bd87e365e9f30d2b07ca083f65734abe0a433f1b69b700d4a6`. The evidence bundle includes the JUnit and Gson binaries downloaded from Maven Central at the versions declared in the repository; see their receipt hashes. Do not interpret a supplemental pass as a sealed-verifier pass.

The original run's command logs contain its original absolute paths for audit. The runner above resolves the new extraction location at execution. Choose a new `--phase` name on each rerun; existing evidence is not overwritten.

The full candidate tree differs from the supplied baseline in exactly the authorized SnapshotFormatter.java. `implementation.diff` has standard `a/` and `b/` paths suitable for review/application against a separately verified frozen baseline. No hidden acceptance test source is included.

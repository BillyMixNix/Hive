# Audit interpretation correction

The first completed analysis audit required an explicit successful `source_immutability` check row for every verifier control. It consequently marked the baseline and outside-source controls unqualified even though both completed their expected behavioral failures with unchanged sources.

The byte-identical production `verification/jvm_runner.py:683-692` compares protected source/runtime digests before returning a failed frozen-test report. A mismatch appends an explicit failed integrity row. Its explicit positive integrity row is emitted only in the passing targeted branch at lines 694-700. The corrected analysis distinguishes `EXPLICIT_PASS` from `INFERRED_PASS_FROM_COMPLETED_FAILURE_PATH`; it also retains separate observed candidate/origin/frozen-test hashes. Inference requires a normal complete non-timeout report containing only the failed frozen acceptance check and the unchanged runner implementation.

The earlier audit, control summary and analysis script are retained in `explicit-row-assumption/`. No native result, measurement, candidate, verifier, production source or historical classification was modified. This is correction of the analysis predicate, not a verifier repair or a changed acceptance decision.

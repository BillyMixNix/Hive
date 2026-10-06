# Postprocessing notes

After all 16 trials and the final integrity audit completed, the first report-generation command attempted to derive textual diffs for every file in a preserved applied-source snapshot, including the binary Gradle wrapper. It stopped with UnicodeDecodeError before writing the final report.

Only the unfrozen, read-only report generator was corrected: textual candidate diffs use each task's frozen authorized source files. The independent trial integrity audit already checks the complete stage inventory for out-of-scope changes. No trial, verifier, production file, frozen harness, raw outcome, or historical evidence was changed or rerun.

The descriptive taxonomy refines native collector labels without replacing them. It identifies duplicate ownership within planner failures and compilation failures within the native frozen-acceptance gate failures. A separate audit counts successfully repaired reviewer parse errors that the terminal-error summary omits.

# Preliminary direct test invocation

Before the captured complete-suite runs, a direct invocation of `pytest -q tests/test_semantic_fidelity.py --tb=short` without a custom `--basetemp` returned 11 passed and four fixture setup errors. All four errors were `PermissionError: [WinError 5] Access is denied` while scanning the pre-existing default `C:\Users\billy\AppData\Local\Temp\pytest-of-billy` directory. No failed production assertion was reached in those four cases.

The full tool output exists in the conversation; it was not separately redirected to a file. Subsequent complete-suite runs used the predecessor's established unique `D:/CodexTemp/hive-transition-005-<id>` policy and preserved full stdout/stderr in their own evidence directories. No default-temp directories were deleted or permissions changed.

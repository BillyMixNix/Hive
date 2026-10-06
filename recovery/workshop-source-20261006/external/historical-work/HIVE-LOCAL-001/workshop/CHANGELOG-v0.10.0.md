# v0.10.0 Workshop Chat Observation Loop

- Added a bounded read-only observation loop to local Workshop Chat.
- Chat can inspect repository text, symbols, excerpts, similar code, recent Hive runs, and a specific Hive run before answering.
- Reused Hive repository observation primitives; no write authority, shell, code execution, network tool, or automatic Hive invocation was added.
- Limited each local chat turn to six observations; observation results are ephemeral and only the final user/assistant messages are persisted.
- Added deterministic run-id validation and bounded run diagnostics.
- Preserved the existing single-call cloud Chat path and cloud admission controls.
- Added regression coverage for repository observation, run inspection, traversal rejection, observe-then-answer behavior, persistence, and unchanged cloud behavior.

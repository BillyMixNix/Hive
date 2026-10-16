# State packet offline gate

This is an offline foundation, not a completed paid experiment or evidence of
model improvement. No model requests are made and no paid workflows are changed.
The original study modules and PR #35 results remain unchanged.

Run from experiments/learning-dev:

    python -m pytest -q tests/test_state_packet.py -p no:cacheprovider

`analysis/state_packet.py` adds:

- An explicit public-snapshot input schema with objective, files, constraints,
  action declarations, ordered typed events, uncertainty and verification.
- Deterministic serialization, snapshot binding, exact round-trip verification
  and refusal to silently truncate a packet beyond its byte budget.
- Paired raw and packet prompts carrying identical public information. A lesson
  condition adds frozen advice. This first intervention is serialization, not
  a demonstrated semantic compression algorithm. Count all packet overhead.
- Final-candidate scoring through the existing independent pytest evaluator.
  Wrong SATISFIED candidates count as false completions and receive the full
  call penalty. Evaluator errors are unusable, not ordinary model failures.
- Scope and public-test preservation checks before grading.

The snapshot must come from a trusted current-recipient public-state producer.
A hash does not establish truth or source authenticity. No prior recipient
answers, protected tests or protected-test feedback may enter the snapshot.
Explicit private fields are rejected, but this does not detect secrets or
oracle information disguised inside otherwise allowed text fields.

The existing evaluator is a trusted development bench, not a hostile-code OS
sandbox. Contract and tool-authority enforcement remain responsibilities of the
existing controller; this module does not replace them.

## Request-path integration

`analysis/packet_adapter.py` supplies `recipient_adapter(..., condition=...,
contracts=...)`. Its `work` interface matches the existing adapter, so callers
can use the existing attempt/final-scoring code without replacing the controller.
Conditions are `raw`, `lessons`, and `packet`. Non-lesson arms require empty
guidance. Contract declarations select the existing contract controller; iterator
cases retain the existing iterator adapter. Supply the same declarations in all
conditions.

Each worker request snapshots the current public candidate, preserves initial
tool contracts, adds attributed message context, and verifies tool schemas are
unchanged. Model claims remain unverified. The adapter rejects reuse across
recipients. `packet_records` and optional `packet_observer` expose snapshots,
hashes and full message byte counts for later audit. The caller must preserve
these records alongside normal request/response and spending evidence.

This version adds public state in all three arms, retains the original messages,
and varies compact versus expanded serialization. It may increase total tokens.
It does NOT yet test semantic selection, historical state compression, or
interruption recovery. A gain here would not by itself establish those benefits.
Public files are baseline-bound, but message provenance is controller-attributed,
not independently authenticated. No protected-test data is read by the adapter.

Offline integration tests disable provider networking and replay a known nine-
action repair through the real contract controller under all three conditions.
Replay success checks wiring only; it is not new model performance evidence.

Remaining before paid launch:

1. Freeze the intended intervention: this integration is lossless state
   presentation, not yet the richer semantic-compression hypothesis.
2. Add a frozen comparison launcher and audit for all saved packet records.
   Use concurrently rerun controls, not old outcomes. These previously seen
   tasks support descriptive results only.
3. Freeze the schedule, metrics, source hashes and new $5 budget ledger; retain
   previous spending separately. Check current pricing and credential setup.
4. Add an explicit interruption protocol before claiming continuity benefits.

The old scripts/packet_experiment.py formatting/cue probe is not a correctness
benchmark. It is not used by this offline gate.

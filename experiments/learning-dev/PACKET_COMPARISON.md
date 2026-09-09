# Frozen state-presentation comparison

The launcher compares raw, frozen-lesson, and compact JSON packet conditions on
the same 15 reused tasks (45 recipients), with a seeded adjacent-arm schedule.
This is descriptive, not a fresh-task lesson-learning experiment. Packets retain
the original messages; this does not test semantic compression or interruption
recovery, and does not promise fewer tokens.

From `experiments/learning-dev`, using the project Python environment:

```sh
python analysis/packet_comparison.py freeze examples/packet-comparison-plan.json
python analysis/packet_comparison.py check examples/packet-comparison-plan.json --sha256 DIGEST
```

Use the digest printed by freeze as an external commitment. The plan pins Python
source bytes, the study, the schedule, the model, and a separate fresh $5 ceiling.
Freezing also runs the existing task/reference and contract mutation preflight.
Any Python source change requires a new plan and digest.

Paid execution is currently BLOCKED: the inherited pricing guard expired on
September 9, 2026. Do not override its clock. Verify pricing and update the guard
before freezing a replacement plan. No paid execution was performed for this
integration. The approved credential is the existing GitHub secret
`HIVE_OPENAI_API_KEY`; no workflow or secret-export mechanism is added here.

Once pricing and a supported secret-backed execution environment are ready:

```sh
python analysis/packet_comparison.py run PLAN --sha256 DIGEST --output NEW_DIRECTORY
python analysis/packet_audit.py NEW_DIRECTORY --plan-sha256 DIGEST
```

One shared guard covers every recipient, with no automatic retries. A failed
launch consumes an adjacent local plan lock, even if pricing blocks before key
loading. This prevents local accidental replay, not cross-machine duplication.
Do not interpret an incomplete run as a complete comparison.

The independent audit regrades saved candidates against protected tests and
checks packet/request/tool bindings, usage totals, artifact inventories, and
completed-run charges. Checksums detect inconsistency, not malicious rewriting
of the whole bundle. Filename checks do not prove complete information isolation;
the audit is not a full security audit or complete journal-state replay.

Offline tests include a synthetic successful audit fixture and tampering cases.
They establish harness behavior, not model improvement. Keep the engineering;
publish any future comparison with these limits; do not claim lessons or packets
improve outcomes until actual complete audited results support that claim.

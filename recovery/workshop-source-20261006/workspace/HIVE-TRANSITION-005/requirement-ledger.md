# Frozen task requirement ledger

Derived only from the supplied frozen task; no frozen test source or assertions used. IDs are analytical, not new prompt fields.

In `SnapshotFormatter.boundLine`, preserve complete UTF-16 surrogate pairs when truncating a line to `MAX_LINE_CHARS`. Keep the existing control-character and section-sign sanitization, the `...` suffix when truncation is necessary, and unchanged behavior for ordinary ASCII lines. Truncation must never introduce an unpaired surrogate or return a string longer than the bound.

Write scope: `src/main/java/dev/atmcompanion/state/SnapshotFormatter.java`.

| ID | Explicit requirement |
|---|---|
| R1 | Preserve complete UTF-16 surrogate pairs during truncation to MAX_LINE_CHARS. |
| R2 | Keep existing control-character sanitization. |
| R3 | Keep existing section-sign sanitization. |
| R4 | Keep the ... suffix when truncation is necessary. |
| R5 | Keep unchanged behavior for ordinary ASCII lines. |
| R6 | Truncation must never introduce an unpaired surrogate. |
| R7 | The returned string must never exceed the bound. |

All behavior is scoped to `SnapshotFormatter.boundLine`; only `src/main/java/dev/atmcompanion/state/SnapshotFormatter.java` may be written. No additional behavior for pre-existing malformed input is inferred.

# Nix Workshop v0.11.1

## Hive Build feature catalog IDs

- Added a bounded, read-only resolver for structured `FEATURES.md` entries.
- Added `GET /api/hive/features/{feature_id}` to preview feature status and the exact specification hash.
- The Hive Build UI displays the resolved scope and asks for explicit confirmation before submission.
- The build endpoint re-resolves the entry and rejects unknown, non-planned, incomplete, or stale specifications before queueing.
- The selected feature ID, original command, specification, and section hash are preserved in Hive run metadata.
- Free-form Hive requests continue through the existing path, and catalog entries do not grant file ownership or weaken any build/apply gate.

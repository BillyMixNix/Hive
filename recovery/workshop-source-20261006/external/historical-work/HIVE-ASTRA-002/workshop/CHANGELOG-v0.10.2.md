# Nix Workshop v0.10.2

## Local generation bounds and real cancellation

- Hive local calls now send explicit role-specific Ollama output-token ceilings.
- Ollama streaming now has an absolute 900-second generation deadline in addition to the existing 900-second inactivity timeout.
- Total-limit and cancellation failures are non-retryable locally, preventing duplicate runaway generations.
- Hive job cancellation is propagated into the active Ollama stream and closes it promptly.
- A provider abort after cancellation can no longer overwrite the job's cancelled state with failed.
- Cloud/API timeout and output controls are unchanged.

## Safety

Planner authority, exact write ownership, strict edit validation, structural repair, replan limits, verification, review, approval/apply, rollback, and cloud budget gates are unchanged.

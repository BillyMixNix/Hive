# Nix Workshop v0.7.1

Model-facing Hive contracts and integration context, following the real Project Summary run.

- Workers and same-role repair calls receive the complete implementation-or-escalation protocol. Escalations carry evidence and requested scope; they never authorize edits.
- Planner sees real role/file constraints. Missing, wildcard, cross-role and concretely contradictory assignments are rejected together; one planner correction is allowed before any worker executes. No legacy scope broadening.
- Read-only source context can cross role boundaries independently of exact write ownership. Large owned files receive bounded, labeled excerpts; integration examples favor actual endpoints and TestClient usage.
- Later workers and the replanner see previous proposals as unverified read-only data. No proposal changes another worker's scope.
- Local Hive requests send role-specific JSON schemas with temperature 0.1. Normal local chat, cloud request bodies, provider retries, and the 900-second local streaming timeout retain their existing behavior.
- Run records include prompt/response hashes and plan correction attempts. Workers that fail prevent partial proposals from becoming approved builds.
- New tests inspect actual prompts at the call boundary, require escalation instructions before returning fake escalations, and exercise correction limits, repaired escalation, cross-role reads, exact ownership and prior proposals.
- Existing edit-validator, staged edit application, apply/rollback and verification functions are unchanged.

Limitations: semantic plan checks catch concrete role contradictions, not arbitrary natural-language mistakes. Bounded excerpts and JSON schemas do not guarantee correct code; verification and approval remain required.

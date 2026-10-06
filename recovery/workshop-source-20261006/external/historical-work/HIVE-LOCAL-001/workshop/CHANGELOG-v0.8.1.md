# Nix Workshop v0.8.1

## Planner structured-output boundary hardening

- Require `interface_contracts` in the planner JSON schema; single-role plans may still return an empty list.
- Preserve required `consumer_roles` on every interface-contract object.
- Planner correction prompts now carry explicit `AgentPrompt` schema metadata instead of falling back to the generic planner schema.
- For a rejected multi-role plan, the one correction call strengthens `interface_contracts` to `minItems: 1`.
- Semantic plan validation remains authoritative; no host-side synthesis of owner or consumer roles was added.
- Added regressions proving the planner schema requires `interface_contracts`/`consumer_roles` and multi-role correction carries the stronger schema.

This is a protocol-boundary patch only. It does not change worker authority, observation budgets, escalation gates, replanning limits, edit validation, verification, review, approval, rollback, or cloud routing.

# Nix Workshop v0.6.8

Planner/executor separation hotfix. Hive plans now assign exact file ownership to each role, executor prompts receive only the planner's bounded goal instead of reinterpreting the full request, and planned-file validation is enforced before any staged file is written. Multi-edit payloads are applied atomically. Existing safety scopes, snapshots, rollback, budgets, verification, reviewer approval, and apply gates are unchanged.

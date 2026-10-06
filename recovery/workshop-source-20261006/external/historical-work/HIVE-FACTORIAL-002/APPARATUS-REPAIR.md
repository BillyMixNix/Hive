# HIVE-FACTORIAL-002 apparatus delta

This is a new comparison, not a continuation or rescore of HIVE-FACTORIAL-001. The task prompts, frozen JUnit tests, randomized order, two models, two conditions, two replicates, baseline, verifier image, 448-PID envelope, caches, token/wall budgets, and no-promotion policy are inherited from the historical freeze. The parent freeze hash is checked before each trial.

The Workshop source was copied from the actual HIVE-JAVA-EDIT-001 frozen source used by HIVE-FACTORIAL-001. Relative to that source, only `workshop/hive.py` changes; `factorial_runner_adapter.py` and `tests/test_host_write_scope.py` are new. No verifier or edit-engine source changes are included.

The old runner threw `StudyStop` inside the provider callback when the planner named an out-of-scope file. That prevented Hive from receiving the response or using its one planner correction. The new runner returns the raw planner response. Host-authorized files are passed separately to `hive.run_build` for both conditions. Hive records exact-path rejection evidence, offers its existing one correction, and still fails closed if correction or replan exceeds the host scope. A host-scope correction may deactivate an unauthorized role without fabricating an interface contract; genuinely multi-role plans still face the unchanged contract validator.

`factorial_runner_adapter.py` preserves the single condition's deterministic host plan/reviewer, while the Hive condition uses its model planner/reviewer. The local-only provider, aggregate token and wall limits, frozen acceptance, sealed offline verifier, integrity checks, and no-promotion policy remain owned by the successor runner.

The prior study's raw results and lock are immutable historical evidence. A new `FREEZE.json` and `LOCK.sha256` must be generated and checked before HIVE-FACTORIAL-002 can start. Neither the prior lock nor its evidence authorizes a new trial by itself.

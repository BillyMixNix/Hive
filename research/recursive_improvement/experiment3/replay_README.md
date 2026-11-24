The original Experiment 3 replay worker changed into the read-only subject root.
PlannerAgent constructs LessonMemory, whose initialization creates hive_lessons.jsonl
when it is absent. All original replay outputs were OSError, so those raw zero
scores cannot measure Planner functional accuracy. They are preserved unchanged.

This follow-up supplies a tmpfs working directory with symlinked immutable source
and a separate writable lesson data file. It first reproduces the original
initialization error inside Docker and checks a clean baseline positive control.
The same eight inputs, expected goals, scoring function, candidates, baseline,
resource limits and permissions are retained. There are zero model requests and
no candidate modifications. This is an adaptive instrumentation diagnostic after
observing held-out data, not an unchanged replication or another generation trial.
It cannot rescue any candidate's failed public gate or change the original verdict.

A separate production compatibility fix preserves the existing one-helper
complexity exception when the target body changes without a changed def line.
Normal bug-fix tasks still use the stronger source-tree scope check. This fix is
outside Experiment 3's pinned baseline and earns no Hive improvement credit.
To reproduce the original study, check out b2b8d01c4aeb622d2c6ed3a7d8758cbe97f76474.

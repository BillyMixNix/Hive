# Additional correctness check, before V4 result inspection

V3 phase-1 candidates for `bank3_single_pass_31` in **all three arms** use
`stream.__reduce__()[1][0]` to recover a list iterator's backing sequence. They pass
the original supplied tests but cannot handle ordinary generators, and the same
approach can ignore an iterator's current position. The task explicitly permits
single-use iterables. This is a concrete gap in test coverage, not evidence of a
lesson benefit.

This audit is committed while V4 phase 1 is running, before its artifact or any
per-recipient V4 repair result has been read. It follows inspection of the already
recorded V3 candidate source. No V4 input, lesson, prompt, recipient schedule,
model budget, acceptance feedback or original protected test changes.

After each completed V4 phase, apply the same standalone test to every single-pass
candidate in every arm. Test list iterators, ordinary generators, a valid iterator
that cannot be serialized, and iterators already advanced by one element. Cover
count/sum, validated tuple output including negative rejection, and dictionaries
with duplicate keys. Commit candidate hashes before running this audit. Verify
that each reference repair passes and that the observed V3 shortcut fails.

Always retain and report the original frozen V4 endpoint. Report supplemental
correctness separately. The new audit can veto a claim that the lessons achieved
correct repairs; it cannot rescue a failed original confirmation decision, replace
failed recipients, or provide feedback to the lesson proposer. If any original
passing candidate fails this check, explicitly disclose the test-coverage gap and
show the affected arms and tasks.

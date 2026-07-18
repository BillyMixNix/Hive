# Recorded regressions

Each JSON object is an executable memory of a behavior Hive is not allowed to forget.

## Required fields

- `id`: globally unique case identifier
- `target_file`: repository-relative Python file
- `callable`: top-level function or `Class.method`
- exactly one of `expected` or `expected_exception`

## Optional fields

- `args`: positional arguments, default `[]`
- `kwargs`: keyword arguments, default `{}`
- `construct`: class construction strategy for method calls
  - `{"mode": "call", "args": [], "kwargs": {}}` invokes the constructor
  - `{"mode": "new"}` allocates the instance without invoking `__init__`
- `preserve_inputs`: verifies the call did not mutate inputs, default `true`
- `post_mutations`: mutations applied to the returned value after equality succeeds; input preservation is checked again to expose shared mutable state
- `description`: human explanation of the failure being preserved

Files may contain one case object or a list of case objects. Duplicate IDs are rejected.

A regression should be as small as possible while reproducing the actual failure. Do not store vague advice here; store inputs and observable outcomes.

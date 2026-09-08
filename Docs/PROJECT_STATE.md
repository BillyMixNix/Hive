# Project state from a curated evidence ledger

`python -m hive_reference.project_state ledger.json` replays a project's documented
state using Hive's existing `EventLedger` and authority policy. It runs locally
without model calls. Use it to preserve completed work, explicit supersession,
plans, and conflicting reports across handoffs.

## Run

From this repository, with `requests` installed (an existing reference-package
dependency):

```bash
python -m hive_reference.project_state /path/to/ledger.json
python -m hive_reference.project_state /path/to/ledger.json --format json
python -m hive_reference.project_state /path/to/ledger.json --known-at 10
python -m hive_reference.project_state /path/to/ledger.json --valid-at 1 --known-at 20
```

Times are nonnegative logical integers, not automatically parsed dates.
`recorded_at` describes when the ledger knew a record; `effective_time` describes
when it applies. Event record times must be unique. By default the command uses
the latest recorded knowledge and greatest effective time among known events.
Pass explicit cutoffs for historical views or future-dated records.

## Manifest

The manifest is an operator-curated mapping from source excerpts to claims. A
person or assistant prepares it; the command does not discover semantics in raw
markdown. Source hashes and matching excerpts establish byte identity and text
presence. They do not prove that the interpretation is true. Treat the manifest
as a trusted input and distinguish reported results from independently observed
results in the claim names or values.

For a UTF-8 file `reports/release.md` containing `The repair is implemented.`:

```json
{
  "schema_version": 1,
  "project": "Example project",
  "sources": [
    {
      "id": "release_report",
      "path": "reports/release.md",
      "sha256": "REPLACE_WITH_THE_FILE_SHA256",
      "recorded_at": 10
    }
  ],
  "records": [
    {
      "id": "repair_reported",
      "subject": "repair",
      "predicate": "reported_status",
      "value": "implemented",
      "effective_time": 1,
      "recorded_at": 11,
      "basis": "observed",
      "truth": "accepted",
      "authority": "canonical",
      "source": "release_report",
      "excerpt": "The repair is implemented."
    }
  ]
}
```

Hash source bytes with `sha256sum reports/release.md` or Python's `hashlib`.
Source paths are relative to the manifest's directory and must resolve beneath
it. Source files are checked on every invocation. Updating a source requires
updating its explicit commitment; preserve older versions as separate files if
they are needed for historical views.

To supersede an earlier claim on the same subject and predicate, add a new record
with a later record time and `"supersedes": ["earlier_record_id"]`. Use an
appropriate effective time. An explicit `valid_to` can end a claim's validity.

`basis`, `truth`, and `authority` are mandatory; the adapter never silently grants
canonical authority. Supported basis values are `observed`, `planned`,
`proposed`, `predicted`, and `unknown`. Inference needs a registered rule and is
outside this adapter's first version. Authority and truth use the existing Hive
enums. Plans cannot materialize their proposed effects, external claims cannot
replace observed canonical facts, and unlicensed overwrites are not applied.

## Output and boundaries

The JSON output includes current facts, unresolved conflicts, other visible
records, source excerpts and hashes, and ledger/snapshot digests. Text output
gives a readable status with source file and line references. Conflicting state
is shown as unknown. A malformed manifest, changed source, missing excerpt, or
invalid ledger relation exits with code 2 and emits no state.

This is a document-to-ledger adapter around the reference implementation. It
does not execute project actions, resume a frozen experiment, change a model,
verify a reported test run, or automatically connect to a coding agent. Its
deterministic tests verify this interface; they are not a capability benchmark.

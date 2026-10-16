# Continuing from a promoted GROW workshop

This development API lets the next GROW attempt start from a verified promoted
workshop. Its failure packet, parent evaluations, diagnosis probe, modifier
context, and candidate workspace all use that parent's code. A successful child
can supply the source for the next episode. Rejected children remain archived
and cannot become parents.

The public GROW-0 implementation deliberately runs one G0 → G1 slice. Its
`scripts.grow0` entry point still does that. Continuation is a separate opt-in
API, with separately identified episode evidence. It does not resume the later
HoH experiment or change any of its stopping rules.

## What changes

`GrowContinuationExperiment` reuses `Grow0Experiment` for the modifier prompt,
proposal application, structural validation, diagnosis probe, current-case
evaluation, and deterministic promotion rule. The base class now exposes the
parent identity and workshop root consistently; its defaults remain G0.

Continuation verifies the chosen parent's hash-chained lineage, archive bytes,
metadata, original G0 integrity snapshot, and promotion evidence. Descendants
must actually derive from the parent they name. Generation IDs are unique across
sibling branches. The controller checks these commitments around callbacks and
rejects edits to a candidate during evaluation.

Controller timestamps stay in the rejection ledger but are omitted from the
lesson projection sent to the modifier. This fixes an existing intermittent
false positive when fractional seconds contain a protected numeric answer.

Before a new candidate can pass the existing gate, it must pass the supplied
prior-capability suite and both presentation orders of every trigger/transfer
case inherited from promoted ancestors. Those protected cases are evaluated by
the controller and excluded from the modifier context. Continuation does not
weaken the requirement for improvement on the new transfer case.

## Use the API

Keep the original experimental repository and its `grow/state` archives intact.
Import this controller from a **separate checkout** and point it at that frozen
repository. Installing changed controller files into the original repository
would change its G0 tree commitment and correctly block continuation. All paths
below refer to the machine on which the controller runs.

Prepare a new episode outside the frozen repository. Its exact JSON fields are:

```json
{
  "schema": "hive.grow.continuation-episode.v1",
  "episode_id": "next-registered-episode",
  "parent_id": "G1-A",
  "trigger": {
    "case_id": "new-trigger",
    "goal": "A prospectively specified provenance-selection task.",
    "stored_value": 12,
    "current_value": -57,
    "expected_source": "current",
    "expected_value": -57
  },
  "transfer": {
    "case_id": "new-transfer",
    "goal": "A separately specified transfer task.",
    "stored_value": 25,
    "current_value": -68,
    "expected_source": "current",
    "expected_value": -68
  }
}
```

These numbers illustrate the schema; they are not a scientific challenge pack.
The inherited evaluator and diagnosis still address stored/current provenance.
New case IDs alone do not establish that a task is unseen or meaningfully novel.
Case records may also contain `bundle_id`, `failure_class`, and `surface_labels`.

Commit the episode bytes and design before exposing its protected cases. Then,
from the controller checkout, use the Python API:

```python
from grow.continuation import GrowContinuationExperiment

growth = GrowContinuationExperiment(
    "/absolute/path/to/frozen-repository",
    parent_id="G1-A",
    episode_path="/absolute/path/to/registered-episode.json",
    episode_sha256=registered_episode_sha256,
)

budgets = growth.required_call_budgets
result = growth.run(
    invoke_parent=audited_parent_model,
    invoke_modifier=audited_modifier_model,
    invoke_candidate=audited_candidate_model,
    prior_suite=run_prior_suite_on_candidate_overlay,
)

record = result["record"]
if record["disposition"] == "PROMOTED":
    next_parent_id = record["generation_id"]
    # A separately committed future episode can name this parent.
```

The model callbacks accept a prompt string and return the model's response
string. Use stateless, audited calls to the same pinned model configuration;
callbacks must not retry or silently switch models. `prior_suite` accepts the
isolated candidate directory and returns a dictionary with a boolean `passed`.
The existing `scripts.grow0.run_prior_hive_suite_on_candidate` implements the
full-repository overlay for that callback. Callbacks are trusted controller code,
not programs supplied by the candidate.

The controller bounds callback invocations at four parent calls, one modifier
call, and `4 + 2 * inherited_case_count` candidate calls. It records actual counts
including retention. Configure transport budgets accordingly. The existing
`FixedOllamaInvoker` counts four calls across its whole instance by default; that
single instance cannot cover a continuation's additional retention calls.
This API does not silently alter its configuration or claim matched compute.
Token, latency, and provider-identity evidence must come from the audited
transport; the callback boundary cannot independently measure those.

Legacy result keys `g0` and `g1` mean parent and candidate. The authoritative
identities are `record.parent_id` and `record.generation_id`. Continuation records
use an episode-specific `benchmark_bundle_id` and retain the episode commitment,
parent record commitment, retention manifest, and call counts.

## Persistence and stopping

One committed episode permits one attempt. The attempt is recorded before any
callback, so interruption, rejection, or an already-solved challenge cannot
silently trigger another attempt on the same protected cases. A restart can
inherit a completed promoted generation; it does not resume partially executed
model calls. Keep episode files at their committed paths for later retention.

Use a single controller/writer for each lineage. This is not a concurrent job
scheduler. Archive files are written before a continuation generation becomes
eligible in the lineage. An interruption during archival may leave an orphan
archive and a consumed attempt, which require operator review.

Hash checks detect drift from the supplied commitments. They do not authenticate
the initial experiment, certify a human's preregistration, contain arbitrary
trusted callback code, or replace OS isolation. The original static workshop
validator and candidate-only workspace remain in use.

## What the verification establishes

The integration tests use explicitly scripted recipients and proposed code.
They verify executable inheritance through G1 → G2 → G3 after reconstruction
from disk, growing retention coverage, rejection of capability loss, evidence
and source drift detection, and prevention of silent retries. The original GROW
tests also run unchanged.

```bash
python -m pytest -q tests/test_grow0*.py tests/test_grow_continuation.py
```

This closes a connection needed for cumulative workshop changes. It is not
evidence that a model discovered an improvement, that K2 provides incremental
learning gain, or that the system became better at producing future improvements.
The proposal policy, failure diagnosis, and task family remain fixed. A recursive
improvement claim still needs independent future improvement episodes, controls,
and complete resource accounting. Jarvis/GROW-9 integration is not provided by
this change.

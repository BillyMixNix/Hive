# Stopped comparison and prospective interface repair

V5's first batch completed on 8 September 2026. Baseline and unrelated-note arms
each passed 5/6 tasks; the retained-lesson arm passed 1/6. Four lesson recipients
stopped when the model omitted one character from a 64-character memory ID.
The exact function outputs and offered IDs are preserved in
`results/bank-v5-phase-1/interface-stop.json` and the raw artifact.

This is an interface defect introduced by this redesign: advisory metadata was a
free string requiring exact hash copying. The decoder correctly rejected unknown
IDs, but this avoidable copying requirement interfered with the intended test of
lesson use. It is not evidence that those four unexecuted actions would otherwise
have repaired their tasks; one proposed action itself acknowledged a contract
problem. The masked-pairs task also failed in all three arms through the normal
controller path. All original outcomes and charges remain unchanged.

## Protocol departure, explicitly recorded

Stopping here was **not predeclared** in V5. Its intended 63-recipient confirmation
is therefore **incomplete**, with no confirmed gain. No favorable early decision
is possible: several required lesson successes have already failed. We do not
silently remove those rows, replay them, reinterpret their actions as successful,
or combine changed-interface results into the original confirmation.

The user's authorization to implement and test the redesign remains in force.
We correct the observed implementation defect before spending more on it. This
follow-on is **descriptive engineering evidence**, with no reassigned alpha,
confirmatory p-value claim, or claim that it rescues V5. The original V5 protocol
and its immutable source commit remain available for reproduction.

## Exact prospective repair and remaining sample

Keep hashes in provenance. Give the model short handles `memory_1`, `memory_2`,
`memory_3` and `none`, constrained by an identical native JSON-schema enum in
every arm. The decoder still checks that a selected handle exists in that
recipient's supplied memory. It never guesses or normalizes a bad response.
The full callable context, public objective, advisory checkpoint fields, model,
tool authority and independent tests are unchanged.

Use exactly the remaining **12 untouched transfer tasks and three retention
tasks** from the original frozen V5 fixture file, with no substituted or newly
selected cases. Each runs once under empty memory, the same unedited three-lesson
bank, and word-matched unrelated notes: **45 remaining recipients**. The same
original seeded phase-2/3/4 schedules and 36-call allocation apply. No information
from the first batch enters the lessons or recipient prompts.

The new source, subset fixture digest, launch parent and cumulative budget are
committed before the first follow-on call. Every recipient retains its actual
request/response, checkpoint, candidate and grading evidence. Model mistakes with
settled usage count as failed tasks; unknown usage, HTTP failure, evaluation
integrity failure or insufficient budget stops the run. No recipient replay or
replacement is permitted. There is no outcome-driven extension.

Report all 18 original-version outcomes separately from all 45 repaired-version
outcomes. For the repaired version, report task success, actual calls, failures
penalized at 36, paired lower/higher/tied effort, tokens and conservative costs.
Those observed differences are not a new confirmatory finding. No weight
training or RSI claim is allowed by this follow-on.

The conservative cumulative bound starts at **$2.6399464**: the prior $2.3149073
plus this batch's $0.3250391. The original total ceiling stays **$5**, including
the permanently carried $0.5323728 unknown-usage reservation. No current request
is unresolved. The existing pricing expiration and one-attempt launch controls
remain in force.

# Kingdom / Mind Constructor

Kingdom is an experimental construction layer above Hive's regression-first contract.

Its mission is not merely to generate more reasoning. It is to turn compressed human intent into recursively navigable, reality-tested construction:

`intent -> decompression -> incompatible worlds -> novel branches -> reality contact -> structural reintegration -> dependency graph -> executable frontier -> acquire capability -> retry -> critical intent path -> reopen or accept -> checkpoint -> resume`

## Mission boundary

Comprehension is part of the interface, not the whole mission. The stronger engineering question is whether a human can point at a high-level goal and have the system expose, explore, test, build, and recursively reduce the missing territory between the idea and executable reality while preserving enough structure for meaningful human direction.

The current branch does **not** claim generalized autonomous construction or generalized cognitive amplification. It builds a falsifiable software apparatus for those questions.

## Cognitive topology

`KingdomEngine` provides bounded branch expansion, exact deduplication, parallel exploration, structural reintegration, a cognitive packet, comprehension probes, and a tamper-evident run ledger.

### Incompatible worlds

`WorldBranchingProvider` injects premise-level interventions before ordinary model-generated branches. The default basis includes:

- premise true
- premise false
- minimum viable
- capability-max
- adversarial
- outside-frame

Forced worlds are deliberate interventions, not votes.

### Branch diversity

`NoveltyFilteringProvider` removes near-duplicate generated branches with a deterministic lexical gate while never removing explicit world branches. `diversity_report()` distinguishes raw branch count from an effective branch count and reports residual correlated pairs.

This is intentionally only a conservative lexical proxy. It prevents obvious correlated clones from masquerading as scale; it does not claim to solve semantic diversity.

## Arena: reality gets a veto

`ArenaRegistry` gives branches an explicit reality-contact layer. Current host-owned adapters include:

- repository read
- repository search
- pre-registered deterministic simulation
- constrained pytest execution

The pytest adapter accepts only validated test node IDs under configured test roots. It does not expose shell strings or arbitrary pytest flags.

Arena distinguishes:

- `verified`: the requested operation produced a successful observation
- `failed`: the operation executed but contradicted the attempted claim or failed its check
- `unavailable`: the required capability is absent

Model prose is never automatically upgraded to external evidence. Only actual Arena observations receive observation status.

## Recursive construction

`MindConstructor` promotes unavailable Arena capabilities into `BuildTarget` nodes attached to the exact originating branch/world that needed them.

`HiveTargetDecomposer` can recursively reduce a blocker into predecessor tools, capabilities, or experiments. Construction depth is measured relative to each promoted blocker, and total targets are budgeted.

### Dependency closure

A decomposition now declares an explicit resolution mode:

- `all`: every child is jointly required
- `any`: any one verified child is sufficient

Parent status propagates only when that declared rule is satisfied. A convenient successful subtask therefore cannot silently mark a larger blocker solved.

## Executable construction frontier

`HiveTargetExecutionPlanner` translates executable leaf targets back into concrete Arena requests. `MindConstructor` can cycle through bounded construction rounds:

`frontier leaf -> Arena -> observation/missing capability -> forge or decompose -> dependency closure -> next frontier`

Arena observations produced during construction retain their originating branch ID and are fed back into structural reintegration rather than becoming orphaned build logs.

## Capability Forge

`CapabilityForge` is an explicit opt-in via `--forge-missing`.

It handles only a deliberately narrow generated capability class: one deterministic Python function `execute(payload)` with no imports, attributes, classes, decorators, file/network/process access, or arbitrary function calls.

A coding role proposes the implementation. A separate acceptance oracle derives independent executable cases from the intended contract. The implementation author therefore does not get to define the only exam that grants its own authority.

A candidate must survive:

1. restricted AST policy
2. author development cases
3. independent acceptance-oracle cases
4. Hive `RegressionGate` over the merged case set in a timeout-bound subprocess
5. a second isolated runtime execution of every case
6. Arena registration only after those validation layers pass
7. immediate retry of the exact request that originally failed

If the oracle cannot define objective expected outputs, the forge fails closed instead of converting ambiguous semantics into code authority.

Generated capabilities are ephemeral. They are **not** automatically trusted or restored after process restart. A resumed run that needs a previously forged tool must actually have that tool available again or the capability becomes blocked.

This is defense in depth for a tiny generated-code class, not a claim of a general secure Python sandbox.

## Critical Intent Path: walk the original request through the finished result

Component truth is not enough. A system can have green unit tests, green regressions, verified Arena observations, and closed dependencies while still assembling the wrong end-to-end experience.

Kingdom therefore has a terminal `IntentPathGate`, inspired by a venue critical-path walk: preserve the original request, then near the end physically/logically follow the path the real user or artifact would take through the assembled result.

### Intent Capsule

Before judging the finished result, Kingdom reconstructs an immutable `IntentCapsule` from the original `Seed`:

- original request
- original context
- original goal
- SHA-256 fingerprint of those values

This is the reference point. The terminal verifier is not asked whether Kingdom's internal reasoning was impressive; it is asked whether the finished path still satisfies what the operator originally meant.

### Fresh path planner

`HiveIntentPathPlanner` receives:

- the original Intent Capsule
- a public finished-state summary
- currently available Arena tools

It does **not** receive branch-by-branch reasoning traces. It creates an ordered set of end-to-end checks and states a success criterion for each one. If a critical step cannot be verified with existing tools, it must request the missing verification capability rather than silently omit the step.

### Reality walk

Each critical-path step is executed through Arena. A failed or unavailable Arena step cannot be upgraded to a pass by the semantic judge.

The gate distinguishes:

- `passed`: every required path observation is verified, no actionable construction frontier remains, and the independent semantic judge recognizes the observed result as satisfying the original intent
- `failed`: an end-to-end step fails or observed behavior contradicts the original intent
- `incomplete`: a required observation/capability is missing or unresolved construction work remains

### Reopen instead of rationalize

A failed walk does not produce a note saying "known issue" and then declare completion.

The construction graph is reopened:

- the root goal becomes `blocked`
- the exact broken user-facing path step becomes a new repair target
- a missing path-verification capability becomes a child capability blocker
- if all technical steps pass but the independent semantic judge detects intent drift, a semantic repair target is created under the original goal

Only a passing critical intent path marks the root goal `verified`.

This adds two truth levels above dependency closure:

`critical-path truth`: do the assembled pieces work together end-to-end?

`intent truth`: is that end-to-end behavior actually what the human asked for?

### Tamper-evident intent walks

Every walk is persisted as its own immutable JSON artifact by `IntentPathRecorder`. Its SHA-256 is anchored in the same Hive hash-chain ledger with the intent fingerprint, status, step count, and number of reopened targets.

Construct and resume modes run this gate by default. `--skip-intent-path` exists only as an explicit debugging escape hatch.

## Structural reintegration and navigation

Reintegration extracts invariants, disagreements, hinge assumptions, causal links, anomalies, unknowns, and branch provenance rather than majority-voting branch answers.

`CognitiveNavigator` retains stable references from structural claims back to the branches/evidence that exposed them. Compression does not require deleting inspectability.

## Tamper-evident construction checkpoints

The base Kingdom run and the post-Arena construction state are both durable.

`ConstructionRecorder` writes hash-addressed construction checkpoint files containing:

- the original Kingdom run
- verified branch results
- Arena executions
- construction targets and dependency modes
- structural reintegration
- cognitive packet/probes
- forge decisions

Each artifact's SHA-256 is anchored into Hive's existing hash-chained ledger. Later edits to the artifact fail verification. Successive checkpoints never overwrite earlier construction history.

The construction checkpoint is written after the terminal intent walk, so any critical-path failure that reopens the graph is part of the durable state.

## Resumable construction

`ConstructionResumer` loads the latest ledger-verified checkpoint for a run ID and continues unresolved frontier work without replaying the original conceptual search.

On resume it:

1. verifies the ledger and checkpoint hash
2. reconstructs the branch/evidence/construction graph
3. reconciles current Arena capabilities
4. demotes direct verified capability targets whose adapters no longer exist
5. continues decomposition/frontier execution
6. appends only new observations to branch evidence
7. reintegrates the updated structure
8. walks the original intent through the updated candidate again
9. writes another immutable intent-path artifact and construction checkpoint

This gives long construction problems continuity without pretending ephemeral execution authority survives a restart.

## Run a fresh construction

```bash
python -m kingdom "Build an artificial decompression intelligence" \
  --construct \
  --forge-missing \
  --branches 12 \
  --worlds 6 \
  --depth 1 \
  --construction-depth 3 \
  --construction-rounds 3 \
  --target-budget 40
```

The critical intent path runs automatically near the end.

## Resume a prior construction

Use the base Kingdom run id printed by construct mode:

```bash
python -m kingdom \
  --resume-run-id kingdom-YYYYMMDD-HHMMSS-XXXXXXXX \
  --forge-missing \
  --construction-rounds 3
```

The latest checkpoint is resolved through the verified ledger rather than by trusting an arbitrary JSON file path, then the original intent is walked again against the updated state.

## Authority boundary

Kingdom still does not expose unrestricted shell execution or unrestricted network access. Multi-file generated implementations, package installation, network clients, privileged APIs, and persistent host mutation remain outside generated-tool authority.

The next broader construction frontier should preserve the same rule:

`proposal != authority`

A future multi-file workshop needs a host-owned isolated candidate workspace, task-specific independent oracles, explicit test execution, Hive regression/reliability gates, and an explicit promotion step before anything can affect the real repository or gain new privileges.

## Research claim still open

What has been established so far is software feasibility: the loop can be represented, bounded, regression-gated, reality-connected, recursively decomposed, checkpointed, resumed, and now checked end-to-end against the original intent.

Still open:

> Can this coupled human-machine process reliably solve or construct across problem spaces that exceed the operator's unaided search bandwidth while preserving enough structure for the operator to understand, challenge, and redirect the process?

That is the crown test.
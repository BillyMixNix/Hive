# Hive

**Verified semantic state for persistent AI workflows.**

Hive is a research prototype for compiling growing workflow history into smaller, task-relevant semantic state without silently discarding distinctions that can change the answer.

The first commercial wedge is **AI coding agents**: long-running agents that repeatedly revisit repositories, prior tool calls, implementation decisions, failures, and changing project state.

## The problem

Persistent AI workflows accumulate history. Later model calls either:

- keep rereading more and more context,
- truncate or summarize it,
- retrieve fragments from it,
- or rely on provider-specific memory.

Those approaches can reduce cost, but they can also blur distinctions such as:

- current vs. historical,
- observed vs. planned,
- authoritative vs. disputed,
- active vs. superseded,
- prerequisite vs. consequence.

Hive's thesis is that those distinctions should be represented explicitly and tested by downstream task correctness.

## Product direction

The planned V1 is a provider-neutral SDK that sits beside an existing model-backed workflow:

```text
workflow history
      |
      v
versioned semantic state
      |
      v
compact task context + omissions
      |
      v
capability / sufficiency gate
      |
      +---- insufficient ----> fuller context / stronger model
      |
      v
existing model or API
      |
      v
outcome + token / latency / cost telemetry
```

The intended deployment mode starts in **shadow mode**. Hive does not need production authority to be evaluated: Raw and Hive-backed calls can be compared on frozen tasks before anything serves live traffic.

## Current evidence

On a sealed synthetic benchmark, the engineered C1 semantic-state representation reduced:

- **supplied-state bytes by 81.1%**,
- **input tokens by 58.0%**, and
- **generation cost by 54–57%**,

while producing the same aggregate observed correct counts as Raw within each tested model arm:

| Solver | Raw | C1 |
|---|---:|---:|
| Luna | 156 / 160 | 156 / 160 |
| Sol | 160 / 160 | 160 / 160 |

This is **not** a production-savings claim and **not** a proof of statistical equivalence. The benchmark is synthetic, the representation is engineered rather than autonomously learned, and the reported cost reduction covers model generation rather than the entire state-construction lifecycle.

See [EVIDENCE.md](EVIDENCE.md) for the benchmark summary, caveats, negative evidence, and artifact identifiers.

## Why the state contract matters

The current representation explicitly tracks several classes of answer-changing state:

- **Temporal state** — effective time, current vs. historical, validity windows, supersession.
- **Epistemic authority** — observed, inferred, planned, disputed, false, and unknown.
- **Causal structure** — prerequisites, effects, dependencies, provenance, and rollback.

A separate ablation study removed the `kind`, `authority`, and `status` bundle and performance fell from **160 / 160 to 26 / 160**, with large increases in illegal promotions and authority errors. That result is narrow to the benchmark, but it is evidence that the semantic distinctions were doing real work rather than acting as cosmetic compression labels.

## What Hive does when compact state is not enough

Hive's product direction is deliberately fail-closed:

1. confirm the solver is capable of the task,
2. compile only task-relevant state,
3. preserve provenance and record omissions,
4. run sufficiency / capability checks,
5. escalate to fuller context or a stronger model when the compact representation is not trustworthy,
6. measure correctness and full lifecycle cost.

The goal is not "compress everything." The goal is to learn **where compact semantic state is safe and economically useful, and where Raw context should remain in control**.

## Design-partner target

Hive is looking for teams operating persistent **AI coding-agent workflows** where:

- history grows across many interactions,
- later calls reuse earlier facts and decisions,
- chronology or authority can change the correct action,
- current context spend is measurable,
- task outcomes can be scored,
- and Raw-vs-Hive shadow testing is permitted.

The first engagement is intended to be a shadow evaluation with frozen success criteria and a before/after cost model that charges every Hive lifecycle cost.

There are currently **no production customers, no revenue, and no claimed production savings**.

## Research lineage

Hive has gone through several narrower research phases, including structural patch safety, lesson-memory experiments, and executable regression memory. Those systems are not being erased from the project history; they are part of the experimental lineage that narrowed the current commercial thesis.

See [RESEARCH_HISTORY.md](RESEARCH_HISTORY.md), [FINDINGS.md](FINDINGS.md), and [HIVE_RELIABILITY_REPORT.md](HIVE_RELIABILITY_REPORT.md).

## Current boundary

Hive is a **research prototype and benchmark apparatus**, not a finished production SDK.

The next proof is straightforward to state and difficult to earn:

> Can Hive automatically construct and maintain trustworthy semantic state from real coding-agent histories cheaply enough that total dollars per correct task improve after extraction, validation, updates, storage, retries, corrections, and escalations are all charged?

That is the work the project is now organized around.

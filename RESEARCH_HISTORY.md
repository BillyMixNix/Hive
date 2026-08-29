# Hive research history

Hive did not begin as a finished semantic-state product. The current commercial wedge is the result of several narrower systems being built, tested, broken, and retained as evidence.

This file exists so the public repository does not pretend those earlier generations never happened.

## 1. Structural patch safety and executable verification

An early Hive focus was controlling whether model-generated code changes were safe enough to accept.

The May 2026 reliability work tested structural and adversarial patch cases. It demonstrated strong rejection of malformed, syntactically broken, wrong-target, oversized, and several other unsafe patch classes while also exposing an important blind spot: a structurally valid patch could still change behavior in the wrong way.

That failure was useful. A focused execution-based detector was then tested against the known intent-drift case and caught the targeted behavioral regressions in that baseline.

See [HIVE_RELIABILITY_REPORT.md](HIVE_RELIABILITY_REPORT.md).

### Lesson carried forward

**Claims are not authority. Executable checks decide whether a result is accepted.**

That principle remains central to the current product direction: compact state should not be trusted merely because it looks coherent.

## 2. Lesson memory and the regression-first coding-agent phase

Hive next explored whether remembered natural-language lessons could make a coding model less likely to repeat mistakes.

The lesson-system study found important limits:

- first-attempt behavior was not improved by lessons that only became relevant after a failure,
- exact-file lessons did not automatically generalize across files,
- lesson-family matching mattered,
- easy tasks saturated and left no measurable headroom,
- irrelevant lesson text could become prompt noise,
- and a calibrated live-model study still failed to show a convincing broad effect in the tested setup.

Those negative and mixed results are preserved in [FINDINGS.md](FINDINGS.md).

The project therefore narrowed its claim. Rather than asserting that prompts had made the model permanently smarter, Hive adopted an **executable regression-memory** boundary:

> once a failure can be expressed as a regression case, future accepted changes should not be allowed to repeat it.

That is the origin of the current `validation/regressions` machinery and the previous public README framing of Hive as a regression-first coding agent.

### Lesson carried forward

**The surrounding system can become harder to fool or regress even when the underlying model has not learned.**

That idea survives in today's state gates, replay, provenance, and fail-closed escalation.

## 3. From remembered text to explicit semantic state

The next research question became broader than patch memory:

> If a long-running AI workflow already processed an event once, why should every later model call need to reread the entire history — and how can we avoid losing the distinctions that change the answer?

That led to an explicit semantic representation for temporal state, epistemic authority, status, prerequisites, effects, provenance, supersession, and known unknowns.

The key shift was from asking whether a summary *sounds sufficient* to asking whether a capable solver can still reconstruct the correct task answer from the smaller representation.

A frozen crossed benchmark then compared Raw histories with an engineered compact representation (C1). In the tested synthetic setup, C1 reduced supplied-state bytes, input tokens, and generation cost while preserving the same aggregate observed correct counts within each tested solver arm.

A separate ablation deleting `kind`, `authority`, and `status` caused a large collapse in performance, providing evidence that those semantic fields were load-bearing for the benchmark.

See [EVIDENCE.md](EVIDENCE.md).

### Lesson carried forward

**Compression is only valuable when answer-changing meaning survives, the solver is capable, and the full lifecycle economics remain favorable.**

## 4. Current commercial wedge: AI coding agents

The project is now organized around a narrower product hypothesis:

**Hive is provider-neutral state middleware for persistent AI workflows, starting with AI coding agents.**

Coding-agent workflows are a useful first proving ground because they naturally contain:

- long interaction histories,
- repeated repository and tool context,
- old and superseded implementation decisions,
- claims that can be checked against executable artifacts,
- measurable model/context spend,
- and task outcomes that can often be scored.

The planned first customer-facing mode is **shadow evaluation**: run Hive beside an existing workflow, freeze the quality and accounting rules, and compare Raw versus compact-state operation before Hive is trusted with production authority.

## 5. What remains unproven

The project has **not** yet demonstrated that automatic state construction from messy real-world coding histories produces positive full-lifecycle economics.

The central open questions are:

1. Can Hive automatically extract and maintain trustworthy state from real histories?
2. Can it detect when that state is insufficient before a wrong answer is served?
3. Do the serving savings survive extraction, validation, correction, storage, and escalation costs?
4. Which coding-agent workloads benefit, and which should remain Raw?

Those are the questions the next SDK and design-partner studies are intended to answer.

## Repository note

This repository contains historical prototypes, experiments, reports, and side tooling from multiple generations of Hive. Their presence is intentional for lineage and reproducibility, but **not every directory represents the current V1 product surface**.

The current public entry points are:

- [README.md](README.md) — product framing and current direction
- [EVIDENCE.md](EVIDENCE.md) — current semantic-state evidence and claim boundary
- [FINDINGS.md](FINDINGS.md) — preserved lesson-memory findings and negative results
- [HIVE_RELIABILITY_REPORT.md](HIVE_RELIABILITY_REPORT.md) — earlier patch-safety evidence and known blind spots

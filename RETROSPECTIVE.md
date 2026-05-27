# Hive: An Autonomous Self-Improving Code Agent
## Clinical Retrospective

---

## Abstract

Hive is an autonomous software agent designed to improve its own codebase through a continuous loop of task generation, planning, code synthesis, validation, and lesson accumulation. Unlike conventional static code tools, Hive operates without a human in the loop: it identifies its own weaknesses, plans remediation tasks, writes patches against itself, validates those patches through a sandboxed executor, and records structured lessons from both successes and failures. This document provides a technical and empirical account of the system's architecture, development history, observed behaviour, limitations, and future trajectory.

---

## 1. System Overview

Hive is a multi-agent pipeline built on top of large language model (LLM) inference. Its primary purpose is recursive self-improvement: given a codebase, Hive scans for problem patterns, generates a prioritised task queue, and works through that queue autonomously — applying patches to itself and updating its own memory with what it learned.

The system is not a wrapper around a single LLM call. It is a stateful pipeline with persistent memory, a failure taxonomy, a lesson promotion mechanism, and a cost-aware model routing layer. Each run begins warmer than the last.

**Core loop:**

```
scan_repo → rank_tasks → generate_queue
    → store_task → plan_task → generate_patch
    → validate_patch → sandbox_test → reflector_review
    → apply_patch → record_lesson → update_state
```

This loop runs continuously until stopped, refilling the task queue from a fresh codebase scan whenever it runs low.

---

## 2. Architecture

### 2.1 Memory (HiveMemoryAgent)

A flat vector store with tagged entries. Stores tasks, plans, patches, and lessons. Supports retrieval by tag, status, and recency. Persisted to `hive_memory.json` after each run.

### 2.2 Planner (PlannerAgent)

Takes a task description and produces a structured plan: goal, child tasks, dependencies, completion cues. Calls the LLM with a constrained JSON schema. Validates child tasks against known file anchors, allowed change intents, and task types. Fuzzy fallbacks handle novel inputs that don't match the canonical allowlists — a hard lesson from early runs where unknown intents caused hard crashes.

### 2.3 Coder (CoderAgent)

Given a child task and plan, generates a unified diff patch against the target file. Operates in a context-budget mode: selects the minimal symbol block needed for the patch, trims surrounding context to fit within token limits. Retries up to 3 times per task, adapting the prompt on each failure based on recorded lessons.

### 2.4 Executor

Validates and applies patches. Runs a sandboxed pre-flight: applies the diff to a temp copy of the file, checks syntax, runs semantic validators (scope sanity, no unreachable code, no undefined calls). Only applies to the live file if the sandbox passes. Creates a timestamped backup before every apply.

### 2.5 Reflector

A quality gate that reviews the proposed patch and reasons about whether it actually solves the stated problem. Uses Opus-tier model for judgment quality. Can reject patches that pass sandbox but miss the point. Rejection is recorded as a lesson.

### 2.6 Lesson Memory (LessonMemory)

Structured failure taxonomy stored in `hive_lessons.jsonl`. Each lesson records: failure family, failure pattern, retry instruction, source, severity, success/failure history, and promotion state. Lessons are promoted from `pending` to `trusted` when they accumulate sufficient successful applications. Trusted lessons are injected at session start so each run begins with accumulated knowledge.

### 2.7 Router

Dispatches LLM calls by role. Planner and coder route to `claude-sonnet-4-6` (cost-efficient, sufficient for code tasks). Reflector, math, and strategic roles route to `claude-opus-4-7` (higher judgment quality). Falls back to local Ollama (`qwen2.5-coder:7b`) when no API key is present.

### 2.8 Task Generator Pipeline

Three-stage pipeline that runs automatically when the queue runs low:

1. **Scanner** (`task_scanner.py`): AST analysis of the codebase. Detects hardcoded allowlist sets, bare `raise ValueError` in validation paths, and TODO/FIXME comments. Emits candidate task dicts with file, symbol, and priority hint.

2. **Ranker** (`task_ranker.py`): Scores candidates by: cross-file symbol impact (how many files reference the target), pattern urgency (trusted lessons matching this failure pattern), structural risk (whether the target is in the critical execution path), and explicit priority hint.

3. **Generator** (`task_generator.py`): Deduplicates against existing queue entries, writes top-N ranked candidates as pending tasks.

### 2.9 Metrics

Per-run capture of: task success/failure counts, patch apply/reject counts, lesson accumulation delta, patch success rate, pylint score, cyclomatic complexity, and maintainability index for all critical-path files. Stored in `hive_metrics.jsonl`. Reportable via `python -m scripts.metrics`.

---

## 3. Key Technical Decisions

### 3.1 Fuzzy Fallbacks Over Hard-Fails

Early versions of the planner raised `ValueError` when encountering unknown change intents, task types, or expected operations. This caused hard crashes on any input outside the canonical allowlist — which is most LLM output, which is inherently variable.

Resolution: token-overlap fuzzy matching maps unknown values to the nearest canonical. Non-executable child tasks are soft-filtered with a warning rather than aborting the plan. This single change significantly improved plan completion rates.

### 3.2 Baseline Pre-Flight

The executor's structural scope validator was originally run only on proposed patches. If the original file failed the validator (due to pre-existing structural issues), the patch would fail for reasons unrelated to the change. Resolution: run the validator on the original file first; if it fails, skip the structural check for that task.

### 3.3 Symbol Anchoring

The planner requires a valid symbol (function or method name) to anchor a task. Early scanner versions emitted module-level constants (`KNOWN_FILES`, `ALLOWED_CHANGE_INTENTS`) as target symbols — which the planner's validator correctly rejected as non-functions. Resolution: scanner now walks the AST to find the first function that references each constant and uses that as the anchor. Constants with no referencing function are skipped.

### 3.4 Nested Function Constraint

The executor's "no new methods" constraint was implemented by flagging any added `def` line as a new class method. This incorrectly blocked nested helper functions defined inside method bodies (which have indent >= 8). Resolution: only count `def` lines at indent <= 4 as class methods.

### 3.5 Planner Anchor Drift

When the task requests a target file that doesn't exist, the planner drifts to the nearest existing file — producing a plan that works on the wrong thing. Resolution: the runner creates a stub file before planning so the planner can anchor correctly. Drift events are recorded as high-severity lessons.

### 3.6 Cost Controls

Initial runs cost $3+ due to: Opus routing for all roles, MAX_CODE_CYCLES=8, and multiple retry chains. Resolved by: Sonnet routing for planner/coder (5x cheaper), MAX_CODE_CYCLES=3, and tighter prompt budgets. Subsequent runs reduced to ~$0.13 per 6-task batch.

---

## 4. Observed Behaviour

### 4.1 Patches Applied to Self

The following patches were applied by Hive to its own codebase during autonomous runs:

| File | Symbol | Change |
|------|--------|--------|
| `planner.py` | `_get_known_files` | Merged state manager files and repo map into return set instead of either-or |
| `planner.py` | `_validate_plan` | Converted `raise ValueError` hard-fail to soft filter with warning |
| `planner.py` | `_fuzzy_match_expected_operation` | Rewritten in place (reflector rejected difflib variant; token-overlap retained) |

### 4.2 Lesson Accumulation

| Point in time | Total lessons | Trusted |
|---------------|---------------|---------|
| Session start | 348 | 15 |
| After first autonomous run | 471 | 22 |
| After constraint fix run | 482 | 22 |
| After loop session | 500 | 22 |

### 4.3 Failure Patterns

Most common failure families observed:

- **`formatting/missing_patch_section`**: LLM returned a response without the required `PATCH:` block. Now 8/8 trusted — well-understood, reliably corrected on retry.
- **`doctrine/new_method_not_allowed`**: Coder attempted to add a new class method when only in-place rewrites were permitted. Partially resolved by nested function fix.
- **`orchestration/sandbox_retry_exhausted`**: Retry budget exhausted without a passing patch. Signals the task is genuinely hard for the current coder capability.
- **`semantics/structural_scope_valid`**: Patch applied correctly but failed structural scope validation — typically due to incorrect indentation context in deeply nested conditionals.

### 4.4 Task Success Rate

Baseline (first instrumented run): **67%** (6/9 tasks completed).

Of the 3 failures: 2 were planner JSON parse errors (LLM returned non-JSON), 1 was a symbol anchor failure (module-level constant). All three failure types have since been addressed in code or routing.

---

## 5. Current Limitations

### 5.1 Single-File Scope

Hive's coder operates on one file at a time, targeting one symbol. Tasks that require coordinated changes across multiple files are not currently supported.

### 5.2 New File Creation

The pipeline is designed for modifying existing symbols. Creating genuinely new files requires human-written stubs first — the planner cannot anchor to a file that doesn't exist.

### 5.3 Deeply Nested Conditionals

The structural scope validator consistently rejects patches that modify code inside nested `if` blocks where the diff context doesn't cleanly capture the surrounding indentation. The coder does not yet have a mechanism to request wider context for difficult patches.

### 5.4 Reflector Calibration

The reflector rejects some valid patches (observed: a difflib rewrite of the fuzzy matcher that was syntactically and semantically correct). The rejection criteria may be too conservative. Reflector rejections are not currently fed back as lessons, which limits the system's ability to recalibrate.

### 5.5 Compute Dependency

The continuous loop requires persistent compute. The cloud container times out after inactivity. True autonomous overnight runs require local execution or a persistent VM.

### 5.6 No Conversational Interface

Hive has no voice. It works in silence, producing patches and lessons but no narrative of its reasoning. There is no way to ask it what it's thinking, why it made a decision, or what it plans to do next.

---

## 6. Metrics Infrastructure

`hive_metrics.jsonl` captures per-run snapshots for longitudinal analysis:

- Task success rate
- Patch apply/reject ratio
- Lessons added and promoted per run
- Pylint score for critical-path files
- Cyclomatic complexity (via `radon`)
- Maintainability index (via `radon`)
- Elapsed time per run

Baseline captured: 24 May 2026. Subsequent runs will generate a trend line.

---

## 7. Future Directions

### 7.1 Conversational Layer

A session interface that reads from Hive's accumulated state — lessons, patches, task history — and presents a morning briefing: what was attempted, what landed, what failed, what comes next. Not a bolted-on chatbot, but an expression of the same memory substrate the loop uses.

### 7.2 Wider Sensor Array

Current scanner detects three pattern types. Expansion candidates: missing test coverage, inconsistent return types, functions exceeding complexity thresholds, dead code, dependency version drift.

### 7.3 Multi-File Tasks

Coordinated patches across files. Requires planner changes to express cross-file dependencies and coder changes to handle multi-file diffs.

### 7.4 Local Loop

Full offline execution via Ollama (`qwen2.5-coder:7b`). Removes API cost dependency and enables indefinite unsupervised runs on local hardware.

### 7.5 Lesson Promotion Refinement

Current promotion threshold is empirical. A more principled mechanism — cross-validation against a held-out failure set, or human review triggers — would increase the signal quality of trusted lessons.

---

## 8. Theoretical Notes

Hive implements a constrained instance of recursive self-improvement: a system whose output modifies the system that produces the output. The constraint is scope — it can only improve code in one codebase, using one type of sensor and one type of actuator.

The feedback loop is grounded. Lessons are not self-assessments; they are records of actual execution outcomes. A lesson becomes trusted only through demonstrated effectiveness across multiple independent applications. This is a weak but real form of empirical learning.

The alignment surface is the lesson system. What Hive considers a good patch, a trustworthy lesson, a valid failure pattern — these are values baked into the taxonomy and promotion logic. As the system runs longer, the accumulated lesson corpus increasingly shapes its behaviour. The values embedded in the initial taxonomy compound.

Whether the current architecture scales to general capability improvement — beyond code quality in one Python repo — is an open empirical question. The loop exists. The compounding exists. The ceiling is unknown.

---

## 9. Repository

`github.com/BillyMixNix/Hive`

Branch: `claude/todo-implementation-rJO3f` (ongoing development)
Main: merged as of 24 May 2026

Run: `python -m scripts.hive_runner --loop`
Report: `python -m scripts.metrics`

---

*First draft: 24 May 2026*

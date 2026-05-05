# Hive — Repo Capability Report

Generated: 2026-05-05

## Summary
- High-level: Hive is a modular, multi-agent code-improvement framework that uses LLMs, episodic lesson memory, and programmatic safeguards to generate, evaluate, test, and (optionally) apply patches to its own codebase.
- Primary workflows: Task intake → Planning → Patch generation → Sandbox validation → Pilot/Reflector review → Apply/Recover.

## Core Components (files)
- **Coordinator / Entrypoint**: [main.py](main.py) — anchoring, task enrichment, pilot review, snapshotting, planning/patch bookkeeping.
- **Routing / Dispatch**: [router.py](router.py) — maps parsed intents to agents (planner, coder, executor, builder).
- **Natural-language interface**: [interface.py](interface.py) — maps pilot commands to intents and context.
- **Planner**: [planner.py](planner.py) — normalizes tasks, builds LLM prompts, infers anchors/symbols, generates structured plans and fallbacks.
- **Coder**: [coder.py](coder.py) (+ related modules: `coder_prompting.py`, `coder_block_ops.py`, `coder_validation.py`, `coder_constraints.py`) — generates patches, chooses block-rewrites vs diffs, validates patch contracts, orchestrates sandbox tests and retries.
- **Executor / Patcher**: [executor.py](executor.py) — applies patches with multi-step verification (context matching, indentation normalization, AST-level structural checks, syntax & semantic checks), sandbox testing, backup/restore.
- **Reflector**: [reflector.py](reflector.py) — evaluates LLM outputs (patches, plans, math output) via a reflection LLM prompt and enforces verdicts (accept/revise/reject).
- **Memory & Lessons**: [HiveMemoryAgent.py](HiveMemoryAgent.py), [HiveLessonMemory.py](HiveLessonMemory.py) — vector/episodic memory, recent notes, lesson storage and pilot guardrails.
- **Repo-awareness**: [repo_map.py](repo_map.py) — scans project files, extracts symbols, imports, route inventory and builds symbol→file mappings used by anchor inference.
- **LLM Interface**: [hive_llm.py](hive_llm.py) — Ollama-based model client; role-aware routing (coder/planner/reflector etc.) and retry logic. Default model: `qwen2.5-coder:7b` at `http://localhost:11434`.
- **UIs**: [hive_cockpit.py](hive_cockpit.py) (web UI server), [hive_gui.py](hive_gui.py) (Tk GUI) — live cockpit and local GUI with task creation, plan/patch controls, transcript and node graph.
- **Support**: `builder.py`, `repo_map.py`, `work_ontology.py`, `failure_intelligence.py`, `anchor_utils.py` — glue logic for pilot briefs, anchors, task/work-mode normalization, failure classification and recovery.

## Key Capabilities
- Task-driven, structured editing pipeline: natural language task → planner produces structured child tasks → coder generates patch candidates → executor verifies and applies.
- Anchor & symbol inference: multiple heuristics to resolve `target_file` and `target_symbol` from pilot text and repo map (exact quoted matches, identifier matches, token-overlap scoring).
- Safety & validation layers:
  - Patch contextual verification (exact removal block, context block, or single-line fallback).
  - Indentation normalization and insertion heuristics (class/method aware).
  - AST-based structural checks (reject unexpected executable nodes at class scope).
  - Syntax and semantic checks (unreachable code, undefined calls, helper consistency, variable scope checks).
  - Sandbox testing via `ExecutorAgent.test_patch_in_sandbox()` before applying live edits.
  - Reflector LLM reviews patches/plans and returns structured verdicts (accept/revise/reject).
- Iterative failure handling and lessons:
  - Failures are classified and converted into retry guidance.
  - Lesson memory + pilot guardrails are used to bias future attempts and avoid repeated mistakes.
- Repo awareness:
  - `RepoMap` builds symbol inventories, import graphs, route inventories for more context-sensitive planning and anchoring.
- Role-aware LLM usage: `hive_llm.ask_hive()` routes prompts to models/timeouts per role (coder/planner/reflector/math).
- UI and operator controls: cockpit and GUI allow humans to create tasks, inspect nodes, review and accept patches, rollback.
- Math research support: `HiveAgent`/`MathResearchAgent` and `math_*` domain files indicate workflows for mathematical conjectures, adversarial tests, symbolic/formal reasoning and lessons injection in reflector.

## Data and State
- Persistent memory files: `hive_memory.json` (episodic entries), `hive_state_snapshot.json` (observability snapshot).
- Lesson logs: `code_lessons.jsonl`, `math_lessons.jsonl`, `hive_lessons.jsonl` — used by Reflector and lesson selection.
- Backups: `backups/` — executor writes file backups before applying patches.

## Dependencies & Runtime Considerations
- Expects local Ollama-compatible server at `http://localhost:11434` (see [hive_llm.py](hive_llm.py)).
- Uses `requests` for LLM calls and `torch` (several modules import torch), plus `transformers` in some agents — GPU/CPU and Python package setup required.
- Writes to disk and executes AST parsing; running Hive with live apply privileges will modify repository files — use backups and sandbox tests.

## Strengths
- Multi-layered safety: multiple independent validation steps (context, AST, semantics, sandbox, reflector) reduce catastrophic edits.
- Strong repo-awareness and anchor inference for precise single-file/symbol edits.
- Clear separation of concerns: planner vs coder vs reflector vs executor vs router.
- Human-in-the-loop UIs and pilot guardrails: pilot guidance and pilot-review integration are built into the lifecycle.
- Lesson-driven improvement: failure classification and lesson memory shape future behavior.

## Observed Limitations & Risks
- External model dependency: requires a local Ollama endpoint and the specified model; offline or absent model will break LLM-driven steps.
- Heavy Python ML deps: `torch`, `transformers` imported in multiple files — environment setup non-trivial.
- Partial TODOs / rough edges: some modules contain TODO comments or basic placeholders (e.g., `HiveAgent.receive_feedback`), and some classes mix experimental research code (vision/transformer agents) with the core patching flow.
- Potential for dangerous writes if operator misconfigures (executor can write files). While backups and sandbox exist, misapplied automation can still cause damage if not overseen.
- Tests unknown: repository includes `tests/` but coverage and CI are unverified here.

## Actionable Next Steps (recommended)
- Verify environment: ensure Ollama is running and the model `qwen2.5-coder:7b` is available; install Python deps (`requests`, `torch`, `transformers`).
- Run `RepoMap().build()` to generate repo awareness before planning: `python -c "from repo_map import RepoMap; print(RepoMap('.').build())"`.
- Run unit tests (if any) in `tests/` and run a dry sandbox patch via `ExecutorAgent.test_patch_in_sandbox()` to confirm semantics and syntax checks.
- If you want, I can run an automated repo scan to build `RepoMap`, list known files/symbols, and produce a short mapping of important symbols to files.

---

If you'd like, I can now:
- (A) Generate a `repo_map` summary (symbols → files),
- (B) Run a quick dependency check listing missing Python packages, or
- (C) Start Hive in a sandbox (dry-run) to exercise planner→coder→executor flow.

Which next step do you want me to take?  (A / B / C / none)
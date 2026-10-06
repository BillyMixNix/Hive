# Nix Workshop Feature Backlog

Last updated: 2026-09-29  
Baseline: v0.11.0

This file is the human-maintained feature catalog and backlog. Feature IDs are stable references; changes to scope or acceptance criteria change the specification hash used by the preview-and-confirm flow. A backlog entry is a request and evidence index, not proof that behavior exists. Hive must inspect the current repository and verify the requested behavior before planning edits.

## Status meanings

- **Existing / verified** — confirmed in source and supported by a test or preserved run evidence.
- **Planned** — defined sufficiently for a user to select and confirm for Hive Build.
- **Queued / needs definition** — reserved for later, but lacks a complete executable specification.
- **Proposed / unapplied** — a Hive run produced a proposal, but it has not been applied and is not part of the verified baseline.

## Existing behavior

### NW-F001 — Hive job stage and percentage visibility

- **Status:** Existing / verified in v0.11.0 source
- **Objective:** Show the current Hive Build stage and percentage while a build runs.
- **Scope:**
  - The Hive Build UI polls `GET /api/jobs/{job_id}`.
  - The UI displays the host-reported job message and percentage.
  - The endpoint returns `Job.as_dict()`, including `state`, `progress`, and `message`.
- **Dependencies:** Existing job telemetry in `app.py` and `workshop/runtime.py`.
- **Acceptance criteria:**
  1. A running build shows the current stage message and percentage.
  2. Terminal states remain truthful and are not overwritten by stale updates.
- **Constraints:** Do not create a second progress mechanism unless repository evidence shows the existing flow is insufficient.
- **Evidence:** Source paths `app.py`, `workshop/runtime.py`, `static/index.html`; diagnostic run `833356e1a4f0`.

## Planned work

### NW-F002 — Cross-layer existing-behavior recognition

- **Status:** Planned
- **Objective:** Let Hive determine from repository evidence whether requested behavior already exists across backend endpoints, state producers, and frontend call/render paths.
- **Scope:**
  - Statically connect route responses to local state producers and frontend consumers when the links are explicit in source.
  - Report the files and symbols that support a coverage conclusion.
  - Distinguish complete, partial, and unknown coverage.
- **Dependencies:** Repository-grounded route/response facts and bounded UI retrieval.
- **Acceptance criteria:**
  1. For the unchanged progress-visibility request against v0.11.0, report the feature as already satisfied with source evidence and propose no edits.
  2. If only part of the behavior exists, identify the missing layer instead of proposing duplicate work for satisfied layers.
  3. Treat dynamic or ambiguous flows as unknown; do not infer full coverage from names or comments alone.
  4. Tests cover complete, partial, and unknown/dynamic behavior.
- **Constraints:** Source and tests remain authoritative. Do not weaken ownership, edit validation, verification, review, human approval/apply, or rollback.
- **Evidence:** Live progress-visibility run `833356e1a4f0`.

### NW-F003 — Evidence-backed no-change result

- **Status:** Planned
- **Objective:** Give Hive a clear terminal result when repository evidence proves the requested behavior is already satisfied.
- **Scope:**
  - Return an explicit no-change disposition with source/test evidence.
  - Skip implementation workers when no edits are needed.
  - Persist the disposition in the run artifact with an empty diff and `applied=false`.
- **Dependencies:** NW-F002.
- **Acceptance criteria:**
  1. The result identifies the relevant files, symbols/routes, and tests that establish coverage.
  2. No worker receives an edit assignment when no change is needed.
  3. Unknown or incomplete evidence does not produce a false no-change result.
  4. Tests distinguish complete coverage from partial coverage.
- **Constraints:** A no-change result must not claim reviewer approval or application when those steps did not occur.

### NW-F004 — Partial-coverage planning

- **Status:** Planned
- **Objective:** Activate only the roles needed to implement behavior that is genuinely missing, treating verified existing components as satisfied dependencies.
- **Scope:** Planner coverage decisions for existing provider/UI/test portions of a cross-layer request.
- **Dependencies:** NW-F002 and NW-F003.
- **Acceptance criteria:**
  1. A fully satisfied cross-layer request produces no edit workers.
  2. If an API exists but the UI is missing, assign UI and appropriate tests without redundant backend work.
  3. If the API is missing, backend work remains available and is assigned when required.
  4. Exact ownership, shared-interface contracts, and all existing safety gates remain enforced.
- **Constraints:** Do not infer missing behavior from worker preference or from the overall feature spanning multiple roles.

### NW-F005 — Build from a feature ID

- **Status:** Implemented / candidate verification passed; one existing symlink test is blocked by Windows privileges
- **Objective:** Let a user select a catalog entry by stable ID, such as `Build NW-F002`, and have Hive work from that exact specification.
- **Scope:**
  - Provide a read-only preview of the catalog entry.
  - Show the objective, scope, dependencies, acceptance criteria, and constraints and require explicit confirmation in the UI.
  - Revalidate the selected specification hash before queueing a build.
  - Store the resolved feature ID, full structured specification, original command, and hash in the run metadata.
- **Dependencies:** A structured, versioned catalog stored in `FEATURES.md`.
- **Acceptance criteria:**
  1. Resolve an ID to the exact title, status, objective, scope, dependencies, acceptance criteria, constraints, and evidence stored in this catalog.
  2. Unknown, malformed, non-planned, incomplete, or changed specifications fail closed before a job starts.
  3. Preserve the resolved entry and original command in the run artifact for traceability.
  4. Feature selection does not replace repository inspection, planner validation, exact worker ownership, verification, review, or explicit human approval/apply.
  5. Ordinary free-form Hive requests keep their existing behavior.
- **Constraints:** Do not treat catalog text as file authorization, do not grant extra worker scope, and never apply automatically.
- **Evidence:** Implemented in the v0.11.1 candidate; see `workshop/feature_catalog.py` and feature-ID regression tests.

## Queued

### NW-F006 — Genuine multi-file coding benchmark

- **Status:** Queued / needs definition
- **Objective:** Exercise a real feature that spans multiple files after cross-layer coverage recognition is implemented.
- **Scope:** To be defined from a concrete user-selected feature.
- **Dependencies:** NW-F002 through NW-F004.
- **Acceptance criteria:** Define measurable behavior and tests before Hive is asked to build it.
- **Constraints:** Do not invent a benchmark feature or treat this placeholder as an executable request.

## Proposed, not applied

The v0.10.5 Qwen runs for a Settings Workshop-version display and an Ollama-connection display reached `READY`, but their generated proposals were not applied. They are experiments, not verified installed features. The Ollama-connection proposal is recorded as run `84c897d26f84` in prior run notes.

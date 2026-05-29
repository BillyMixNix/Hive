# Hive Validation Gate — Implementation Review

**Branch:** `claude/phases-1-3-4Jshu`  
**Commits:** `7a84ea5`, `0491cbe`, `c59170e`  
**Spec:** HIVE_VALIDATION_GATE_SPEC.md v1.0  
**Reference:** Darwin Gödel Machine (arXiv:2505.22954), Voyager (arXiv:2305.16291), ExpeL (arXiv:2308.10144)  
**Baseline benchmark score:** 1.0 (40/40) — confirmed unchanged after all changes

---

## The Gap Closed

Before this branch: a patch that ran without crashing was treated as a win.

After this branch: every self-modification is validated on a benchmark before it sticks. Rejected changes write a lesson rather than silently disappearing. The live codebase is never touched until a variant has provably beaten the baseline by more than the measured noise band.

---

## Architecture Overview

```
evaluate(patch, task_note, anchors)
    │
    ├── 1. anchors_satisfied()          — file-target + import guard
    ├── 2. make_variant()               — copy repo to sibling dir
    ├── 3. apply_patch_to_variant()     — patch the copy, not main
    ├── 4. self_verify()                — syntax + importability check
    ├── 5. score_variant(repo_root, n)  — baseline: N subprocess runs
    ├── 5. score_variant(variant, n)    — variant: N subprocess runs
    ├── 6. compute_stats()              — delta, noise_band = k × pooled_stdev
    │
    ├── ACCEPT (delta > noise_band)
    │       _promote()                  — copy file: variant → repo_root
    │       _write_success_memory()     — win entry → success_memory.jsonl
    │
    └── REJECT (delta ≤ noise_band)
            main untouched
            _write_failure_lesson()     — lesson → hive_lessons.jsonl
    
    finally (always)
        archive.append()                — record + diff + pre_patch_content
        discard_variant()               — rm -rf the variant dir
```

**Non-negotiable invariant:** `repo_root` is only written at `_promote()`. Everything before that is in the isolated copy.

---

## Files Created

### `validation/__init__.py`
Empty package marker. Enables `from validation.gate import evaluate`.

---

### `validation/scoring.py` — 45 lines

Pure-math scoring helpers. No I/O.

| Function | Purpose |
|---|---|
| `pooled_stdev(base_scores, var_scores)` | Standard deviation of the combined score distribution |
| `compute_stats(base_scores, var_scores, k=2.0)` | Returns full stats dict for the accept/reject decision |

**Output of `compute_stats`:**
```json
{
  "baseline_scores": [1.0, 1.0, 1.0, 1.0, 1.0],
  "variant_scores":  [0.95, 0.97, 0.96, 0.95, 0.96],
  "baseline_mean": 1.0,
  "variant_mean": 0.958,
  "delta": -0.042,
  "noise_band": 0.036,
  "k": 2.0
}
```

Acceptance criterion stated once: `delta > noise_band`.

---

### `validation/variant.py` — 143 lines

Isolated copy management. The live repo is never touched here.

| Function | Signature | Purpose |
|---|---|---|
| `make_variant` | `(repo_root, variant_id=None) → (Path, str)` | `shutil.copytree` to sibling `_variant_{id}/` |
| `apply_patch_to_variant` | `(variant_dir, patch_text, target_file=None) → (bool, str\|None)` | Calls live `ExecutorAgent.apply_patch()` at the variant path |
| `self_verify` | `(variant_dir, task_note, patch_text, target_file=None) → (bool, str)` | Syntax compile + subprocess import check |
| `score_variant` | `(codebase_dir, n=1) → list[float]` | Runs `benchmark_harness.py --score` as subprocess N times |
| `discard_variant` | `(variant_dir)` | `shutil.rmtree` |

**Why subprocess scoring:** running `benchmark_harness.py` with `cwd=variant_dir` causes Python to import the variant's module code rather than the live code. Behavioral differences from the patch are captured correctly.

---

### `validation/gate.py` — 319 lines

The orchestrator.

**Primary function:**
```python
evaluate(
    patch,          # Hive-format patch string
    task_note,      # Human description of intent
    anchors=None,   # {"target_file": "x.py", "no_new_imports": True}
    repo_root=None, # Defaults to Hive root
    n=5,            # Benchmark runs per side
    k=2.0,          # Noise multiplier (~2σ)
    variant_id=None # Optional explicit ID
) -> dict           # Full validation record
```

**Validation record shape:**
```json
{
  "variant_id": "v_20260529_171938_6ca727",
  "parent_id": "main@/home/user/Hive",
  "task_note": "...",
  "patch_summary": "...",
  "target_file": "interface.py",
  "anchors_checked": ["target_file"],
  "self_verified": true,
  "baseline_scores": [1.0],
  "variant_scores": [0.875],
  "baseline_mean": 1.0,
  "variant_mean": 0.875,
  "delta": -0.125,
  "noise_band": 0.1768,
  "decision": "reject",
  "reason": "no_significant_gain: delta -0.1250 <= noise_band 0.1768",
  "timestamp": "2026-05-29T17:19:38Z",
  "k": 2.0
}
```

**`anchors_satisfied(patch_text, anchors) → (bool, list[str])`**  
Supported anchor keys:
- `target_file` — patch `TARGET_FILE:` header must match
- `no_new_imports` — no `+import` or `+from` lines in the diff

**`gated_apply(patch_text, task_note, anchors, repo_root, n=1, k=2.0) → (bool, dict)`**  
Drop-in wrapper for the live loop in `main.py`. Returns `(accepted, record)`. If accepted, the file is already written by `_promote()`.

**`__main__` demo:**
```bash
python -m validation.gate 1    # n=1, fast
python -m validation.gate 5    # n=5, ~2σ confidence
```

---

### `validation/archive.py` — 98 lines

Append-only JSONL. Storage: `validation/archive.jsonl`.

Every variant tried is recorded here — accepted and rejected both. Rejected variants are data, not garbage (DGM principle).

| Function | Purpose |
|---|---|
| `append(record, patch_text, pre_patch_content)` | Appends one line: full record + diff + pre-patch file content |
| `read_all()` | All entries, oldest first |
| `get_by_variant_id(vid)` | Lookup by variant ID |
| `rollback(variant_id, repo_root)` | Writes `pre_patch_content` back — no diff reversal needed |

**Rollback example:**
```python
from validation.archive import rollback
rollback("v_20260529_171938_6ca727", repo_root="/home/user/Hive")
# → True
```

---

### `success_memory.py` — 192 lines

ExpeL-style win-signal store. Mirrors `HiveLessonMemory` but for accepted patches.

Each entry stores **both** the concrete trajectory and the abstract rule — ExpeL's key finding: action-heavy retrieval wants the trajectory; reasoning-heavy retrieval wants the rule.

**Entry shape:**
```json
{
  "id": "win_4e2a1c9f8d30",
  "signal": "patch targeting executor.py accepted by gate",
  "trajectory_ref": "archive.jsonl:v_20260529_001",
  "abstract_insight": "validate inputs at the boundary before mid-function use",
  "weight": 1.2,
  "wins": 2,
  "losses": 0,
  "timestamp": "2026-05-29T..."
}
```

**Memory ops (ExpeL pattern):**

| Method | Op | Behaviour |
|---|---|---|
| `add_win(signal, trajectory_ref, abstract_insight)` | ADD | Appends new win, `weight=1.0` |
| `upvote(win_id, delta=0.1)` | UPVOTE | `weight += delta`, `wins += 1` |
| `downvote(win_id, delta=0.1)` | DOWNVOTE | `weight -= delta` (floor 0), `losses += 1` |
| `edit(win_id, **updates)` | EDIT | Updates any non-protected field |
| `merge(keep_id, drop_id)` | MERGE | Collapses duplicates, sums wins/losses, averages weight |
| `prune(floor=0.1)` | PRUNE | Removes entries below weight floor |
| `find_relevant(context, limit)` | Retrieval | Scores by weight + target_file signal match |
| `get_recent(limit)` | Retrieval | Last N entries |

---

## Files Modified

### `benchmark_harness.py`

Two additions, zero existing behaviour changed.

**`ReliabilityBenchmarkHarness.score()` — line 847**

Returns a structured numeric score over the fixed 40-case benchmark pack:
```python
{
  "score": 1.0,        # passed / total  (0.0–1.0)
  "passed": 40,
  "total": 40,
  "failed": 0,
  "per_band": {
    "comment_docstring":              {"passed": 10, "total": 10},
    "narrow_logic_edits":             {"passed": 10, "total": 10},
    "architectural_in_place_rewrites": {"passed": 10, "total": 10},
    "route_flow_state":               {"passed": 10, "total": 10}
  }
}
```

**`main()` updated — line 924**

`--score` flag redirects all debug output to stderr and writes only the JSON score dict to stdout. This is what `score_variant()` parses from the subprocess.

**`score_main(repo_root)` — line 918**

Module-level convenience: `ReliabilityBenchmarkHarness(repo_root).score()`.

---

### `benchmark_pack.py`

One line added at the top:
```python
BENCHMARK_PACK_VERSION = "1.0"
```

This constant must never change during an evolution run. If the task set drifts, cross-run scores are not comparable and the gate is meaningless. Freezing it in code makes the invariant explicit and auditable.

---

### `HiveStateManager.py`

Three methods added after `save_snapshot()` — lines 463–518.

| Method | Signature | Purpose |
|---|---|---|
| `save_tagged_snapshot` | `(tag, notes=None) → str` | Saves full state to `backups/hive_snapshot_{tag}.json` |
| `restore_tagged_snapshot` | `(tag) → bool` | Loads that path, syncs file state, returns success |
| `list_tagged_snapshots` | `() → list[dict]` | Lists `{tag, timestamp, notes, path}` dicts, newest first |

Used by the gate to checkpoint main before any evolution run. Every promotion is reversible by tag. The full lineage can be walked backward.

**Usage:**
```python
state = HiveStateManager()
state.save_tagged_snapshot("v_20260529_001", notes="before evolution run 3")
# ... evolution runs ...
state.restore_tagged_snapshot("v_20260529_001")   # undo
state.list_tagged_snapshots()
# [{"tag": "v_20260529_001", "timestamp": "...", "notes": "before evolution run 3", "path": "..."}]
```

---

### `HiveLessonMemory.py`

Three ExpeL ops added after `record_lesson_outcome()` — lines 808–849.  
Built on the existing `_rewrite_lessons()` atomic rewrite helper (no new file I/O patterns introduced).

| Method | Op | Behaviour |
|---|---|---|
| `upvote_lesson(lesson_id, delta=0.1)` | UPVOTE | `weight += delta`, `success_after_use += 1`, recomputes `promotion_state` |
| `downvote_lesson(lesson_id, delta=0.1)` | DOWNVOTE | `weight -= delta` (floor 0), `failure_after_use += 1`, recomputes `promotion_state` |
| `edit_lesson(lesson_id, **updates)` | EDIT | Updates any field except `lesson_id` and `timestamp` |

`weight` is a new field (defaults to `1.0` for existing entries). It coexists with the existing `success_after_use`, `failure_after_use`, and `promotion_state` counters — all ops work on both old and new lesson records.

---

### `main.py`

One block added in `_handle_patch_apply_route()` — lines 2664–2686.

Wraps the existing `router.executor.apply_patch()` call:

```
HIVE_GATE_MODE=0  (default) → direct apply, identical to pre-branch behaviour
HIVE_GATE_MODE=1             → gate.gated_apply() runs the full pipeline
```

**If gate rejects:**
- Returns `"Gate rejected patch {id}: {reason}"`
- Sets status `gate_rejected` in observability snapshot
- Disk is never written

**If gate accepts:**
- `_promote()` has already written the file
- All existing memory/state update code runs unchanged (lines 2686–2714)
- From the rest of `main.py`'s perspective, the file is just updated

**Tunable via environment:**

| Variable | Default | Purpose |
|---|---|---|
| `HIVE_GATE_MODE` | `0` | Enable gate (`1`/`true`/`yes`) |
| `HIVE_GATE_N` | `1` | Benchmark runs per side (raise for higher confidence) |
| `HIVE_GATE_K` | `2.0` | Noise multiplier (raise if accepting non-replicating patches) |

---

## Runtime Artifacts Committed

| File | Contents |
|---|---|
| `validation/archive.jsonl` | First archive entry from demo run — rejected variant with `pre_patch_content`, full diff, scoring data |
| `hive_lessons.jsonl` | One gate-sourced lesson appended: `file=interface.py`, `source=validation_gate`, `variant_id`, `delta`, `noise_band` |

---

## How to Use

**Run gate demo (verify end-to-end, Phase 3/4):**
```bash
cd /home/user/Hive
python -m validation.gate 1      # n=1, fast
python -m validation.gate 5      # n=5, ~2σ confidence
```

**Score the current codebase:**
```bash
python benchmark_harness.py --score
# → {"score": 1.0, "passed": 40, "total": 40, ...}
```

**Activate gate in the live loop:**
```bash
HIVE_GATE_MODE=1 HIVE_GATE_N=5 HIVE_GATE_K=2.0 python -m hive_runner
```

**Rollback a promotion by variant ID:**
```python
from validation.archive import rollback
rollback("v_20260529_171938_6ca727", repo_root="/home/user/Hive")
```

**Rollback via HiveStateManager snapshot:**
```python
from HiveStateManager import HiveStateManager
state = HiveStateManager()
state.restore_tagged_snapshot("v_20260529_171938_6ca727")
```

**Inspect what the gate has rejected:**
```python
from validation.archive import read_all
rejects = [e for e in read_all() if e["decision"] == "reject"]
for r in rejects:
    print(r["variant_id"], r["delta"], r["reason"])
```

---

## Parameters to Tune (Do Not Let the Agent Guess These)

| Parameter | Start | When to raise |
|---|---|---|
| `N` (runs per side) | 5 | If accepted patches don't replicate in subsequent cycles |
| `k` (noise multiplier) | 2.0 | Same signal — tighten the bar |
| `prune_floor` in SuccessMemory | 0.1 | If the win store grows without producing wins |
| `delta` in upvote/downvote | 0.1 | If weights converge too fast or too slow |

---

## What Phase 7 Requires

Per the spec, Phase 7 is "let it run." The gate infrastructure is complete. What's needed next:

1. Set `HIVE_GATE_MODE=1` in the runner environment
2. Run multiple unattended evolution cycles
3. Plot benchmark score across cycles

**The success condition is a chart:** score trending up, every accepted point provably above the prior baseline's noise band, and a non-empty `archive.jsonl` of rejected patches. The rejections are the proof the gate is honest. A flat line is also a real result — it tells you the gate is working correctly, just that no patches have been good enough yet.

---

## File Index

| File | Status | Lines | Purpose |
|---|---|---|---|
| `validation/__init__.py` | NEW | 2 | Package marker |
| `validation/scoring.py` | NEW | 45 | Noise-band math |
| `validation/variant.py` | NEW | 143 | Isolated copy lifecycle |
| `validation/gate.py` | NEW | 319 | Accept/reject orchestrator |
| `validation/archive.py` | NEW | 98 | Append-only variant archive |
| `validation/archive.jsonl` | NEW (data) | — | Runtime archive |
| `success_memory.py` | NEW | 192 | ExpeL win-signal store |
| `benchmark_harness.py` | MODIFIED | +43 | `score()` method + `--score` CLI |
| `benchmark_pack.py` | MODIFIED | +5 | `BENCHMARK_PACK_VERSION = "1.0"` |
| `HiveStateManager.py` | MODIFIED | +56 | Tagged snapshot save/restore/list |
| `HiveLessonMemory.py` | MODIFIED | +43 | ExpeL upvote/downvote/edit ops |
| `main.py` | MODIFIED | +22 | Gate hook in apply_patch route |
| `hive_lessons.jsonl` | MODIFIED (data) | +1 | Gate-sourced lesson from demo |

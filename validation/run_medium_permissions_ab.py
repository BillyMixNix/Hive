"""Temporary medium-difficulty live A/B experiment. This branch is not intended to merge."""

from __future__ import annotations

import ast
import copy
import importlib.util
import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import requests

import coder_validation
from benchmark_harness import ReliabilityBenchmarkHarness


REPO_ROOT = Path(__file__).resolve().parents[1]
TARGET_FILE = "permissions_target.py"
TARGET_SYMBOL = "compile_permissions"
MODEL = "qwen2.5-coder:7b"
LESSON_MARKER = "STRING_PERMISSION_GUARDRAIL"

TASK_NOTE = """Repair compile_permissions so it compiles user permission records correctly.

Requirements:
- records must be a list; otherwise raise TypeError.
- ignore entries that are not dictionaries or whose normalized user name is empty.
- normalize user names by stripping surrounding whitespace and converting to lowercase.
- permissions may be a single string, a list, or a tuple. Treat a string as one permission, not as characters.
- normalize permission names by converting values to strings, stripping whitespace, and lowercasing.
- ignore empty normalized permissions.
- combine duplicate users while preserving the order in which users first appear.
- deduplicate permissions per user while preserving each permission's first-seen order.
- do not mutate records or any nested permission lists.
- keep the implementation inside compile_permissions and do not modify sentinel.
"""

CASE = {
    "name": "medium_stable_permission_compiler",
    "band": "behavioral_collection_normalization",
    "task_id": "medium-permissions-1",
    "task_note": TASK_NOTE,
    "target_file": TARGET_FILE,
    "target_symbol": TARGET_SYMBOL,
    "change_intent": "modify_existing_logic",
    "expected_operation": "modify_logic",
    "completion_cues": [],
    "task_type": "bugfix",
    "expected_final_status": "proposed",
    "expected_failure_code": None,
    "risks": [
        "A string permission can be split into individual characters.",
        "Using sets or sorting can destroy first-seen order.",
        "Normalizing values in place can mutate caller-owned records.",
    ],
    "next_action": "Rewrite only compile_permissions and satisfy the executable behavior contract.",
}


def _live_ask_factory(prompts: list[str], responses: list[str]):
    def ask_live(prompt, *args, **kwargs):
        prompts.append(prompt)
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0,
                    "seed": 29,
                    "num_ctx": 8192,
                    "num_predict": 900,
                },
            },
            timeout=360,
        )
        response.raise_for_status()
        text = response.json()["response"]
        responses.append(text)
        return text

    return ask_live


def _seed_guardrail(lesson_memory):
    lesson_memory.add_lesson(
        file=TARGET_FILE,
        change_type="bugfix",
        failure_reason=(
            "A previous normalization patch iterated over a string as characters, used unordered sets, "
            "and lost stable first-seen ordering while deduplicating permissions."
        ),
        retry_instruction=(
            f"{LESSON_MARKER}: branch on isinstance(value, str) before handling list or tuple; "
            "normalize before deduplicating; keep an ordered output list plus a per-user seen set; "
            "never modify the input records or nested permission containers."
        ),
        failure_pattern="string treated as iterable and stable deduplication order lost",
        source="pilot",
        severity="high",
        lesson_level="generalized",
        lesson_family="pilot_guardrail",
        target_symbol=TARGET_SYMBOL,
        trigger_pattern="stable normalization and deduplication of scalar-or-sequence values",
        fix_strategy="string_special_case_then_ordered_seen_set",
        context_requirements={"change_type": "bugfix"},
        times_used=4,
        success_after_use=4,
        failure_after_use=0,
        promotion_state="trusted",
        scope="domain",
    )


def _top_level_contract(source: str) -> dict[str, str]:
    tree = ast.parse(source)
    contract = {}
    for node in tree.body:
        name = getattr(node, "name", None)
        if name == TARGET_SYMBOL:
            continue
        key = f"{type(node).__name__}:{name or ast.dump(node, include_attributes=False)[:80]}"
        contract[key] = ast.dump(node, include_attributes=False)
    return contract


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location("medium_permissions_candidate", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _behavior_checks(original_source: str, patched_path: Path) -> dict:
    checks: dict[str, bool] = {}
    errors: dict[str, object] = {}

    try:
        patched_source = patched_path.read_text(encoding="utf-8")
        checks["scope_only_target_changed"] = _top_level_contract(original_source) == _top_level_contract(patched_source)
    except Exception as exc:
        checks["scope_only_target_changed"] = False
        errors["scope_only_target_changed"] = str(exc)

    try:
        module = _load_module(patched_path)
        compile_permissions = module.compile_permissions
    except Exception as exc:
        for name in (
            "type_validation",
            "normalization",
            "string_is_single_permission",
            "stable_user_order",
            "stable_permission_dedupe",
            "invalid_entries_ignored",
            "empty_permissions_ignored",
            "inputs_unchanged",
        ):
            checks[name] = False
            errors[name] = f"import failed: {exc}"
        return {"checks": checks, "errors": errors, "score": sum(checks.values()), "total": len(checks), "passed": False}

    invalid_inputs = [None, {}, (), "records"]
    type_results = []
    for value in invalid_inputs:
        try:
            compile_permissions(value)
        except TypeError:
            type_results.append(True)
        except Exception as exc:
            type_results.append(False)
            errors.setdefault("type_validation", []).append(type(exc).__name__)
        else:
            type_results.append(False)
    checks["type_validation"] = all(type_results)

    records = [
        {"user": " Alice ", "permissions": [" Read ", "WRITE", "read", ""]},
        {"user": "BOB", "permissions": " Admin "},
        {"user": "alice", "permissions": ("delete", " write ", 7)},
        None,
        {"permissions": ["ignored"]},
        {"user": "   ", "permissions": ["ignored"]},
        {"user": "Carol", "permissions": None},
        {"user": "bob", "permissions": ["audit", "ADMIN"]},
    ]
    before = copy.deepcopy(records)

    try:
        result = compile_permissions(records)
        checks["normalization"] = (
            list(result) == ["alice", "bob", "carol"]
            and result.get("alice") == ["read", "write", "delete", "7"]
            and result.get("bob") == ["admin", "audit"]
            and result.get("carol") == []
        )
        checks["string_is_single_permission"] = result.get("bob", [None])[0] == "admin"
        checks["stable_user_order"] = list(result) == ["alice", "bob", "carol"]
        checks["stable_permission_dedupe"] = (
            result.get("alice") == ["read", "write", "delete", "7"]
            and result.get("bob") == ["admin", "audit"]
        )
        checks["invalid_entries_ignored"] = "" not in result and len(result) == 3
        checks["empty_permissions_ignored"] = "" not in result.get("alice", []) and result.get("carol") == []
        checks["inputs_unchanged"] = records == before
    except Exception as exc:
        errors["behavior_execution"] = f"{type(exc).__name__}: {exc}"
        for name in (
            "normalization",
            "string_is_single_permission",
            "stable_user_order",
            "stable_permission_dedupe",
            "invalid_entries_ignored",
            "empty_permissions_ignored",
            "inputs_unchanged",
        ):
            checks.setdefault(name, False)

    score = sum(bool(value) for value in checks.values())
    return {
        "checks": checks,
        "errors": errors,
        "score": score,
        "total": len(checks),
        "passed": score == len(checks),
    }


def _run_arm(*, lessons_enabled: bool, repeat_index: int) -> dict:
    harness = ReliabilityBenchmarkHarness(repo_root=REPO_ROOT)
    session = harness._create_session(lessons_enabled=lessons_enabled)
    prompts: list[str] = []
    responses: list[str] = []
    original_source = (REPO_ROOT / TARGET_FILE).read_text(encoding="utf-8")

    try:
        if lessons_enabled:
            _seed_guardrail(session["coder"].lesson_memory)

        case = dict(CASE)
        case["task_id"] = f"medium-permissions-{repeat_index}-{'on' if lessons_enabled else 'off'}"
        parent_task = harness._make_parent_task(session["state"], case)
        plan = harness._make_plan(case)
        coder_task, effective_plan = harness._build_coder_task(parent_task, plan)

        reflection_response = json.dumps({
            "reflection": "The patch is confined to compile_permissions and is ready for executable evaluation.",
            "confidence": 0.93,
            "next_step": "Run hidden behavior checks.",
            "verdict": "accept",
        })

        ask_live = _live_ask_factory(prompts, responses)
        with patch("coder.ask_hive", side_effect=ask_live) as coder_mock:
            with patch("reflector.ask_hive", return_value=reflection_response):
                with patch.object(
                    session["coder"].executor,
                    "test_patch_in_sandbox",
                    side_effect=lambda patch_text, target_file, patch_reason="": harness._workspace_sandbox_test(
                        session,
                        patch_text,
                        target_file,
                        patch_reason=patch_reason,
                    ),
                ):
                    result = session["coder"].generate_patch_with_revisions(
                        coder_task,
                        effective_plan,
                        session["reflector"],
                        max_revisions=0,
                    )

        behavior = {
            "checks": {},
            "errors": {"generation": result.get("llm_error")},
            "score": 0,
            "total": 9,
            "passed": False,
        }
        patched_source = None
        if result.get("status") == "proposed" and result.get("patch"):
            with tempfile.TemporaryDirectory(prefix="hive-medium-ab-") as temp_dir:
                patched_path = Path(temp_dir) / TARGET_FILE
                shutil.copy2(REPO_ROOT / TARGET_FILE, patched_path)
                try:
                    session["coder"].executor.apply_patch(
                        result["patch"],
                        str(patched_path),
                        patch_reason=result.get("reason", "medium A/B candidate"),
                    )
                    patched_source = patched_path.read_text(encoding="utf-8")
                    behavior = _behavior_checks(original_source, patched_path)
                except Exception as exc:
                    behavior["errors"]["apply"] = f"{type(exc).__name__}: {exc}"

        return {
            "lessons_enabled": lessons_enabled,
            "repeat_index": repeat_index,
            "model": MODEL,
            "final_status": result.get("status"),
            "generation_calls": coder_mock.call_count,
            "retry_count": max(0, coder_mock.call_count - 1),
            "guardrail_seen_in_prompt": any(LESSON_MARKER in prompt for prompt in prompts),
            "behavior": behavior,
            "patch": result.get("patch"),
            "patched_source": patched_source,
            "raw_responses": responses,
            "reason": result.get("reason"),
            "failure_code": result.get("failure_code"),
            "llm_error": result.get("llm_error"),
        }
    finally:
        harness._cleanup_session(session)


def main():
    coder_validation.KNOWN_FILES.add(TARGET_FILE)
    repeats = []
    for repeat_index in range(2):
        order = [True, False] if repeat_index == 0 else [False, True]
        arms = [_run_arm(lessons_enabled=enabled, repeat_index=repeat_index) for enabled in order]
        by_condition = {"with_lessons" if arm["lessons_enabled"] else "without_lessons": arm for arm in arms}
        repeats.append({
            "repeat_index": repeat_index,
            "arm_order": ["with_lessons" if value else "without_lessons" for value in order],
            **by_condition,
        })

    with_scores = [item["with_lessons"]["behavior"]["score"] for item in repeats]
    without_scores = [item["without_lessons"]["behavior"]["score"] for item in repeats]
    with_passes = sum(item["with_lessons"]["behavior"]["passed"] for item in repeats)
    without_passes = sum(item["without_lessons"]["behavior"]["passed"] for item in repeats)
    paired_deltas = [a - b for a, b in zip(with_scores, without_scores)]

    if all(delta > 0 for delta in paired_deltas):
        verdict = "lessons_improve_behavior_score"
    elif with_passes > without_passes:
        verdict = "lessons_improve_full_pass_rate"
    elif any(delta != 0 for delta in paired_deltas):
        verdict = "mixed_result"
    else:
        verdict = "no_measured_difference"

    report = {
        "experiment": "medium_stable_permission_compiler",
        "model": MODEL,
        "repeats": repeats,
        "summary": {
            "with_lesson_scores": with_scores,
            "without_lesson_scores": without_scores,
            "paired_score_deltas": paired_deltas,
            "with_lesson_full_passes": with_passes,
            "without_lesson_full_passes": without_passes,
            "verdict": verdict,
        },
    }

    output_path = REPO_ROOT / "validation" / "results" / "live_ab_medium_permissions.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()

"""Temporary hard live A/B experiment. This branch is not intended to merge."""

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

from benchmark_harness import ReliabilityBenchmarkHarness


REPO_ROOT = Path(__file__).resolve().parents[1]
TARGET_FILE = "validation/fixtures/config_merge_target.py"
TARGET_SYMBOL = "merge_settings"
MODEL = "qwen2.5-coder:7b"
LESSON_MARKER = "COPY_ON_WRITE_GUARDRAIL"

TASK_NOTE = """Repair merge_settings so it behaves as a safe recursive configuration merge.

Requirements:
- defaults and overrides must both be dictionaries; otherwise raise TypeError.
- recursively merge nested dictionaries while preserving nested default keys that are not overridden.
- when values conflict and are not both dictionaries, the override replaces the default.
- do not mutate defaults or overrides at any depth.
- the returned object must not share mutable dictionaries, lists, or sets with either input.
- keep the entire implementation inside merge_settings; do not add helper functions or top-level imports.
- do not modify sentinel or any other top-level symbol.
"""

CASE = {
    "name": "hard_recursive_copy_on_write_merge",
    "band": "behavioral_recursive_merge",
    "task_id": "hard-merge-1",
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
        "A shallow copy can still mutate caller-owned nested values.",
        "Replacing nested mappings wholesale can discard untouched defaults.",
        "A broad rewrite can alter neighboring symbols.",
    ],
    "next_action": "Rewrite only merge_settings and satisfy the executable behavior contract.",
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
                    "seed": 17,
                    "num_ctx": 8192,
                    "num_predict": 1024,
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
        failure_reason="A prior merge patch passed syntax checks but mutated nested caller-owned containers and discarded untouched nested defaults.",
        retry_instruction=(
            f"{LESSON_MARKER}: use a recursive copy-on-write merge. Validate both top-level inputs, "
            "deep-copy every retained or overriding mutable value, merge only when both values are dictionaries, "
            "and keep all edits inside the anchored function."
        ),
        failure_pattern="shallow merge or aliasing during nested configuration updates",
        source="pilot",
        severity="high",
        lesson_level="generalized",
        lesson_family="pilot_guardrail",
        target_symbol=TARGET_SYMBOL,
        trigger_pattern="recursive merge of nested mutable mappings",
        fix_strategy="recursive_copy_on_write_merge",
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
    spec = importlib.util.spec_from_file_location("hard_merge_candidate", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _behavior_checks(original_source: str, patched_path: Path) -> dict:
    checks = {}
    errors = {}
    try:
        patched_source = patched_path.read_text(encoding="utf-8")
        checks["scope_only_target_changed"] = _top_level_contract(original_source) == _top_level_contract(patched_source)
    except Exception as exc:
        checks["scope_only_target_changed"] = False
        errors["scope_only_target_changed"] = str(exc)

    try:
        module = _load_module(patched_path)
        merge_settings = module.merge_settings
    except Exception as exc:
        for name in (
            "type_validation",
            "recursive_merge",
            "preserves_unoverridden_keys",
            "type_conflict_replacement",
            "inputs_unchanged",
            "output_detached_from_defaults",
            "output_detached_from_overrides",
            "mutable_override_values_copied",
        ):
            checks[name] = False
            errors[name] = f"import failed: {exc}"
        return {"checks": checks, "errors": errors, "score": sum(checks.values()), "total": len(checks), "passed": False}

    invalid_inputs = [
        ([], {}),
        ({}, None),
        ("defaults", {}),
        ({}, ()),
    ]
    type_results = []
    for defaults, overrides in invalid_inputs:
        try:
            merge_settings(defaults, overrides)
        except TypeError:
            type_results.append(True)
        except Exception as exc:
            type_results.append(False)
            errors.setdefault("type_validation", []).append(type(exc).__name__)
        else:
            type_results.append(False)
    checks["type_validation"] = all(type_results)

    defaults = {
        "service": {
            "host": "localhost",
            "ports": [8000],
            "auth": {"user": "root", "scopes": {"read"}},
        },
        "features": ["base"],
        "limits": {"cpu": 2, "memory": {"mb": 512}},
        "mode": "safe",
        "untouched": {"enabled": True},
    }
    overrides = {
        "service": {
            "ports": [9000],
            "auth": {"token": "abc"},
        },
        "features": ["fast"],
        "limits": {"memory": {"mb": 1024}},
        "mode": {"name": "turbo"},
    }
    defaults_before = copy.deepcopy(defaults)
    overrides_before = copy.deepcopy(overrides)

    try:
        result = merge_settings(defaults, overrides)
        checks["recursive_merge"] = (
            result["service"]["host"] == "localhost"
            and result["service"]["ports"] == [9000]
            and result["service"]["auth"]["user"] == "root"
            and result["service"]["auth"]["token"] == "abc"
            and result["service"]["auth"]["scopes"] == {"read"}
            and result["limits"]["cpu"] == 2
            and result["limits"]["memory"]["mb"] == 1024
        )
        checks["preserves_unoverridden_keys"] = result["untouched"] == {"enabled": True}
        checks["type_conflict_replacement"] = result["mode"] == {"name": "turbo"}
        checks["inputs_unchanged"] = defaults == defaults_before and overrides == overrides_before

        result_snapshot = copy.deepcopy(result)
        defaults["service"]["ports"].append(7000)
        defaults["service"]["auth"]["scopes"].add("write")
        defaults["untouched"]["enabled"] = False
        checks["output_detached_from_defaults"] = result == result_snapshot

        overrides["service"]["ports"].append(9100)
        overrides["service"]["auth"]["token"] = "changed"
        overrides["features"].append("later")
        checks["output_detached_from_overrides"] = result == result_snapshot

        result["service"]["ports"].append(9200)
        result["service"]["auth"]["scopes"].add("admin")
        result["features"].append("candidate-only")
        checks["mutable_override_values_copied"] = (
            overrides_before["service"]["ports"] == [9000]
            and overrides_before["features"] == ["fast"]
            and defaults_before["service"]["auth"]["scopes"] == {"read"}
        )
    except Exception as exc:
        errors["behavior_execution"] = f"{type(exc).__name__}: {exc}"
        for name in (
            "recursive_merge",
            "preserves_unoverridden_keys",
            "type_conflict_replacement",
            "inputs_unchanged",
            "output_detached_from_defaults",
            "output_detached_from_overrides",
            "mutable_override_values_copied",
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
        case["task_id"] = f"hard-merge-{repeat_index}-{'on' if lessons_enabled else 'off'}"
        parent_task = harness._make_parent_task(session["state"], case)
        plan = harness._make_plan(case)
        coder_task, effective_plan = harness._build_coder_task(parent_task, plan)

        reflection_response = json.dumps({
            "reflection": "The patch is confined to merge_settings and is ready for executable evaluation.",
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
            with tempfile.TemporaryDirectory(prefix="hive-hard-ab-") as temp_dir:
                patched_path = Path(temp_dir) / "config_merge_target.py"
                shutil.copy2(REPO_ROOT / TARGET_FILE, patched_path)
                try:
                    session["coder"].executor.apply_patch(
                        result["patch"],
                        str(patched_path),
                        patch_reason=result.get("reason", "hard A/B candidate"),
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
    with_passes = [item["with_lessons"]["behavior"]["passed"] for item in repeats]
    without_passes = [item["without_lessons"]["behavior"]["passed"] for item in repeats]
    with_retries = [item["with_lessons"]["retry_count"] for item in repeats]
    without_retries = [item["without_lessons"]["retry_count"] for item in repeats]

    score_deltas = [a - b for a, b in zip(with_scores, without_scores)]
    retry_deltas = [a - b for a, b in zip(with_retries, without_retries)]
    if all(with_passes) and not all(without_passes):
        verdict = "lessons_help_behavioral_success"
    elif sum(score_deltas) > 0:
        verdict = "lessons_help_partial_behavior"
    elif sum(score_deltas) < 0:
        verdict = "lessons_hurt_behavior"
    elif sum(retry_deltas) < 0:
        verdict = "lessons_help_efficiency_only"
    else:
        verdict = "no_measured_difference"

    report = {
        "schema_version": 1,
        "experiment": "hard_recursive_merge_live_coder_lessons_on_vs_off",
        "model": MODEL,
        "temperature": 0,
        "seed": 17,
        "repeats": 2,
        "counterbalanced": True,
        "task": TASK_NOTE,
        "hidden_behavior_check_count": repeats[0]["with_lessons"]["behavior"]["total"],
        "with_lessons_scores": with_scores,
        "without_lessons_scores": without_scores,
        "paired_score_deltas": score_deltas,
        "with_lessons_full_passes": with_passes,
        "without_lessons_full_passes": without_passes,
        "with_lessons_retries": with_retries,
        "without_lessons_retries": without_retries,
        "paired_retry_deltas": retry_deltas,
        "verdict": verdict,
        "repeats_detail": repeats,
    }

    output = REPO_ROOT / "validation/results/live_ab_hard_merge.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "verdict": verdict,
        "with_lessons_scores": with_scores,
        "without_lessons_scores": without_scores,
        "paired_score_deltas": score_deltas,
        "with_lessons_full_passes": with_passes,
        "without_lessons_full_passes": without_passes,
        "with_lessons_retries": with_retries,
        "without_lessons_retries": without_retries,
        "output": str(output),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

import json
import hashlib
import platform
import shutil
import sys
import uuid
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from HiveLessonMemory import LessonMemory
from HiveStateManager import HiveStateManager
from benchmark_pack import build_reliability_benchmark_pack
from coder import CoderAgent
from coder_block_ops import should_use_block_rewrite
from coder_context import select_target_block
from coder_prompting import (
    build_block_rewrite_prompt,
    build_prompt,
    build_symbol_locked_prompt,
    prepare_block_rewrite_input,
)
from executor import ExecutorAgent
from failure_intelligence import interpret_failure
from planner import PlannerAgent
from reflector import Reflector


class ReliabilityBenchmarkHarness:
    def __init__(self, repo_root=None):
        self.repo_root = Path(repo_root or Path(__file__).resolve().parent)

    def _stable_json(self, data):
        return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    def _stable_hash(self, data):
        payload = data if isinstance(data, str) else self._stable_json(data)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _case_fingerprints(self, cases):
        return [
            {
                "name": case.get("name"),
                "band": case.get("band"),
                "fingerprint": self._stable_hash(case),
            }
            for case in cases
        ]

    def _source_tree_fingerprint(self):
        source_files = []
        for path in sorted(self.repo_root.rglob("*.py")):
            relative = path.relative_to(self.repo_root)
            parts = set(relative.parts)
            if "__pycache__" in parts or ".venv" in parts or "backups" in parts:
                continue
            if any(part.startswith("_tmp_reliability_") for part in relative.parts):
                continue

            source_files.append({
                "path": relative.as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            })

        return {
            "file_count": len(source_files),
            "fingerprint": self._stable_hash(source_files),
            "files": source_files,
        }

    def _build_reproducibility_manifest(self, cases):
        case_fingerprints = self._case_fingerprints(cases)
        source_tree = self._source_tree_fingerprint()
        return {
            "goal": "v0.6-reproducibility",
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "repo_root": str(self.repo_root),
            "case_count": len(cases),
            "case_order": [case.get("name") for case in cases],
            "case_order_hash": self._stable_hash([case.get("name") for case in cases]),
            "case_pack_hash": self._stable_hash(case_fingerprints),
            "case_fingerprints": case_fingerprints,
            "source_file_count": source_tree["file_count"],
            "source_tree_fingerprint": source_tree["fingerprint"],
        }

    def _report_signature(self, report):
        return self._stable_hash({
            "summary": report.get("summary"),
            "records": report.get("records"),
        })

    def _create_session(self, lessons_enabled=True):
        temp_root = self.repo_root / "tests" / f"_tmp_reliability_{uuid.uuid4().hex}"
        temp_root.mkdir(parents=True, exist_ok=False)
        state = HiveStateManager(
            snapshot_path=temp_root / "snapshot.json",
            repo_root=self.repo_root,
        )
        state.rebuild_repo_map()

        planner = PlannerAgent(state_manager=state)
        reflector = Reflector()
        coder = CoderAgent(
            state_manager=state,
            executor=ExecutorAgent(backup_dir=temp_root / "backups"),
        )
        lesson_path = str(temp_root / "lessons.jsonl") if lessons_enabled else None
        coder.lesson_memory = LessonMemory(path=lesson_path or str(temp_root / "lessons_disabled.jsonl"), max_entries=200)
        coder._lessons_enabled = lessons_enabled
        return {
            "temp_root": temp_root,
            "state": state,
            "planner": planner,
            "reflector": reflector,
            "coder": coder,
        }

    def _cleanup_session(self, session):
        shutil.rmtree(session["temp_root"], ignore_errors=True)

    def _make_plan(self, case):
        return {
            "goal": case["task_note"],
            "task_type": case.get("task_type", "bugfix"),
            "tasks": [
                {
                    "title": case.get("title", case["task_note"]),
                    "description": case["task_note"],
                    "target_file": case["target_file"],
                    "target_symbol": case["target_symbol"],
                    "change_intent": case.get("change_intent", "modify_existing_logic"),
                    "expected_operation": case.get("expected_operation", "modify_logic"),
                    "completion_cues": list(case.get("completion_cues") or []),
                    "task_type": case.get("task_type", "bugfix"),
                    "task_id": case.get("child_task_id", f"{case['task_id']}-child"),
                }
            ],
            "dependencies": [case["target_file"]],
            "risks": list(case.get("risks") or []),
            "next_action": case.get("next_action", f"Patch {case['target_symbol']} in {case['target_file']}."),
            "status": "planned",
        }

    def _workspace_sandbox_test(self, session, patch_text, target_file, patch_reason=""):
        report = {
            "patch_id": None,
            "target_file": target_file,
            "sandbox_file": None,
            "applied": False,
            "syntax_valid": False,
            "semantic_valid": False,
            "errors": [],
            "notes": "",
        }

        sandbox_dir = session["temp_root"] / f"sandbox_{uuid.uuid4().hex}"
        sandbox_dir.mkdir(parents=True, exist_ok=False)
        sandbox_file = sandbox_dir / Path(target_file).name
        report["sandbox_file"] = str(sandbox_file)

        try:
            shutil.copy2(self.repo_root / target_file, sandbox_file)
            session["coder"].executor.apply_patch(
                patch_text,
                str(sandbox_file),
                patch_reason=patch_reason,
            )
            report["applied"] = True

            sandbox_file_text = sandbox_file.read_text(encoding="utf-8")
            syntax_check = session["coder"].executor._validate_python_syntax(sandbox_file_text)
            report["syntax_valid"] = syntax_check["valid"]
            if not syntax_check["valid"]:
                report["errors"].append(
                    f"Syntax error: {session['coder'].executor._format_syntax_error(syntax_check['error'])}"
                )

            semantic_check = session["coder"].executor.validate_patch_semantics(
                patch_text,
                target_file=str(sandbox_file),
                file_text=sandbox_file_text,
                patch_reason=patch_reason,
            )
            report["semantic_valid"] = semantic_check["valid"]
            if not semantic_check["valid"]:
                report["errors"].append(f"Semantic issues: {semantic_check['checks']}")
                report["notes"] = "Patch failed semantic safety checks in workspace sandbox."
        except Exception as exc:
            report["errors"].append(f"Patch apply failed: {exc}")
            report["notes"] = "Patch could not be applied in workspace sandbox."

        if report["applied"] and report["syntax_valid"] and report["semantic_valid"]:
            report["notes"] = "Patch passed workspace sandbox testing successfully."

        return report

    def _make_parent_task(self, state, case):
        span = state.get_symbol_span(case["target_file"], case["target_symbol"])
        anchor = {
            "target_file": case["target_file"],
            "target_symbol": case["target_symbol"],
            "target_symbol_id": span.get("symbol_id") if span else None,
            "lineno": span.get("lineno") if span else None,
            "end_lineno": span.get("end_lineno") if span else None,
            "col_offset": span.get("col_offset") if span else None,
            "end_col_offset": span.get("end_col_offset") if span else None,
            "scope": "single_file",
            "anchor_level": "symbol",
            "anchor_source": "benchmark",
        }
        return {
            "id": case["task_id"],
            "tag": "task",
            "status": "active",
            "note": case["task_note"],
            "target_file": case["target_file"],
            "target_symbol": case["target_symbol"],
            "metadata": {
                "target_file": case["target_file"],
                "target_symbol": case["target_symbol"],
                "target_symbol_id": span.get("symbol_id") if span else None,
                "change_intent": case.get("change_intent"),
                "expected_operation": case.get("expected_operation"),
                "completion_cues": list(case.get("completion_cues") or []),
                "anchor": anchor,
                "benchmark_case_id": case["name"],
                "benchmark_band": case["band"],
            },
        }

    def _build_coder_task(self, parent_task, plan):
        child = dict(plan["tasks"][0])
        child["status"] = "current"
        anchor = dict((parent_task.get("metadata") or {}).get("anchor") or {})
        anchor["target_file"] = child.get("target_file") or anchor.get("target_file")
        anchor["target_symbol"] = child.get("target_symbol") or anchor.get("target_symbol")

        coder_task = {
            "id": parent_task["id"],
            "tag": parent_task.get("tag", "task"),
            "status": parent_task.get("status", "active"),
            "note": child.get("description", parent_task.get("note", "")),
            "metadata": {
                **(parent_task.get("metadata") or {}),
                "target_file": child.get("target_file"),
                "target_symbol": child.get("target_symbol"),
                "change_intent": child.get("change_intent"),
                "expected_operation": child.get("expected_operation"),
                "completion_cues": child.get("completion_cues"),
                "task_type": child.get("task_type"),
                "child_task_id": child.get("task_id"),
                "parent_task_id": parent_task["id"],
                "anchor": anchor,
            },
            "target_file": child.get("target_file"),
            "target_symbol": child.get("target_symbol"),
            "change_intent": child.get("change_intent"),
            "expected_operation": child.get("expected_operation"),
            "completion_cues": child.get("completion_cues"),
            "task_type": child.get("task_type"),
            "child_task_id": child.get("task_id"),
            "parent_task_id": parent_task["id"],
        }

        effective_plan = {
            **plan,
            "tasks": [child],
            "active_child_task_id": child.get("task_id"),
            "active_child_task_title": child.get("title"),
            "active_child_target_file": child.get("target_file"),
        }
        return coder_task, effective_plan

    def _preview_generation(self, coder, task, plan):
        target_file = coder._select_target_file(
            plan,
            target_file=task.get("target_file"),
            task=task,
        )
        full_file_text = coder._get_current_file_text(target_file)
        context = coder._select_context_for_intent(
            task,
            plan,
            target_file,
            full_file_text,
            revision=True,
        )
        prompt_kind = "symbol_locked" if coder._should_use_symbol_locked_prompt(task, context) else "revision"
        context = coder._apply_prompt_budget(
            task,
            plan,
            target_file,
            context,
            full_file_text,
            prompt_kind=prompt_kind,
        )
        prompt_text = context.get("prompt_context_text") or context.get("context_text") or full_file_text
        prompt = None
        if should_use_block_rewrite(task, plan, target_file) and context.get("selected_block") is not None:
            file_summary = coder.state_manager.get_file_summary(target_file) if coder.state_manager is not None else None
            block_prompt_text, _ = prepare_block_rewrite_input(
                target_file=target_file,
                block=context["selected_block"],
                file_summary=file_summary,
            )
            prompt_block = dict(context["selected_block"])
            prompt_block["text"] = block_prompt_text
            prompt = build_block_rewrite_prompt(task, plan, target_file, prompt_block)
        elif coder._should_use_symbol_locked_prompt(task, context):
            prompt = build_symbol_locked_prompt(task, target_file, prompt_text)
        else:
            prompt = build_prompt(task, plan, target_file, prompt_text)

        return {
            "target_file": target_file,
            "context_mode": context.get("mode"),
            "prompt_length": len(prompt or ""),
            "context_budget": dict(context.get("context_budget") or {}),
        }

    def _build_learning_case(
        self,
        *,
        name,
        task_id,
        task_note,
        target_file,
        target_symbol,
        completion_cues,
        bad_response,
        good_response,
        change_intent="modify_existing_logic",
        expected_operation="modify_logic",
        task_type="bugfix",
        band="lesson_learning",
    ):
        return {
            "name": name,
            "band": band,
            "task_id": task_id,
            "task_note": task_note,
            "target_file": target_file,
            "target_symbol": target_symbol,
            "change_intent": change_intent,
            "expected_operation": expected_operation,
            "completion_cues": list(completion_cues or []),
            "task_type": task_type,
            "plan_response": self._make_plan(
                {
                    "task_note": task_note,
                    "target_file": target_file,
                    "target_symbol": target_symbol,
                    "change_intent": change_intent,
                    "expected_operation": expected_operation,
                    "completion_cues": completion_cues,
                    "task_type": task_type,
                    "task_id": task_id,
                }
            ),
            "coder_side_effect": [bad_response, good_response],
        }

    def _run_learning_case(self, session, case):
        state = session["state"]
        planner = session["planner"]
        coder = session["coder"]
        reflector = session["reflector"]

        parent_task = self._make_parent_task(state, case)
        planner_response = json.dumps(case["plan_response"])
        reflection_response = json.dumps({
            "reflection": "Patch stays within the requested symbol and is safe to review.",
            "confidence": 0.92,
            "next_step": "Approve patch.",
            "verdict": "accept",
        })

        with patch("planner.ask_hive", return_value=planner_response):
            plan = planner.plan_task(parent_task)

        coder_task, effective_plan = self._build_coder_task(parent_task, plan)
        preview = self._preview_generation(coder, coder_task, effective_plan)

        with patch("coder.ask_hive", side_effect=list(case["coder_side_effect"])) as coder_mock:
            with patch("reflector.ask_hive", return_value=reflection_response):
                with patch.object(
                    coder.executor,
                    "test_patch_in_sandbox",
                    side_effect=lambda patch_text, target_file, patch_reason="": self._workspace_sandbox_test(
                        session,
                        patch_text,
                        target_file,
                        patch_reason=patch_reason,
                    ),
                ):
                    result = coder.generate_patch_with_revisions(coder_task, effective_plan, reflector)

        recent_lessons = coder.lesson_memory.get_recent_lessons(limit=10)
        return {
            "name": case["name"],
            "result": result,
            "coder_calls": coder_mock.call_count,
            "selected_context_mode": preview["context_mode"],
            "prompt_length": preview["prompt_length"],
            "recent_lessons": recent_lessons,
            "coder_task": coder_task,
            "effective_plan": effective_plan,
        }

    def run_lesson_learning_benchmark(self):
        session = self._create_session()
        try:
            missing_diff_headers_response = (
                "TARGET_FILE: {target_file}\n"
                "CHANGE_TYPE: diff_patch\n"
                "RISK_LEVEL: low\n"
                "STATUS: proposed\n"
                "REASON: Attempt malformed diff.\n"
                "PATCH:\n"
                "@@ -1,0 +1,1 @@\n"
                "+        return revised_value\n"
            )

            interface_good_response = (
                "TARGET_FILE: interface.py\n"
                "CHANGE_TYPE: diff_patch\n"
                "RISK_LEVEL: low\n"
                "STATUS: proposed\n"
                "REASON: Copy the optional context mapping before storing it in the response.\n"
                "PATCH:\n"
                "--- interface.py\n"
                "+++ interface.py\n"
                "@@ -44,7 +44,7 @@ class Interface:\n"
                "     def _build_response(self, intent, text, context=None):\n"
                "         return {\n"
                "             \"intent\": intent,\n"
                "-            \"context\": context or {},\n"
                "+            \"context\": dict(context or {}),\n"
                "             \"raw_text\": text,\n"
                "         }\n"
            )
            router_good_response = (
                "TARGET_FILE: router.py\n"
                "CHANGE_TYPE: diff_patch\n"
                "RISK_LEVEL: low\n"
                "STATUS: proposed\n"
                "REASON: Guard normalize_command against missing command values.\n"
                "PATCH:\n"
                "--- router.py\n"
                "+++ router.py\n"
                "@@ -32,5 +32,5 @@ class Router:\n"
                "     def normalize_command(self, command):\n"
                "-        return command.lower().strip()\n"
                "+        return str(command or \"\").lower().strip()\n"
            )
            doc_good_response = (
                "TARGET_FILE: coder_context.py\n"
                "CHANGE_TYPE: diff_patch\n"
                "RISK_LEVEL: low\n"
                "STATUS: proposed\n"
                "REASON: Add a narrow explanatory comment inside select_edit_context.\n"
                "PATCH:\n"
                "--- coder_context.py\n"
                "+++ coder_context.py\n"
                "@@ -971,6 +971,7 @@ def select_edit_context(task, plan, target_file, file_text, radius=0, padding_lines=40):\n"
                "         if anchor_span:\n"
                "+            # Enforce span-locked selection before building exact-symbol context.\n"
                "             selected_block = _find_block_by_anchor_span(all_blocks, anchor_span)\n"
                "             _validate_block_against_anchor_span(\n"
            )

            seed_case_one = self._build_learning_case(
                name="lesson_seed_one",
                task_id="lesson-seed-1",
                task_note="Update _build_response to copy the provided context mapping before returning it.",
                target_file="interface.py",
                target_symbol="_build_response",
                completion_cues=['"context": dict(context or {}),'],
                bad_response=missing_diff_headers_response.format(target_file="interface.py"),
                good_response=interface_good_response,
            )
            seed_case_two = self._build_learning_case(
                name="lesson_seed_two",
                task_id="lesson-seed-2",
                task_note="Update _build_response to copy the provided context mapping before returning it.",
                target_file="interface.py",
                target_symbol="_build_response",
                completion_cues=['"context": dict(context or {}),'],
                bad_response=missing_diff_headers_response.format(target_file="interface.py"),
                good_response=interface_good_response,
            )
            generalized_reuse_case = self._build_learning_case(
                name="lesson_generalized_reuse",
                task_id="lesson-reuse-1",
                task_note="Update normalize_command to handle missing command values safely before lowercasing.",
                target_file="router.py",
                target_symbol="normalize_command",
                completion_cues=['return str(command or "").lower().strip()'],
                bad_response=missing_diff_headers_response.format(target_file="router.py"),
                good_response=router_good_response,
            )
            unsafe_context_case = self._build_learning_case(
                name="lesson_unsafe_context",
                task_id="lesson-unsafe-1",
                task_note="Insert a comment above the anchor_span lookup in select_edit_context to explain the strict span lock.",
                target_file="coder_context.py",
                target_symbol="select_edit_context",
                completion_cues=["# Enforce span-locked selection before building exact-symbol context."],
                bad_response=missing_diff_headers_response.format(target_file="coder_context.py"),
                good_response=doc_good_response,
                expected_operation="insert_comment",
                task_type="docs",
            )

            first_seed = self._run_learning_case(session, seed_case_one)
            second_seed = self._run_learning_case(session, seed_case_two)

            lesson_memory = session["coder"].lesson_memory
            exact_lessons = lesson_memory.find_relevant_lessons(
                file="interface.py",
                change_type="diff_patch",
                failure_code="missing_diff_headers",
                target_symbol="_build_response",
                context_mode=first_seed["selected_context_mode"],
                limit=10,
            )
            promoted_generalized = None
            for lesson in lesson_memory.get_recent_lessons(limit=20):
                if lesson.get("lesson_level") == "generalized" and lesson.get("failure_code") == "missing_diff_headers":
                    promoted_generalized = lesson
                    break

            compatible_lookup = lesson_memory.get_retry_lessons(
                file=generalized_reuse_case["target_file"],
                change_type="diff_patch",
                failure_code="missing_diff_headers",
                target_symbol=generalized_reuse_case["target_symbol"],
                context_mode="exact_symbol_block",
                trigger_pattern=promoted_generalized.get("trigger_pattern") if promoted_generalized else None,
                fix_strategy=promoted_generalized.get("fix_strategy") if promoted_generalized else None,
                current_context={
                    "file": generalized_reuse_case["target_file"],
                    "target_symbol": generalized_reuse_case["target_symbol"],
                    "context_mode": "exact_symbol_block",
                    "change_intent": generalized_reuse_case["change_intent"],
                    "expected_operation": generalized_reuse_case["expected_operation"],
                    "failure_code": "missing_diff_headers",
                    "trigger_pattern": promoted_generalized.get("trigger_pattern") if promoted_generalized else None,
                    "fix_strategy": promoted_generalized.get("fix_strategy") if promoted_generalized else None,
                },
                limit=10,
            )
            compatible_generalized_matches = [
                lesson for lesson in compatible_lookup
                if lesson.get("lesson_level") == "generalized"
            ]
            compatible_lesson_package = session["coder"]._compose_retry_lesson_text(
                "Patch is missing diff file headers.",
                compatible_lookup,
            )
            generalized_reuse = self._run_learning_case(session, generalized_reuse_case)

            unsafe_lookup = lesson_memory.get_retry_lessons(
                file=unsafe_context_case["target_file"],
                change_type="diff_patch",
                failure_code="missing_diff_headers",
                target_symbol=unsafe_context_case["target_symbol"],
                context_mode="exact_symbol_block",
                trigger_pattern=promoted_generalized.get("trigger_pattern") if promoted_generalized else None,
                fix_strategy=promoted_generalized.get("fix_strategy") if promoted_generalized else None,
                current_context={
                    "file": unsafe_context_case["target_file"],
                    "target_symbol": unsafe_context_case["target_symbol"],
                    "context_mode": "exact_symbol_block",
                    "change_intent": unsafe_context_case["change_intent"],
                    "expected_operation": unsafe_context_case["expected_operation"],
                    "failure_code": "missing_diff_headers",
                    "trigger_pattern": promoted_generalized.get("trigger_pattern") if promoted_generalized else None,
                    "fix_strategy": promoted_generalized.get("fix_strategy") if promoted_generalized else None,
                },
                limit=10,
            )
            unsafe_case_result = self._run_learning_case(session, unsafe_context_case)

            unsafe_generalized_matches = [
                lesson for lesson in unsafe_lookup
                if lesson.get("lesson_level") == "generalized"
            ]
            generalized_match_reasons = list(
                (compatible_generalized_matches[0].get("_match_reasons") or [])
            ) if compatible_generalized_matches else []

            summary = {
                "seed_exact_lesson_recorded": bool(exact_lessons),
                "seed_exact_lesson_successes": max(
                    (int(lesson.get("success_after_use", 0) or 0) for lesson in exact_lessons),
                    default=0,
                ),
                "generalized_lesson_created": promoted_generalized is not None,
                "generalized_lesson_id": promoted_generalized.get("lesson_id") if promoted_generalized else None,
                "compatible_generalized_matches": len(compatible_generalized_matches),
                "compatible_generalized_available": len(compatible_generalized_matches) > 0,
                "compatible_guidance_changed": bool(compatible_lesson_package["guidance_changed"]),
                "generalized_match_reasons": generalized_match_reasons,
                "unsafe_generalized_matches": len(unsafe_generalized_matches),
                "unsafe_generalized_skipped": len(unsafe_generalized_matches) == 0,
                "all_checks_passed": all([
                    bool(exact_lessons),
                    max((int(lesson.get("success_after_use", 0) or 0) for lesson in exact_lessons), default=0) >= 2,
                    promoted_generalized is not None,
                    len(compatible_generalized_matches) > 0,
                    bool(compatible_lesson_package["guidance_changed"]),
                    "trigger_pattern" in generalized_match_reasons if generalized_match_reasons else False,
                    "generalized" in generalized_match_reasons if generalized_match_reasons else False,
                    len(unsafe_generalized_matches) == 0,
                    unsafe_case_result["result"].get("status") == "proposed",
                ]),
            }

            return {
                "summary": summary,
                "records": [
                    {
                        "name": first_seed["name"],
                        "final_status": first_seed["result"].get("status"),
                        "coder_calls": first_seed["coder_calls"],
                    },
                    {
                        "name": second_seed["name"],
                        "final_status": second_seed["result"].get("status"),
                        "coder_calls": second_seed["coder_calls"],
                    },
                    {
                        "name": generalized_reuse["name"],
                        "final_status": generalized_reuse["result"].get("status"),
                        "coder_calls": generalized_reuse["coder_calls"],
                    },
                    {
                        "name": unsafe_case_result["name"],
                        "final_status": unsafe_case_result["result"].get("status"),
                        "coder_calls": unsafe_case_result["coder_calls"],
                    },
                ],
            }
        finally:
            self._cleanup_session(session)

    def run_case(self, case, lessons_enabled=True):
        session = self._create_session(lessons_enabled=lessons_enabled)
        try:
            state = session["state"]
            planner = session["planner"]
            coder = session["coder"]
            reflector = session["reflector"]

            parent_task = self._make_parent_task(state, case)
            planner_response = case.get("planner_raw_response")
            if planner_response is None:
                planner_response = json.dumps(case["plan_response"])
            reflection_response = json.dumps({
                "reflection": "Patch stays within the requested symbol and is safe to review.",
                "confidence": 0.92,
                "next_step": "Approve patch.",
                "verdict": "accept",
            })

            with patch("planner.ask_hive", return_value=planner_response) as planner_mock:
                plan = planner.plan_task(parent_task)

            coder_task, effective_plan = self._build_coder_task(parent_task, plan)
            preview = self._preview_generation(coder, coder_task, effective_plan)

            coder_side_effect = case.get("coder_side_effect")
            if coder_side_effect is None:
                coder_patch = patch("coder.ask_hive", return_value=case["coder_response"])
            else:
                coder_patch = patch("coder.ask_hive", side_effect=list(coder_side_effect))

            with coder_patch as coder_mock:
                with patch("reflector.ask_hive", return_value=reflection_response):
                    with patch.object(
                        coder.executor,
                        "test_patch_in_sandbox",
                        side_effect=lambda patch_text, target_file, patch_reason="": self._workspace_sandbox_test(
                            session,
                            patch_text,
                            target_file,
                            patch_reason=patch_reason,
                        ),
                    ):
                        result = coder.generate_patch_with_revisions(coder_task, effective_plan, reflector)

            final_status = result.get("status")
            failure_code = None
            if final_status != "proposed":
                interpretation = interpret_failure(
                    stage=case.get("failure_stage", "benchmark"),
                    error_text=result.get("llm_error"),
                    task=coder_task,
                    patch_data=result,
                    metadata={
                        "planner_source": effective_plan.get("source"),
                        "benchmark_case_id": case["name"],
                    },
                )
                failure_code = interpretation.classification.failure_code

            sandbox = result.get("sandbox_report") or {}
            expected_final_status = case.get("expected_final_status", "proposed")
            expected_failure_code = case.get("expected_failure_code")
            expected_to_succeed = expected_final_status == "proposed"
            passed = final_status == case.get("expected_final_status", "proposed")
            if expected_failure_code is not None:
                passed = passed and failure_code == expected_failure_code

            return {
                "name": case["name"],
                "band": case["band"],
                "task_note": case["task_note"],
                "target_file": case["target_file"],
                "target_symbol": case["target_symbol"],
                "change_intent": case.get("change_intent"),
                "expected_operation": case.get("expected_operation"),
                "completion_cues": list(case.get("completion_cues") or []),
                "expected_failure_sensitivities": list(case.get("expected_failure_sensitivities") or []),
                "selected_context_mode": preview["context_mode"],
                "prompt_length": preview["prompt_length"],
                "context_budget": preview["context_budget"],
                "planner_source": effective_plan.get("source"),
                "planner_success": effective_plan.get("status") == "planned",
                "patch_accepted": final_status == "proposed",
                "patch_rejected": final_status != "proposed",
                "sandbox_result": {
                    "applied": sandbox.get("applied"),
                    "syntax_valid": sandbox.get("syntax_valid"),
                    "semantic_valid": sandbox.get("semantic_valid"),
                },
                "apply_result": "not_run",
                "retry_count": max(0, coder_mock.call_count - 1),
                "retry_succeeded": final_status == "proposed" and coder_mock.call_count > 1,
                "failure_code": failure_code,
                "final_status": final_status,
                "expected_to_succeed": expected_to_succeed,
                "pass_fail_record": {
                    "expected_final_status": expected_final_status,
                    "expected_failure_code": expected_failure_code,
                    "passed": passed,
                },
            }
        finally:
            self._cleanup_session(session)

    def run_pack_ab(self, cases=None, output_path=None):
        """Run the benchmark twice — with and without lesson memory — and report the delta."""
        cases = list(build_reliability_benchmark_pack() if cases is None else cases)
        report_with = self.run_pack(cases=cases, include_reproducibility=False, _lessons_enabled=True)
        report_without = self.run_pack(cases=cases, include_reproducibility=False, _lessons_enabled=False)

        s_with    = report_with["summary"]
        s_without = report_without["summary"]
        ab_report = {
            "with_lessons":    s_with,
            "without_lessons": s_without,
            "delta": {
                "passed_cases":                    s_with["passed_cases"]                    - s_without["passed_cases"],
                "successful_patch_cases_passed":   s_with["successful_patch_cases_passed"]   - s_without["successful_patch_cases_passed"],
                "expected_failure_cases_passed":   s_with["expected_failure_cases_passed"]   - s_without["expected_failure_cases_passed"],
                "true_regressions":                s_with["true_regressions"]                - s_without["true_regressions"],
            },
            "verdict": (
                "lessons HELP" if s_with["passed_cases"] > s_without["passed_cases"]
                else "lessons HURT" if s_with["passed_cases"] < s_without["passed_cases"]
                else "no difference"
            ),
        }
        if output_path:
            Path(output_path).write_text(json.dumps(ab_report, indent=2))
        return ab_report

    def run_pack(self, cases=None, output_path=None, include_reproducibility=True, _lessons_enabled=True):
        cases = list(build_reliability_benchmark_pack() if cases is None else cases)
        records = [self.run_case(case, lessons_enabled=_lessons_enabled) for case in cases]

        band_counts = Counter(record["band"] for record in records)
        failure_counts = Counter(
            record["failure_code"]
            for record in records
            if record.get("failure_code")
        )
        top_failure_classes = [
            {"failure_code": code, "count": count}
            for code, count in failure_counts.most_common(5)
        ]
        passed_cases = sum(1 for record in records if record["pass_fail_record"]["passed"])
        successful_patch_cases = [
            record for record in records
            if record["pass_fail_record"]["expected_final_status"] == "proposed"
        ]
        expected_failure_cases = [
            record for record in records
            if record["pass_fail_record"]["expected_final_status"] != "proposed"
        ]
        successful_patch_cases_passed = sum(
            1 for record in successful_patch_cases
            if record["pass_fail_record"]["passed"]
        )
        expected_failure_cases_passed = sum(
            1 for record in expected_failure_cases
            if record["pass_fail_record"]["passed"]
        )
        true_regressions = [
            record for record in records
            if not record["pass_fail_record"]["passed"]
        ]

        summary = {
            "total_cases": len(records),
            "passed_cases": passed_cases,
            "failed_cases": len(records) - passed_cases,
            "successful_patch_cases_total": len(successful_patch_cases),
            "successful_patch_cases_passed": successful_patch_cases_passed,
            "successful_patch_cases_failed": len(successful_patch_cases) - successful_patch_cases_passed,
            "expected_failure_cases_total": len(expected_failure_cases),
            "expected_failure_cases_passed": expected_failure_cases_passed,
            "expected_failure_cases_failed": len(expected_failure_cases) - expected_failure_cases_passed,
            "true_regressions": len(true_regressions),
            "bands": dict(band_counts),
            "top_failure_classes": top_failure_classes,
        }
        report = {
            "summary": summary,
            "records": records,
        }
        if include_reproducibility:
            report["reproducibility"] = {
                "manifest": self._build_reproducibility_manifest(cases),
                "report_signature": self._report_signature(report),
            }

        if output_path:
            Path(output_path).write_text(json.dumps(report, indent=2), encoding="utf-8")

        return report

    def run_reproducibility_check(self, cases=None, repeats=2, output_path=None):
        if repeats < 2:
            raise ValueError("Reproducibility checks require at least two repeats.")

        cases = list(build_reliability_benchmark_pack() if cases is None else cases)
        runs = [self.run_pack(cases=cases) for _ in range(repeats)]
        signatures = [
            run.get("reproducibility", {}).get("report_signature") or self._report_signature(run)
            for run in runs
        ]
        baseline_signature = signatures[0] if signatures else None
        mismatches = [
            {
                "run_index": index,
                "signature": signature,
                "baseline_signature": baseline_signature,
            }
            for index, signature in enumerate(signatures[1:], start=1)
            if signature != baseline_signature
        ]
        summary = {
            "repeats": repeats,
            "case_count": len(cases),
            "baseline_signature": baseline_signature,
            "matching_runs": repeats - len(mismatches),
            "mismatched_runs": len(mismatches),
            "all_checks_passed": len(mismatches) == 0,
        }
        report = {
            "summary": summary,
            "manifest": self._build_reproducibility_manifest(cases),
            "runs": [
                {
                    "run_index": index,
                    "report_signature": signature,
                    "summary": run["summary"],
                }
                for index, (run, signature) in enumerate(zip(runs, signatures))
            ],
            "mismatches": mismatches,
        }

        if output_path:
            Path(output_path).write_text(json.dumps(report, indent=2), encoding="utf-8")

        return report


def main():
    harness = ReliabilityBenchmarkHarness()
    report = harness.run_pack()
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()

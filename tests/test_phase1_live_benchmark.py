import json
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from HiveLessonMemory import LessonMemory
from HiveStateManager import HiveStateManager
from coder import CoderAgent
from coder_prompting import prepare_context_for_prompt
from executor import ExecutorAgent
from failure_intelligence import interpret_failure
from planner import PlannerAgent
from reflector import Reflector

ORIGINAL_TEMP_DIR = tempfile.TemporaryDirectory


class Phase1LiveBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.repo_root = Path(__file__).resolve().parents[1]
        self.temp_root = Path(__file__).resolve().parent / f"_tmp_live_phase1_{uuid.uuid4().hex}"
        self.temp_root.mkdir(parents=True, exist_ok=False)
        self.addCleanup(lambda: shutil.rmtree(self.temp_root, ignore_errors=True))

        self.state = HiveStateManager(
            snapshot_path=self.temp_root / "snapshot.json",
            repo_root=self.repo_root,
        )
        self.state.rebuild_repo_map()

        self.planner = PlannerAgent(state_manager=self.state)
        self.reflector = Reflector()
        self.coder = CoderAgent(
            state_manager=self.state,
            executor=ExecutorAgent(backup_dir=self.temp_root / "backups"),
        )
        self.coder.lesson_memory = LessonMemory(path=str(self.temp_root / "lessons.jsonl"), max_entries=100)

    def _workspace_sandbox_test(self, patch_text, target_file, patch_reason=""):
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

        sandbox_dir = self.temp_root / f"sandbox_{uuid.uuid4().hex}"
        sandbox_dir.mkdir(parents=True, exist_ok=False)
        sandbox_file = sandbox_dir / Path(target_file).name
        report["sandbox_file"] = str(sandbox_file)

        try:
            shutil.copy2(self.repo_root / target_file, sandbox_file)
            self.coder.executor.apply_patch(
                patch_text,
                str(sandbox_file),
                patch_reason=patch_reason,
            )
            report["applied"] = True

            sandbox_file_text = sandbox_file.read_text(encoding="utf-8")
            syntax_check = self.coder.executor._validate_python_syntax(sandbox_file_text)
            report["syntax_valid"] = syntax_check["valid"]
            if not syntax_check["valid"]:
                report["errors"].append(
                    f"Syntax error: {self.coder.executor._format_syntax_error(syntax_check['error'])}"
                )

            semantic_check = self.coder.executor.validate_patch_semantics(
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

    def _make_parent_task(self, task_id, note, target_file, target_symbol, benchmark_case_id=None):
        span = self.state.get_symbol_span(target_file, target_symbol)
        anchor = {
            "target_file": target_file,
            "target_symbol": target_symbol,
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
            "id": task_id,
            "tag": "task",
            "status": "active",
            "note": note,
            "target_file": target_file,
            "target_symbol": target_symbol,
            "metadata": {
                "target_file": target_file,
                "target_symbol": target_symbol,
                "anchor": anchor,
                "benchmark_case_id": benchmark_case_id,
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

    def _build_benchmark_record(self, *, case_name, plan, result, planner_calls, coder_calls, failure_code=None):
        sandbox = result.get("sandbox_report") or {}
        return {
            "name": case_name,
            "planner_source": plan.get("source"),
            "planner_success": plan.get("status") == "planned",
            "coder_first_attempt_success": result.get("status") == "proposed" and coder_calls == 1,
            "retry_count": max(0, coder_calls - 1),
            "sandbox_success": (
                sandbox.get("applied") is True
                and sandbox.get("syntax_valid") is True
                and sandbox.get("semantic_valid") is True
            ),
            "reflector_verdict": (result.get("reflection") or {}).get("verdict"),
            "final_status": result.get("status"),
            "failure_code": failure_code,
        }

    def _run_case(self, case):
        parent_task = self._make_parent_task(
            case["task_id"],
            case["task_note"],
            case["target_file"],
            case["target_symbol"],
            benchmark_case_id=case["name"],
        )

        planner_response = case.get("planner_raw_response")
        if planner_response is None:
            planner_response = json.dumps(case["plan_response"])
        reflection_response = json.dumps({
            "reflection": "Patch stays within the requested symbol and is safe to review.",
            "confidence": 0.92,
            "next_step": "Approve patch.",
            "verdict": "accept",
        })

        with patch("planner.ask_model", return_value=planner_response) as planner_mock:
            plan = self.planner.plan_task(parent_task)

        self.assertEqual(plan.get("status"), case.get("expected_plan_status", "planned"), msg=f"planner failed for {case['name']}: {plan}")
        self.assertEqual(planner_mock.call_count, 1, msg=f"planner should run once for {case['name']}")
        self.assertEqual(plan.get("source"), case.get("expected_planner_source", plan.get("source")))

        coder_task, effective_plan = self._build_coder_task(parent_task, plan)

        coder_side_effect = case.get("coder_side_effect")
        if coder_side_effect is None:
            coder_patch = patch("coder.ask_model", return_value=case["coder_response"])
        else:
            coder_patch = patch("coder.ask_model", side_effect=coder_side_effect)

        with coder_patch as coder_mock:
            with patch("reflector.ask_model", return_value=reflection_response) as reflector_mock:
                with patch.object(self.coder.executor, "test_patch_in_sandbox", side_effect=self._workspace_sandbox_test):
                    result = self.coder.generate_patch_with_revisions(coder_task, effective_plan, self.reflector)

        expected_final_status = case.get("expected_final_status", "proposed")
        self.assertEqual(result.get("status"), expected_final_status, msg=f"coder failed for {case['name']}: {result}")

        failure_code = None
        if expected_final_status == "proposed":
            self.assertEqual(coder_mock.call_count, case.get("expected_coder_calls", 1), msg=f"unexpected coder attempts for {case['name']}")
            self.assertEqual(reflector_mock.call_count, 1, msg=f"reflector should run once for {case['name']}")
            self.assertEqual(result.get("target_file"), case["target_file"])
            self.assertEqual(result.get("context_target"), case["target_symbol"])
            anchor = (coder_task.get("metadata") or {}).get("anchor") or {}
            self.assertEqual(result.get("context_symbol_id"), anchor.get("target_symbol_id"))
            self.assertEqual((result.get("context_span") or {}).get("lineno"), anchor.get("lineno"))
            self.assertEqual((result.get("context_span") or {}).get("end_lineno"), anchor.get("end_lineno"))
            sandbox = result.get("sandbox_report") or {}
            self.assertTrue(sandbox.get("applied"), msg=f"sandbox apply failed for {case['name']}: {sandbox}")
            self.assertTrue(sandbox.get("syntax_valid"), msg=f"syntax failed for {case['name']}: {sandbox}")
            self.assertTrue(sandbox.get("semantic_valid"), msg=f"semantic failed for {case['name']}: {sandbox}")
            self.assertEqual((result.get("reflection") or {}).get("verdict"), "accept")
        else:
            interpretation = interpret_failure(
                stage=case.get("failure_stage", "benchmark"),
                error_text=result.get("llm_error"),
                task=coder_task,
                patch_data=result,
                metadata={
                    "planner_source": plan.get("source"),
                    "benchmark_case_id": case["name"],
                },
            )
            failure_code = interpretation.classification.failure_code
            self.assertEqual(failure_code, case.get("expected_failure_code"))

        return self._build_benchmark_record(
            case_name=case["name"],
            plan=plan,
            result=result,
            planner_calls=planner_mock.call_count,
            coder_calls=coder_mock.call_count,
            failure_code=failure_code,
        )

    def test_phase1_live_benchmark_batch(self):
        cases = [
            {
                "name": "comment_exact_symbol",
                "task_id": "live-1",
                "task_note": "Insert a comment above the anchor_span lookup in select_edit_context to explain the strict span lock.",
                "target_file": "coder_context.py",
                "target_symbol": "select_edit_context",
                "plan_response": {
                    "goal": "Clarify strict span-locked context selection in select_edit_context.",
                    "task_type": "docs",
                    "tasks": [
                        {
                            "title": "Document anchor span lookup",
                            "description": "Insert a comment above the anchor_span lookup in select_edit_context to explain the strict span lock.",
                            "target_file": "coder_context.py",
                            "target_symbol": "select_edit_context",
                            "change_intent": "modify_existing_logic",
                            "completion_cues": [
                                "# Enforce span-locked selection before building exact-symbol context.",
                            ],
                        }
                    ],
                    "dependencies": ["coder_context.py"],
                    "risks": ["Misplaced comment could drift outside the target symbol."],
                    "next_action": "Insert the explanatory comment in select_edit_context.",
                    "status": "planned",
                },
                "coder_response": (
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
                ),
            },
            {
                "name": "logic_exact_symbol_diff",
                "task_id": "live-2",
                "task_note": "Update _build_response so it copies the context mapping before returning it.",
                "target_file": "interface.py",
                "target_symbol": "_build_response",
                "plan_response": {
                    "goal": "Keep Interface responses from sharing mutable context objects.",
                    "task_type": "bugfix",
                    "tasks": [
                        {
                            "title": "Copy response context",
                            "description": "Update _build_response to copy the provided context mapping before returning it.",
                            "target_file": "interface.py",
                            "target_symbol": "_build_response",
                            "change_intent": "modify_existing_logic",
                            "completion_cues": [
                                '"context": dict(context or {}),',
                            ],
                        }
                    ],
                    "dependencies": ["interface.py"],
                    "risks": ["Changing response construction could drift outside the target method."],
                    "next_action": "Modify _build_response in Interface.",
                    "status": "planned",
                },
                "coder_response": (
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
                ),
            },
            {
                "name": "block_rewrite_router_normalize",
                "task_id": "live-3",
                "task_note": "Tighten normalize_command so it handles missing command values safely.",
                "target_file": "router.py",
                "target_symbol": "normalize_command",
                "plan_response": {
                    "goal": "Keep command normalization safe for missing values.",
                    "task_type": "bugfix",
                    "tasks": [
                        {
                            "title": "Guard normalize_command input",
                            "description": "Update normalize_command to handle missing command values safely before lowercasing.",
                            "target_file": "router.py",
                            "target_symbol": "normalize_command",
                            "change_intent": "modify_existing_logic",
                            "completion_cues": [
                                "return str(command or \"\").lower().strip()",
                            ],
                        }
                    ],
                    "dependencies": ["router.py"],
                    "risks": ["A broad rewrite could touch unrelated routing logic."],
                    "next_action": "Patch normalize_command in Router.",
                    "status": "planned",
                },
                "coder_response": (
                    "    def normalize_command(self, command):\n"
                    "        return str(command or \"\").lower().strip()\n"
                ),
            },
        ]

        results = [self._run_case(case) for case in cases]

        self.assertEqual(len(results), 3)
        self.assertTrue(all(item["final_status"] == "proposed" for item in results))
        self.assertTrue(all(item["planner_source"] == "llm" for item in results))
        self.assertTrue(all(item["coder_first_attempt_success"] for item in results))

    def test_phase1_benchmark_path_reporting(self):
        cases = [
            {
                "name": "planner_fallback_comment_task",
                "task_id": "live-fallback",
                "task_note": "Insert a comment above the anchor_span lookup in select_edit_context to explain the strict span lock.",
                "target_file": "coder_context.py",
                "target_symbol": "select_edit_context",
                "planner_raw_response": "not json at all",
                "expected_planner_source": "fallback_narrow_task",
                "expected_plan_status": "planned",
                "expected_final_status": "proposed",
                "coder_response": (
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
                ),
            },
            {
                "name": "missing_context_block_failure",
                "task_id": "live-missing-context",
                "task_note": "Insert the exact line `if not isinstance(cue, str): continue` into _normalize_completion_cues.",
                "target_file": "planner.py",
                "target_symbol": "_normalize_completion_cues",
                "plan_response": {
                    "goal": "Insert the missing cue-type guard into _normalize_completion_cues.",
                    "task_type": "bugfix",
                    "tasks": [
                        {
                            "title": "Ignore empty non-string cues",
                            "description": "Insert the exact line `if not isinstance(cue, str): continue` into _normalize_completion_cues.",
                            "target_file": "planner.py",
                            "target_symbol": "_normalize_completion_cues",
                            "change_intent": "modify_existing_logic",
                            "completion_cues": ['if not isinstance(cue, str): continue'],
                        }
                    ],
                    "dependencies": ["planner.py"],
                    "risks": ["A context-free patch could drift outside the target function."],
                    "next_action": "Patch _normalize_completion_cues in PlannerAgent.",
                    "status": "planned",
                },
                "coder_side_effect": [(
                    "TARGET_FILE: planner.py\n"
                    "CHANGE_TYPE: diff_patch\n"
                    "RISK_LEVEL: low\n"
                    "STATUS: proposed\n"
                    "REASON: Attempt to normalize completion cues.\n"
                    "PATCH:\n"
                    "--- planner.py\n"
                    "+++ planner.py\n"
                    "@@ -1,0 +1,1 @@\n"
                    "+        if not isinstance(cue, str): continue\n"
                )] * 3,
                "expected_final_status": "blocked",
                "expected_failure_code": "missing_context_block",
            },
            {
                "name": "mixed_scope_patch_failure",
                "task_id": "live-mixed-scope",
                "task_note": "Update _build_response so it copies the provided context mapping before returning it.",
                "target_file": "interface.py",
                "target_symbol": "_build_response",
                "plan_response": {
                    "goal": "Keep Interface responses from sharing mutable context objects.",
                    "task_type": "bugfix",
                    "tasks": [
                        {
                            "title": "Copy response context",
                            "description": "Update _build_response to copy the provided context mapping before returning it.",
                            "target_file": "interface.py",
                            "target_symbol": "_build_response",
                            "change_intent": "modify_existing_logic",
                            "completion_cues": ['"context": dict(context or {}),'],
                        }
                    ],
                    "dependencies": ["interface.py"],
                    "risks": ["Changing response construction could drift outside the target method."],
                    "next_action": "Modify _build_response in Interface.",
                    "status": "planned",
                },
                "coder_side_effect": [(
                    "TARGET_FILE: interface.py\n"
                    "CHANGE_TYPE: diff_patch\n"
                    "RISK_LEVEL: low\n"
                    "STATUS: proposed\n"
                    "REASON: Bad mixed-scope patch for benchmark coverage.\n"
                    "PATCH:\n"
                    "--- interface.py\n"
                    "+++ interface.py\n"
                    "@@ -44,7 +44,9 @@ class Interface:\n"
                    "     def _build_response(self, intent, text, context=None):\n"
                    "+helper_context = {}\n"
                    "+        context = dict(context or {})\n"
                    "         return {\n"
                    "             \"intent\": intent,\n"
                    "             \"context\": context or {},\n"
                )] * 3,
                "expected_final_status": "blocked",
                "expected_failure_code": "mixed_scope_patch",
            },
        ]

        records = [self._run_case(case) for case in cases]
        by_name = {record["name"]: record for record in records}

        self.assertEqual(by_name["planner_fallback_comment_task"]["planner_source"], "fallback_narrow_task")
        self.assertTrue(by_name["planner_fallback_comment_task"]["coder_first_attempt_success"])
        self.assertEqual(by_name["missing_context_block_failure"]["failure_code"], "missing_context_block")
        self.assertEqual(by_name["mixed_scope_patch_failure"]["failure_code"], "mixed_scope_patch")
        self.assertGreaterEqual(by_name["missing_context_block_failure"]["retry_count"], 1)
        self.assertGreaterEqual(by_name["mixed_scope_patch_failure"]["retry_count"], 1)

    def test_large_file_trimmed_context_case_reports_budget_metadata(self):
        full_file_text = (self.repo_root / "main.py").read_text(encoding="utf-8")
        context = {
            "mode": "block_window",
            "context_text": full_file_text,
            "context_priority": ["block_window", "line_window", "file_head_fallback"],
            "anchoring_confidence": "high",
            "selected_block": {
                "name": "route",
                "type": "function",
                "lineno": 1,
                "end_lineno": min(len(full_file_text.splitlines()), 400),
                "text": "def route(...):\n" + ("    branch = handler\n" * 1200),
            },
        }

        prompt_text, budget = prepare_context_for_prompt(
            target_file="main.py",
            context=context,
            full_file_text=full_file_text,
            related_context_text="related\n" * 2000,
            prompt_kind="revision",
            task={"id": "bench-main-trim", "note": "Update route in main.py.", "target_symbol": "route"},
            file_summary={
                "char_count": len(full_file_text),
                "symbol_count": 60,
                "symbol_inventory": [{"type": "function", "symbol": "route", "lineno": 1, "end_lineno": 400}],
                "high_value_symbols": [{"type": "function", "symbol": "route", "lineno": 1, "end_lineno": 400}],
                "route_branch_inventory": ["help", "show_patch", "apply_patch"],
            },
        )

        record = {
            "name": "large_file_trimmed_context",
            "planner_source": "llm",
            "planner_success": True,
            "coder_first_attempt_success": True,
            "retry_count": 0,
            "sandbox_success": True,
            "reflector_verdict": "accept",
            "final_status": "trimmed",
            "failure_code": None,
            "budget_decision": budget.get("budget_decision"),
        }

        self.assertTrue(budget.get("trimmed"))
        self.assertEqual(record["budget_decision"], "summary_used")
        self.assertIn("FILE SUMMARY: main.py", prompt_text)


if __name__ == "__main__":
    unittest.main()

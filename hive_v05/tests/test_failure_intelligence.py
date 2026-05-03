import unittest

from failure_intelligence import interpret_failure


class FailureIntelligenceTests(unittest.TestCase):
    def test_missing_diff_headers(self):
        result = interpret_failure(
            stage="exception",
            error_text="Patch is missing diff file headers.",
            task={"id": "t1", "target_file": "coder.py"},
        )
        self.assertEqual(result.classification.failure_code, "missing_diff_headers")
        self.assertIn("diff", result.revision.retry_instruction.lower())

    def test_multiple_patch_sections(self):
        result = interpret_failure(
            stage="exception",
            error_text="Model response contains multiple PATCH: sections.",
            task={"id": "t2", "target_file": "coder.py"},
        )
        self.assertEqual(result.classification.failure_code, "multiple_patch_sections")
        self.assertIn("exactly one", result.revision.retry_instruction.lower())

    def test_symbol_anchor_drift(self):
        result = interpret_failure(
            stage="exception",
            error_text="symbol_anchor_drift: patch modifies unrelated symbols ['helper']; only target_fn may change.",
            task={"id": "t3", "target_file": "coder.py", "target_symbol": "target_fn"},
        )
        self.assertEqual(result.classification.failure_code, "symbol_anchor_drift")
        self.assertIn("target symbol", result.revision.retry_instruction.lower())

    def test_scope_alignment_mismatch_is_classified_explicitly(self):
        result = interpret_failure(
            stage="exception",
            error_text="scope_alignment_mismatch: Patch appears misaligned with task scope for change_intent=modify_existing_logic: no meaningful keyword overlap with task note.",
            task={"id": "t3b", "target_file": "coder.py", "target_symbol": "target_fn"},
        )
        self.assertEqual(result.classification.failure_code, "scope_alignment_mismatch")
        self.assertIn("task scope", result.revision.retry_instruction.lower())

    def test_block_rewrite_wrong_method_is_classified_explicitly(self):
        result = interpret_failure(
            stage="exception",
            error_text="block_rewrite_wrong_method: Block rewrite returned incorrect method. Expected route",
            task={"id": "t3c", "target_file": "main.py", "target_symbol": "route"},
        )
        self.assertEqual(result.classification.failure_code, "block_rewrite_wrong_method")
        self.assertIn("exact anchored method", result.revision.retry_instruction.lower())

    def test_block_rewrite_contract_failure_is_classified_explicitly(self):
        result = interpret_failure(
            stage="exception",
            error_text="block_rewrite_contract_failure: Block rewrite changed the target method signature. Preserve the original def line and rewrite only the in-method logic.",
            task={"id": "t3d", "target_file": "main.py", "target_symbol": "route"},
        )
        self.assertEqual(result.classification.failure_code, "block_rewrite_contract_failure")
        self.assertIn("block rewrite contract", result.revision.retry_instruction.lower())

    def test_local_assignment_at_module_scope(self):
        result = interpret_failure(
            stage="sandbox",
            error_text="Sandbox semantic failed: Semantic issues detected.",
            task={"id": "t4", "target_file": "main.py", "target_symbol": "route"},
            patch_data={"patch_id": "p4"},
            sandbox_report={
                "applied": True,
                "syntax_valid": True,
                "semantic_valid": False,
                "details": {
                    "variable_scope_sanity": {
                        "reason": "assignment appears at module scope",
                        "problematic_line": "result = route_map.get(intent)",
                    }
                },
            },
        )
        self.assertEqual(result.classification.failure_code, "local_assignment_at_module_scope")
        self.assertIn("inside the target function body", result.revision.retry_instruction.lower())

    def test_inserted_after_terminal_statement(self):
        result = interpret_failure(
            stage="sandbox",
            error_text="Sandbox semantic failed: Patch appears to insert executable code after a terminal statement.",
            task={"id": "t5", "target_file": "main.py"},
            sandbox_report={
                "applied": True,
                "syntax_valid": True,
                "semantic_valid": False,
                "details": {
                    "no_unreachable_code_after_return": {
                        "terminal_line": "return result",
                        "reason": "patch appears to insert executable code after a terminal statement in the same block",
                    }
                },
            },
        )
        self.assertEqual(result.classification.failure_code, "inserted_after_terminal_statement")
        self.assertIn("above the return", result.revision.retry_instruction.lower())

    def test_duplicate_docstring(self):
        result = interpret_failure(
            stage="sandbox",
            error_text="Sandbox semantic failed: Structural scope issue.",
            task={"id": "t6", "target_file": "coder.py"},
            sandbox_report={
                "applied": True,
                "syntax_valid": True,
                "semantic_valid": False,
                "details": {
                    "structural_scope_valid": {
                        "reason": "candidate file contains unexpected executable structure at class scope",
                        "issues": [
                            {
                                "reason": "non-docstring expression found at class scope",
                                "lineno": 18,
                            }
                        ],
                    }
                },
            },
        )
        self.assertEqual(result.classification.failure_code, "duplicate_docstring_instead_of_edit")
        self.assertIn("existing docstring", result.revision.retry_instruction.lower())

    def test_structural_scope_invalid(self):
        result = interpret_failure(
            stage="sandbox",
            error_text="Sandbox semantic failed: Structural scope issue.",
            task={"id": "t7", "target_file": "coder.py"},
            sandbox_report={
                "applied": True,
                "syntax_valid": True,
                "semantic_valid": False,
                "details": {
                    "structural_scope_valid": {
                        "reason": "candidate file contains unexpected executable structure at class scope",
                        "issues": [{"reason": "unexpected executable structure found at class scope"}],
                    }
                },
            },
        )
        self.assertEqual(result.classification.failure_code, "structural_scope_invalid")
        self.assertIn("valid executable structure", result.revision.retry_instruction.lower())

    def test_reflector_reject(self):
        result = interpret_failure(
            stage="reflector",
            task={"id": "t8", "target_file": "coder.py"},
            reflection={
                "verdict": "reject",
                "reflection": "Patch broadens scope beyond the requested function.",
            },
        )
        self.assertEqual(result.classification.failure_code, "reflector_reject")
        self.assertIn("rejected approach", result.revision.retry_instruction.lower())

    def test_completion_cue_mismatch_disables_retry(self):
        result = interpret_failure(
            stage="exception",
            error_text="Patch does not satisfy planner completion_cues; missing expected diff cues: ['child[\"target_symbol\"] = anchored_symbol'].",
            task={"id": "t9", "target_file": "main.py", "target_symbol": "route"},
        )
        self.assertEqual(result.classification.failure_code, "completion_cue_mismatch")
        self.assertFalse(result.revision.retry_recommended)
        self.assertIn("completion cue mismatch", result.revision.retry_instruction.lower())

    def test_comment_task_nonfunctional_guard_is_classified_explicitly(self):
        result = interpret_failure(
            stage="exception",
            error_text="Patch change too small or non-functional.",
            task={
                "id": "t10",
                "target_file": "coder_context.py",
                "expected_operation": "insert_comment",
                "metadata": {
                    "expected_operation": "insert_comment",
                },
            },
        )
        self.assertEqual(result.classification.failure_code, "comment_task_rejected_as_nonfunctional")
        self.assertIn("documentation task", result.revision.retry_instruction.lower())

    def test_planner_invalid_json_is_classified_explicitly(self):
        result = interpret_failure(
            stage="planner",
            error_text="No JSON object found in model response.",
            task={"id": "t11", "target_file": "planner.py", "target_symbol": "plan_task"},
            metadata={"planner_failure_code": "invalid_llm_plan_shape"},
        )
        self.assertEqual(result.classification.failure_code, "planner_invalid_json")
        self.assertIn("fallback plan", result.revision.retry_instruction.lower())

    def test_planner_validation_failure_is_classified_explicitly(self):
        result = interpret_failure(
            stage="planner",
            error_text="Planner output failed validation: Planner produced task without target_symbol.",
            task={"id": "t12", "target_file": "planner.py"},
            metadata={"planner_failure_code": "planner_missing_target_symbol"},
        )
        self.assertEqual(result.classification.failure_code, "planner_validation_failure")
        self.assertIn("fallback plan", result.revision.retry_instruction.lower())

    def test_mixed_scope_patch_is_classified_explicitly(self):
        result = interpret_failure(
            stage="sandbox",
            error_text="Patch verification failed: {'mixed_scope_detected': True, 'safe_to_apply': False}",
            task={"id": "t13", "target_file": "main.py", "target_symbol": "route"},
        )
        self.assertEqual(result.classification.failure_code, "mixed_scope_patch")
        self.assertIn("one indentation boundary", result.revision.retry_instruction.lower())

    def test_missing_context_block_is_classified_explicitly(self):
        result = interpret_failure(
            stage="exception",
            error_text="Patch has no anchor context or removal lines.",
            task={"id": "t14", "target_file": "coder_context.py", "target_symbol": "select_edit_context"},
        )
        self.assertEqual(result.classification.failure_code, "missing_context_block")
        self.assertIn("real unchanged anchor", result.revision.retry_instruction.lower())

    def test_workspace_sandbox_permission_issue_is_classified_explicitly(self):
        result = interpret_failure(
            stage="sandbox",
            error_text="Sandbox apply failed: [WinError 5] Access is denied: 'C:\\\\Temp\\\\sandbox.py'",
            task={"id": "t15", "target_file": "coder.py"},
        )
        self.assertEqual(result.classification.failure_code, "workspace_sandbox_permission_issue")
        self.assertFalse(result.revision.retry_recommended)

    def test_oversized_context_trimmed_is_classified_from_budget_metadata(self):
        result = interpret_failure(
            stage="context_budget",
            error_text="Prompt context exceeded budget and context was trimmed.",
            task={"id": "t16", "target_file": "main.py"},
            metadata={"context_budget": {"trimmed": True, "budget_decision": "summary_used"}},
        )
        self.assertEqual(result.classification.failure_code, "oversized_context_trimmed")
        self.assertEqual(result.observability.get("budget_decision"), "summary_used")

    def test_stagnant_retry_patch_is_classified_explicitly(self):
        result = interpret_failure(
            stage="exception",
            error_text="Retry returned the same patch as the previous failed attempt.",
            task={"id": "t17", "target_file": "coder.py", "target_symbol": "generate_patch_with_revisions"},
        )
        self.assertEqual(result.classification.failure_code, "stagnant_retry_patch")
        self.assertIn("do not repeat", result.revision.retry_instruction.lower())

    def test_non_meaningful_patch_is_classified_explicitly(self):
        result = interpret_failure(
            stage="exception",
            error_text="Patch failed usefulness check: no meaningful code changes detected.",
            task={"id": "t18", "target_file": "coder.py", "target_symbol": "generate_patch_with_revisions"},
        )
        self.assertEqual(result.classification.failure_code, "non_meaningful_patch")
        self.assertIn("meaningful requested change", result.revision.retry_instruction.lower())


if __name__ == "__main__":
    unittest.main()

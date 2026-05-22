import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from HiveStateManager import HiveStateManager
from coder import CoderAgent
from coder_validation import validate_symbol_locked_patch


class HardAnchorEnforcementTests(unittest.TestCase):
    def _make_temp_root(self):
        root = Path(__file__).resolve().parent / f"_tmp_anchor_{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=False)
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        return root

    def _build_state(self):
        repo_root = Path(__file__).resolve().parents[1]
        temp_root = self._make_temp_root()
        state = HiveStateManager(snapshot_path=temp_root / "snapshot.json", repo_root=repo_root)
        state.rebuild_repo_map()
        return state

    def _build_anchor_task(self, state, target_file, target_symbol, note):
        span = state.get_symbol_span(target_file, target_symbol)
        self.assertIsNotNone(span)
        anchor = {
            "target_file": target_file,
            "target_symbol": target_symbol,
            "target_symbol_id": span.get("symbol_id"),
            "lineno": span.get("lineno"),
            "end_lineno": span.get("end_lineno"),
            "col_offset": span.get("col_offset"),
            "end_col_offset": span.get("end_col_offset"),
            "scope": "single_file",
            "anchor_level": "symbol",
            "anchor_source": "test",
        }
        return {
            "id": f"task-{target_symbol}",
            "note": note,
            "target_file": target_file,
            "target_symbol": target_symbol,
            "target_symbol_id": span.get("symbol_id"),
            "metadata": {
                "target_file": target_file,
                "target_symbol": target_symbol,
                "target_symbol_id": span.get("symbol_id"),
                "anchor": anchor,
            },
        }

    def _build_exact_patch_data(self, anchor):
        return {
            "target_file": anchor["target_file"],
            "change_type": "diff_patch",
            "risk_level": "low",
            "status": "proposed",
            "patch": (
                f"--- {anchor['target_file']}\n"
                f"+++ {anchor['target_file']}\n"
                "@@ -1,2 +1,2 @@\n"
                f" def {anchor['target_symbol']}(x):\n"
                "-    return x\n"
                "+    return x + 1\n"
            ),
            "context_mode": "exact_symbol_block",
            "context_target": anchor["target_symbol"],
            "context_symbol_id": anchor["target_symbol_id"],
            "context_span": {
                "lineno": anchor["lineno"],
                "end_lineno": anchor["end_lineno"],
                "col_offset": anchor.get("col_offset"),
                "end_col_offset": anchor.get("end_col_offset"),
            },
        }

    def test_validate_symbol_locked_patch_rejects_non_exact_context_mode(self):
        task = {
            "id": "anchor-1",
            "target_file": "sample.py",
            "target_symbol": "target_fn",
            "metadata": {
                "target_file": "sample.py",
                "target_symbol": "target_fn",
                "anchor": {
                    "target_file": "sample.py",
                    "target_symbol": "target_fn",
                    "target_symbol_id": "sample.py::target_fn",
                    "lineno": 10,
                    "end_lineno": 12,
                    "col_offset": 0,
                    "end_col_offset": 4,
                },
            },
        }
        patch_data = self._build_exact_patch_data(task["metadata"]["anchor"])
        patch_data["context_mode"] = "block_window"

        with self.assertRaisesRegex(ValueError, "exact_symbol_block context required"):
            validate_symbol_locked_patch(
                patch_data,
                task,
                selected_block={
                    "name": "target_fn",
                    "symbol_id": "sample.py::target_fn",
                    "lineno": 10,
                    "end_lineno": 12,
                    "col_offset": 0,
                    "end_col_offset": 4,
                },
            )

    def test_validate_symbol_locked_patch_rejects_mismatched_context_symbol_id(self):
        task = {
            "id": "anchor-2",
            "target_file": "sample.py",
            "target_symbol": "target_fn",
            "metadata": {
                "target_file": "sample.py",
                "target_symbol": "target_fn",
                "anchor": {
                    "target_file": "sample.py",
                    "target_symbol": "target_fn",
                    "target_symbol_id": "sample.py::target_fn",
                    "lineno": 10,
                    "end_lineno": 12,
                    "col_offset": 0,
                    "end_col_offset": 4,
                },
            },
        }
        patch_data = self._build_exact_patch_data(task["metadata"]["anchor"])
        patch_data["context_symbol_id"] = "sample.py::other_fn"

        with self.assertRaisesRegex(ValueError, "patch context symbol_id expected"):
            validate_symbol_locked_patch(
                patch_data,
                task,
                selected_block={
                    "name": "target_fn",
                    "symbol_id": "sample.py::target_fn",
                    "lineno": 10,
                    "end_lineno": 12,
                    "col_offset": 0,
                    "end_col_offset": 4,
                },
            )

    def test_validate_symbol_locked_patch_rejects_mismatched_span(self):
        task = {
            "id": "anchor-3",
            "target_file": "sample.py",
            "target_symbol": "target_fn",
            "metadata": {
                "target_file": "sample.py",
                "target_symbol": "target_fn",
                "anchor": {
                    "target_file": "sample.py",
                    "target_symbol": "target_fn",
                    "target_symbol_id": "sample.py::target_fn",
                    "lineno": 10,
                    "end_lineno": 12,
                    "col_offset": 0,
                    "end_col_offset": 4,
                },
            },
        }
        patch_data = self._build_exact_patch_data(task["metadata"]["anchor"])
        patch_data["context_span"]["end_lineno"] = 14

        with self.assertRaisesRegex(ValueError, "exact context span expected 10-12, got 10-14"):
            validate_symbol_locked_patch(
                patch_data,
                task,
                selected_block={
                    "name": "target_fn",
                    "symbol_id": "sample.py::target_fn",
                    "lineno": 10,
                    "end_lineno": 12,
                    "col_offset": 0,
                    "end_col_offset": 4,
                },
            )

    def test_validate_symbol_locked_patch_rejects_missing_selected_block(self):
        task = {
            "id": "anchor-4",
            "target_file": "sample.py",
            "target_symbol": "target_fn",
            "metadata": {
                "target_file": "sample.py",
                "target_symbol": "target_fn",
                "anchor": {
                    "target_file": "sample.py",
                    "target_symbol": "target_fn",
                    "target_symbol_id": "sample.py::target_fn",
                    "lineno": 10,
                    "end_lineno": 12,
                    "col_offset": 0,
                    "end_col_offset": 4,
                },
            },
        }
        patch_data = self._build_exact_patch_data(task["metadata"]["anchor"])

        with self.assertRaisesRegex(ValueError, "selected block missing"):
            validate_symbol_locked_patch(patch_data, task, selected_block=None)

    def test_validate_symbol_locked_patch_rejects_missing_block_rewrite_proof(self):
        task = {
            "id": "anchor-5",
            "target_file": "sample.py",
            "target_symbol": "target_fn",
            "metadata": {
                "target_file": "sample.py",
                "target_symbol": "target_fn",
                "anchor": {
                    "target_file": "sample.py",
                    "target_symbol": "target_fn",
                    "target_symbol_id": "sample.py::target_fn",
                    "lineno": 10,
                    "end_lineno": 12,
                    "col_offset": 0,
                    "end_col_offset": 4,
                },
            },
        }
        patch_data = self._build_exact_patch_data(task["metadata"]["anchor"])
        patch_data["context_span"] = {}

        with self.assertRaisesRegex(ValueError, "missing span proof"):
            validate_symbol_locked_patch(
                patch_data,
                task,
                selected_block={
                    "name": "target_fn",
                    "symbol_id": "sample.py::target_fn",
                    "lineno": 10,
                    "end_lineno": 12,
                    "col_offset": 0,
                    "end_col_offset": 4,
                },
            )

    def test_get_task_anchor_enriches_symbol_span_from_state(self):
        state = self._build_state()
        agent = CoderAgent(state_manager=state)
        task = {
            "id": "anchor-6",
            "note": "Update _build_response narrowly.",
            "target_file": "interface.py",
            "target_symbol": "_build_response",
            "metadata": {
                "target_file": "interface.py",
                "target_symbol": "_build_response",
                "anchor": {
                    "target_file": "interface.py",
                    "target_symbol": "_build_response",
                },
            },
        }

        anchor = agent._get_task_anchor(task)

        self.assertEqual(anchor["target_file"], "interface.py")
        self.assertEqual(anchor["target_symbol"], "_build_response")
        self.assertTrue(anchor["target_symbol_id"])
        self.assertIsNotNone(anchor["lineno"])
        self.assertIsNotNone(anchor["end_lineno"])

    def test_generate_patch_blocks_when_exact_symbol_context_is_missing(self):
        state = self._build_state()
        agent = CoderAgent(state_manager=state)
        task = self._build_anchor_task(
            state,
            "interface.py",
            "_build_response",
            "Update _build_response so it copies the provided context mapping before returning it.",
        )
        plan = {
            "goal": "Keep Interface responses from sharing mutable context objects.",
            "tasks": [],
            "dependencies": ["interface.py"],
            "risks": [],
            "next_action": "Modify _build_response in Interface.",
            "status": "planned",
            "source": "test",
        }
        downgraded_context = {
            "mode": "anchor_window",
            "target_name": "_build_response",
            "context_text": "def _build_response(...):\n    pass\n",
            "window_start": 0,
            "window_end": 2,
            "context_budget": {},
        }

        with patch.object(agent, "_select_context_for_intent", return_value=downgraded_context):
            with patch.object(agent, "_apply_prompt_budget", return_value=downgraded_context):
                with patch("coder.ask_hive") as ask_model_mock:
                    result = agent.generate_patch(task, plan)

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["target_file"], "interface.py")
        self.assertIn("Hard anchor enforcement blocked patch", result["reason"])
        self.assertIn("exact_symbol_block context required", result["llm_error"])
        ask_model_mock.assert_not_called()

    def test_generate_patch_compat_wrapper_returns_validated_patch(self):
        state = self._build_state()
        agent = CoderAgent(state_manager=state)
        task = self._build_anchor_task(
            state,
            "router.py",
            "normalize_command",
            "Tighten normalize_command so it handles missing command values safely.",
        )
        plan = {
            "goal": "Keep command normalization safe for missing values.",
            "tasks": [],
            "dependencies": ["router.py"],
            "risks": [],
            "next_action": "Patch normalize_command in Router.",
            "status": "planned",
            "source": "test",
        }
        patch_response = (
            "TARGET_FILE: router.py\n"
            "CHANGE_TYPE: diff_patch\n"
            "RISK_LEVEL: low\n"
            "STATUS: proposed\n"
            "REASON: tighten missing-command handling\n"
            "PATCH:\n"
            "--- router.py\n"
            "+++ router.py\n"
            "@@\n"
            "     def normalize_command(self, command):\n"
            "-            return command.lower().strip()\n"
            "+            return str(command or \"\").lower().strip()\n"
        )

        with patch("coder.ask_hive", return_value=patch_response):
            with patch.object(agent, "_sandbox_test_patch", return_value={
                "applied": True,
                "syntax_valid": True,
                "semantic_valid": True,
                "errors": [],
                "notes": "ok",
            }):
                result = agent.generate_patch(task, plan)

        self.assertEqual(result["status"], "proposed")
        self.assertEqual(result["context_mode"], "exact_symbol_block")
        self.assertEqual(result["context_target"], "normalize_command")
        self.assertEqual(result["context_symbol_id"], task["target_symbol_id"])
        self.assertEqual((result.get("context_span") or {}).get("lineno"), task["metadata"]["anchor"]["lineno"])
        self.assertIn("str(command or \"\")", result["patch"])


if __name__ == "__main__":
    unittest.main()

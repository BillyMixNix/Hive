import os
import tempfile
import unittest

from HiveLessonMemory import LessonMemory
from interface import Interface
from main import (
    build_pilot_review_packet,
    build_recovery_payload,
    decide_recovery_action,
    format_pilot_review_packet,
    list_pending_pilot_review_patches,
    list_pending_recoveries,
)
from coder import CoderAgent


class _FakeMemory:
    def __init__(self, entries):
        self._entries = entries

    def get_recent_notes(self, limit=25):
        return self._entries[-limit:]


class PilotReviewGateTests(unittest.TestCase):
    def test_interface_parses_pilot_patch_review_commands(self):
        interface = Interface()

        accept = interface.process_input("pilot accept patch 12")
        revise = interface.process_input("pilot revise patch 12 tighten to the current child step only")
        reject = interface.process_input("pilot reject patch 12 wrong symbol and wrong step")
        review = interface.process_input("review patch 12")

        self.assertEqual(accept["intent"], "pilot_accept_patch")
        self.assertEqual(accept["context"]["patch_id"], 12)
        self.assertEqual(revise["intent"], "pilot_revise_patch")
        self.assertEqual(revise["context"]["patch_id"], 12)
        self.assertIn("current child step", revise["context"]["pilot_guidance"])
        self.assertEqual(reject["intent"], "pilot_reject_patch")
        self.assertEqual(reject["context"]["patch_id"], 12)
        self.assertEqual(review["intent"], "review_patch")
        self.assertEqual(review["context"]["patch_id"], 12)

    def test_build_and_format_review_packet(self):
        patch_metadata = {
            "patch_id": "patch-7",
            "task_id": 7,
            "plan_id": "plan-7",
            "task_note": "Keep the patch aligned with the child step.",
            "child_task_id": "task-7-1",
            "child_task_title": "Tighten route alignment",
            "child_task_description": "Update route to stay on the active child step.",
            "target_file": "router.py",
            "child_target_symbol": "route",
            "reason": "Tighten route logic for the active task.",
            "reflection": {
                "verdict": "accept",
                "reflection": "Patch is localized.",
                "next_step": "Pilot review.",
            },
            "patch": (
                "--- router.py\n"
                "+++ router.py\n"
                "@@ -10,6 +10,7 @@ def route(self, user_input, message):\n"
                "-    return self.builder.build({\"intent\": normalized_input})\n"
                "+    return self.builder.build({\"intent\": normalized_input, \"step\": \"active\"})\n"
            ),
        }

        packet = build_pilot_review_packet("patch-7", patch_metadata)
        text = format_pilot_review_packet(packet)

        self.assertEqual(packet["target_symbol"], "route")
        self.assertEqual(packet["patch_stats"]["hunks"], 1)
        self.assertIn("Is this the right place to patch?", text)
        self.assertIn("Reflector Verdict: accept", text)
        self.assertIn("Patch Excerpt:", text)

    def test_pending_review_listing_filters_by_status(self):
        memory = _FakeMemory(
            [
                {"id": 3, "tag": "patch", "status": "approved", "metadata": {}},
                {"id": 4, "tag": "patch", "status": "pending_pilot_review", "metadata": {}},
                {"id": 5, "tag": "plan", "status": "planned", "metadata": {}},
                {"id": 6, "tag": "patch", "status": "pending_pilot_review", "metadata": {}},
            ]
        )

        pending = list_pending_pilot_review_patches(memory)

        self.assertEqual([entry["id"] for entry in pending], [6, 4])

    def test_pending_recoveries_listing_filters_by_recovery_status(self):
        memory = _FakeMemory(
            [
                {"id": 1, "tag": "builder", "status": "drafted", "metadata": {"recovery_status": "retry_ready", "recovery_action": "retry_patch"}},
                {"id": 2, "tag": "builder", "status": "drafted", "metadata": {}},
                {"id": 3, "tag": "task", "status": "active", "metadata": {"recovery_status": "blocked", "recovery_action": "stop_and_wait"}},
            ]
        )

        pending = list_pending_recoveries(memory)

        self.assertEqual([entry["id"] for entry in pending], [3, 1])

    def test_recovery_routing_rules(self):
        self.assertEqual(
            decide_recovery_action(
                {"location_correct": True, "task_alignment": False, "plan_step_alignment": False},
                "wrong step",
            ),
            "replan_task",
        )
        self.assertEqual(
            decide_recovery_action(
                {"location_correct": False, "task_alignment": False, "plan_step_alignment": False},
                "wrong symbol use route instead",
            ),
            "retry_patch",
        )
        self.assertEqual(
            decide_recovery_action(
                {"location_correct": None, "task_alignment": None, "plan_step_alignment": None},
                "not quite right",
            ),
            "stop_and_wait",
        )

    def test_build_recovery_payload_sets_retry_ready(self):
        payload = build_recovery_payload(
            {
                "patch_id": 9,
                "target_file": "router.py",
                "child_target_symbol": "route",
                "child_task_id": "task-1-1",
                "child_task_description": "Update route",
                "reflection": {"verdict": "revise", "reflection": "Too broad"},
                "patch": "--- router.py\n+++ router.py\n@@ -1 +1 @@\n-foo\n+bar\n",
            },
            "retry_patch",
            "wrong symbol use route instead",
        )

        self.assertEqual(payload["recovery_status"], "retry_ready")
        self.assertEqual(payload["retry_source"], "pilot_revision")
        self.assertEqual(payload["recovery_source_patch_id"], 9)

    def test_pilot_guardrails_can_be_retrieved_separately(self):
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        try:
            memory = LessonMemory(path=path)
            memory.add_lesson(
                file="router.py",
                change_type="routing",
                failure_reason="wrong step",
                retry_instruction="Keep the patch on the active child step only.",
                source="pilot",
                lesson_family="pilot_guardrail",
                target_symbol="route",
                guidance_category="wrong_step",
                guardrail_text="Keep the patch on the active child step only.",
                preferred_recovery_action="replan_task",
            )
            memory.add_lesson(
                file="router.py",
                change_type="routing",
                failure_reason="wrong symbol",
                retry_instruction="Use route, not normalize_command.",
                source="pilot",
                lesson_family="pilot_guardrail",
                target_symbol="route",
                guidance_category="wrong_symbol",
                guardrail_text="Use route, not normalize_command.",
                preferred_recovery_action="retry_patch",
            )
            memory.add_lesson(
                file="router.py",
                change_type="routing",
                failure_reason="sandbox fail",
                retry_instruction="Retry narrower.",
                source="validator",
                lesson_family="failure_retry",
                target_symbol="route",
            )

            guardrails = memory.get_pilot_guardrails(
                file="router.py",
                change_type="routing",
                target_symbol="route",
                current_context={"file": "router.py", "change_type": "routing", "target_symbol": "route"},
            )
            prompt_text = memory.format_pilot_guardrails_for_prompt(guardrails)
            retry_guardrails = memory.get_pilot_guardrails(
                file="router.py",
                change_type="routing",
                target_symbol="route",
                preferred_recovery_action="retry_patch",
                current_context={"file": "router.py", "change_type": "routing", "target_symbol": "route"},
            )

            self.assertEqual(len(guardrails), 2)
            self.assertEqual(retry_guardrails[0]["preferred_recovery_action"], "retry_patch")
            self.assertIn("wrong_step", prompt_text)
            self.assertIn("active child step", prompt_text)
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_coder_builds_pilot_retry_context(self):
        agent = CoderAgent()
        context = agent._build_pilot_retry_context(
            {
                "metadata": {
                    "retry_source": "pilot_revision",
                    "pilot_guidance": "Keep the patch on route only.",
                    "reflector_summary": {"verdict": "revise", "reflection": "Too broad"},
                    "rejected_patch_excerpt": "--- router.py\n+++ router.py\n",
                }
            }
        )

        self.assertIn("PILOT RETRY CONTEXT", context)
        self.assertIn("Keep the patch on route only.", context)
        self.assertIn("Too broad", context)


if __name__ == "__main__":
    unittest.main()

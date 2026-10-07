import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from hive_remote import qualification as q
from hive_remote import runner


class QualificationTests(unittest.TestCase):
    def test_wrong_commit_fails_before_environment_or_provider(self):
        with patch.object(q, "git", return_value="1" * 40), self.assertRaises(q.QualificationFailure):
            q.inventory(expected_commit="0" * 40)

    def test_dirty_checkout_cannot_start_provider_smoke(self):
        with patch.object(q, "git", side_effect=["a" * 40, " M hive_remote/providers.py"]), self.assertRaises(q.QualificationFailure):
            q.exact_checkout("a" * 40)

    def test_existing_controller_and_historical_corpus_bytes_unchanged(self):
        identity = q.controller_identity()
        self.assertEqual(identity["classification"], "EXACTLY_REPRODUCED")
        self.assertEqual(identity["sealed_files"], 42)
        contract = json.loads(q.CONTRACT.read_bytes())
        self.assertEqual(q.git("rev-parse", "HEAD:recovery/workshop-source-20261006"), contract["historical_corpus_tree"])

    def test_missing_environment_cannot_qualify_task(self):
        with patch.object(q, "exact_checkout"), patch.object(q.shutil, "which", return_value=None):
            report = q.inventory(expected_commit=q.git("rev-parse", "HEAD"))
        self.assertFalse(report["remote_verifier_qualified"])
        self.assertFalse(report["ready_for_model_backed_task"])
        self.assertIn("DOCKER_UNAVAILABLE", report["blockers"])
        self.assertFalse(report["recovery_002_authorization_reused"])
        self.assertEqual(report["components"]["frozen_acceptance"]["classification"], "EXACTLY_REPRODUCED")
        self.assertFalse(report["components"]["frozen_acceptance"]["model_visible"])

    def test_prepared_task_contains_no_hidden_test_content(self):
        with patch.object(q, "exact_checkout"), patch.object(q.shutil, "which", return_value=None):
            report = q.inventory(expected_commit=q.git("rev-parse", "HEAD"))
        plan = runner.prepare(report)
        self.assertEqual(plan["status"], "PREPARED_BLOCKED")
        self.assertEqual(plan["model_calls"], 0)
        self.assertEqual(plan["frozen_acceptance_sha256"], "80c1ced02955971cc827aed4e983d9407b919f47cc3af20f457f3a0f0098f159")
        serialized = json.dumps(plan)
        self.assertNotIn("assertEquals", serialized)
        self.assertNotIn("test_class", plan)
        self.assertEqual(plan["targeted_timeout_seconds"], 240)
        self.assertEqual(plan["full_timeout_seconds"], 660)

    def test_remote_gate_never_constructs_a_provider(self):
        with patch.object(runner, "exact_checkout"), patch.object(runner, "new_run") as new_run:
            import tempfile
            with tempfile.TemporaryDirectory() as temp:
                new_run.return_value = Path(temp)
                with patch.object(runner, "inventory", return_value={"remote_verifier_qualified": True}), patch.object(runner, "OpenAIProvider") as model:
                    code = runner.main(["experiment", "--expected-commit", "a" * 40, "--output-root", temp])
                self.assertEqual(code, 2)
                model.assert_not_called()
                self.assertEqual(json.loads((Path(temp) / "outcome.json").read_bytes())["status"], "BLOCKED")

    def test_workflow_has_only_manual_infrastructure_triggers_and_step_secret(self):
        import yaml
        workflow = yaml.safe_load((q.ROOT / ".github/workflows/hive-remote-api.yml").read_text())
        trigger = workflow.get("on", workflow.get(True))  # PyYAML YAML 1.1
        self.assertEqual(set(trigger), {"workflow_dispatch"})
        self.assertEqual(trigger["workflow_dispatch"]["inputs"]["mode"]["options"], ["preflight", "prepare", "smoke"])
        job = workflow["jobs"]["infrastructure"]
        self.assertNotIn("env", job)
        steps = job["steps"]
        secret_steps = [s for s in steps if "OPENAI_API_KEY" in s.get("env", {})]
        self.assertEqual(len(secret_steps), 1)
        self.assertEqual(secret_steps[0]["if"], "inputs.mode == 'smoke'")
        self.assertFalse(steps[0]["with"]["persist-credentials"])
        self.assertTrue(steps[-1]["if"] == "always()")
        for step in steps:
            if "uses" in step:
                self.assertEqual(len(step["uses"].rsplit("@", 1)[1]), 40)


if __name__ == "__main__":
    unittest.main()

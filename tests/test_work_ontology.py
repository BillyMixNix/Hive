import unittest

from work_ontology import build_work_profile, infer_domain, infer_work_mode, normalize_work_mode


class WorkOntologyTests(unittest.TestCase):
    def test_modes_transfer_across_domains(self):
        self.assertEqual(infer_work_mode("research market demand before making an offer"), "research")
        self.assertEqual(infer_work_mode("create a new onboarding draft"), "create")
        self.assertEqual(infer_work_mode("validate the proof claim"), "validate")
        self.assertEqual(infer_work_mode("configure the default timeout"), "configure")

    def test_domain_is_separate_from_mode(self):
        self.assertEqual(infer_domain("prove a Collatz lemma"), "math")
        self.assertEqual(infer_domain("create a new GUI switch", target_file="hive_gui.py"), "code")
        self.assertEqual(infer_domain("research market demand"), "business")

    def test_build_profile_maps_code_create_task(self):
        profile = build_work_profile(
            task={"note": "add a switch in the gui for dark mode", "target_file": "hive_gui.py"},
            plan={"task_type": "feature"},
            child={
                "description": "Add a control and wire state in the GUI.",
                "artifact": "GUI capability",
                "operation": "add control plus state wiring",
                "validation": "AST parse plus launch smoke test",
            },
        )

        self.assertEqual(profile["work_mode"], "create")
        self.assertEqual(profile["domain"], "code")
        self.assertEqual(profile["artifact"], "GUI capability")
        self.assertEqual(profile["operation"], "add control plus state wiring")
        self.assertEqual(profile["validation"], "AST parse plus launch smoke test")

    def test_build_profile_maps_task_backlog_create_task(self):
        profile = build_work_profile(
            task={"note": "create a way of clearing older tasks that no longer need to be completed"},
        )

        self.assertEqual(profile["work_mode"], "create")
        self.assertEqual(profile["domain"], "code")
        self.assertEqual(profile["artifact"], "task backlog")
        self.assertEqual(profile["operation"], "clear stale task records")
        self.assertEqual(profile["validation"], "route smoke test plus memory status check")

    def test_task_type_default_still_supports_legacy_plans(self):
        self.assertEqual(normalize_work_mode(task_type="bugfix"), "repair")
        self.assertEqual(normalize_work_mode(task_type="feature"), "create")


if __name__ == "__main__":
    unittest.main()

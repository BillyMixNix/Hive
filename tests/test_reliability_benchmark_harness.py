import unittest

from benchmark_harness import ReliabilityBenchmarkHarness
from benchmark_pack import build_reliability_benchmark_pack


class ReliabilityBenchmarkHarnessTests(unittest.TestCase):
    def test_benchmark_pack_has_four_bands_of_ten(self):
        cases = build_reliability_benchmark_pack()

        self.assertEqual(len(cases), 40)

        by_band = {}
        for case in cases:
            by_band.setdefault(case["band"], 0)
            by_band[case["band"]] += 1

        self.assertEqual(by_band["comment_docstring"], 10)
        self.assertEqual(by_band["narrow_logic_edits"], 10)
        self.assertEqual(by_band["architectural_in_place_rewrites"], 10)
        self.assertEqual(by_band["route_flow_state"], 10)

    def test_harness_reports_case_metrics_and_top_failure_classes(self):
        harness = ReliabilityBenchmarkHarness()
        cases = build_reliability_benchmark_pack()[:6]

        report = harness.run_pack(cases=cases)

        self.assertEqual(report["summary"]["total_cases"], 6)
        self.assertEqual(len(report["records"]), 6)
        self.assertIn("top_failure_classes", report["summary"])
        self.assertIn("successful_patch_cases_passed", report["summary"])
        self.assertIn("expected_failure_cases_passed", report["summary"])
        self.assertIn("true_regressions", report["summary"])
        self.assertTrue(all("selected_context_mode" in record for record in report["records"]))
        self.assertTrue(all("prompt_length" in record for record in report["records"]))
        self.assertTrue(all("sandbox_result" in record for record in report["records"]))
        self.assertTrue(all("pass_fail_record" in record for record in report["records"]))
        self.assertTrue(all("expected_to_succeed" in record for record in report["records"]))

    def test_lesson_learning_benchmark_proves_reuse_and_safety_gating(self):
        harness = ReliabilityBenchmarkHarness()

        report = harness.run_lesson_learning_benchmark()

        self.assertTrue(report["summary"]["seed_exact_lesson_recorded"])
        self.assertGreaterEqual(report["summary"]["seed_exact_lesson_successes"], 2)
        self.assertTrue(report["summary"]["generalized_lesson_created"])
        self.assertTrue(report["summary"]["compatible_generalized_available"])
        self.assertTrue(report["summary"]["compatible_guidance_changed"])
        self.assertIn("trigger_pattern", report["summary"]["generalized_match_reasons"])
        self.assertIn("generalized", report["summary"]["generalized_match_reasons"])
        self.assertTrue(report["summary"]["unsafe_generalized_skipped"])
        self.assertTrue(report["summary"]["all_checks_passed"])


if __name__ == "__main__":
    unittest.main()

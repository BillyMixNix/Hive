from validation.ab_run import run_sequence_ab
from validation.experiment_cases import build_lesson_reuse_experiment_pack


CASES = [
    {"name": "seed"},
    {"name": "reuse"},
]


class FakeHarness:
    def run_sequence(self, cases, lessons_enabled=True):
        assert [case["name"] for case in cases] == ["seed", "reuse"]
        if lessons_enabled:
            return [
                {
                    "name": "seed",
                    "final_status": "blocked",
                    "retry_count": 2,
                    "failure_code": "missing_diff_headers",
                    "pass_fail_record": {"passed": True},
                },
                {
                    "name": "reuse",
                    "final_status": "proposed",
                    "retry_count": 0,
                    "failure_code": None,
                    "pass_fail_record": {"passed": True},
                },
            ]
        return [
            {
                "name": "seed",
                "final_status": "blocked",
                "retry_count": 2,
                "failure_code": "missing_diff_headers",
                "pass_fail_record": {"passed": True},
            },
            {
                "name": "reuse",
                "final_status": "blocked",
                "retry_count": 2,
                "failure_code": "missing_diff_headers",
                "pass_fail_record": {"passed": False},
            },
        ]


def test_sequence_ab_measures_cross_case_lesson_advantage(tmp_path):
    output = tmp_path / "ab.json"
    report = run_sequence_ab(
        cases=CASES,
        repeats=3,
        harness_factory=FakeHarness,
        output_path=output,
    )

    assert report["verdict"] == "lessons_help"
    assert report["paired_summary"]["passed_cases"]["paired_delta_mean"] == 1.0
    assert report["paired_summary"]["total_retries"]["paired_delta_mean"] == -2.0
    assert report["paired_summary"]["true_regressions"]["paired_delta_mean"] == -1.0
    assert report["repeat_records"][0]["arm_order"] == ["with_lessons", "without_lessons"]
    assert report["repeat_records"][1]["arm_order"] == ["without_lessons", "with_lessons"]
    assert len(report["repeat_records"]) == 3
    assert output.is_file()


def test_real_hive_harness_detects_seeded_lesson_reuse():
    observations = []
    report = run_sequence_ab(
        cases=build_lesson_reuse_experiment_pack(observations),
        repeats=2,
    )

    assert report["verdict"] == "lessons_help"
    assert report["paired_summary"]["passed_cases"]["paired_delta_mean"] == 1.0
    assert report["paired_summary"]["total_retries"]["paired_delta_mean"] < 0
    assert any(observations)
    assert any(seen is False for seen in observations)


def test_sequence_ab_rejects_empty_case_set():
    try:
        run_sequence_ab(cases=[], repeats=1, harness_factory=FakeHarness)
    except ValueError as exc:
        assert "at least one case" in str(exc)
    else:
        raise AssertionError("Expected empty case set to be rejected")

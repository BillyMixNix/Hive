from validation.ab_run import run_sequence_ab


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
    assert len(report["repeat_records"]) == 3
    assert output.is_file()


def test_sequence_ab_rejects_empty_case_set():
    try:
        run_sequence_ab(cases=[], repeats=1, harness_factory=FakeHarness)
    except ValueError as exc:
        assert "at least one case" in str(exc)
    else:
        raise AssertionError("Expected empty case set to be rejected")

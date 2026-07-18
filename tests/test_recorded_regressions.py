import json
from pathlib import Path

from regression_gate import RegressionGate


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_recorded_regressions_pass():
    report = RegressionGate(REPO_ROOT / "validation" / "regressions").run_all(REPO_ROOT)
    assert report["passed"], json.dumps(report, indent=2, sort_keys=True)

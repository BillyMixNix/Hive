"""Billy's explicit second attempt, carrying the original total spending forward."""
import hashlib
from pathlib import Path

from .cloud_trial import main as run_cloud, SUITE_SHA256
from .evaluate import strict_json


PRIOR_REPORT_SHA256 = "1a3e5592f010235eb08ccc615b0b4b3571a3158e578466c9f0da7f7a9d98e716"
PRIOR_EPISODE = "070f26ab17e167af098f591d33430a57beb1eae1c5348ed14cd9f9769ae5e390"


def read_prior(path):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != PRIOR_REPORT_SHA256:
        raise ValueError("prior trial report commitment mismatch")
    prior = strict_json(raw)
    if (prior["episode_id"] != PRIOR_EPISODE or prior["verdict"] != "INVALID"
            or prior["suite_sha256"] != SUITE_SHA256
            or prior["spending"]["total_upper_nano_usd"] != 937000):
        raise ValueError("prior trial identity or spending mismatch")
    return prior


def main():
    root = Path(__file__).resolve().parent.parent
    return run_cloud(repeat_of=read_prior(root / "results/2026-09-08/report.json"))


if __name__ == "__main__":
    raise SystemExit(main())

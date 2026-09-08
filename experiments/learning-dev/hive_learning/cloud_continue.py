"""Run one committed continuation under Billy's existing total allowance."""
import hashlib
import json
import os
from pathlib import Path
import re
import sys

from .cloud_trial import allowed_launch, main as run_cloud, SUITE_SHA256
from .evaluate import strict_json
from .spending import LIMIT_NUSD


def read_plan(root):
    plan = strict_json((root / "continuation-plan.json").read_bytes())
    if (set(plan) != {"attempt", "mode", "max_requests", "launch_parent", "launch_message",
                      "prior_report", "prior_report_sha256"}
            or type(plan["attempt"]) is not int or not 3 <= plan["attempt"] <= 20
            or plan["mode"] not in {"diagnose", "replay"}
            or plan["max_requests"] != (2 if plan["mode"] == "diagnose" else 325)
            or not re.fullmatch(r"[a-f0-9]{40}", plan["launch_parent"])
            or plan["launch_message"] != f"Run authorized Hive continuation {plan['attempt']}"
            or not re.fullmatch(r"results/[A-Za-z0-9-]+/report\.json", plan["prior_report"])
            or not re.fullmatch(r"[a-f0-9]{64}", plan["prior_report_sha256"])):
        raise ValueError("invalid continuation commitment")
    raw = (root / plan["prior_report"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != plan["prior_report_sha256"]:
        raise ValueError("prior cumulative spending report changed")
    prior = strict_json(raw)
    spent = prior["spending"]["total_upper_nano_usd"]
    if (prior["suite_sha256"] != SUITE_SHA256 or type(spent) is not int or not 0 <= spent <= LIMIT_NUSD
            or not re.fullmatch(r"[a-f0-9]{64}", prior["episode_id"])):
        raise ValueError("invalid prior episode or cumulative charge")
    return plan, prior


def main():
    root = Path(__file__).resolve().parent.parent
    plan, prior = read_plan(root)
    event = strict_json(Path(os.environ["GITHUB_EVENT_PATH"]).read_bytes())
    launch_env = {**os.environ, "HIVE_LAUNCH_PARENT": plan["launch_parent"]}
    if not allowed_launch(launch_env, event, plan["launch_message"]):
        os.environ.pop("OPENAI_API_KEY", None)
        print(json.dumps({"status": "LAUNCH_REFUSED", "model_requests": 0}))
        return 2
    if sys.argv[1:] == ["--check"]:
        print(json.dumps({"status": "COMMITMENT_VERIFIED", "attempt": plan["attempt"],
                          "prior_upper_nano_usd": prior["spending"]["total_upper_nano_usd"]}))
        return 0
    return run_cloud(repeat_of=prior, continuation=plan)


if __name__ == "__main__":
    raise SystemExit(main())

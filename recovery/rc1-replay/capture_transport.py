"""Capture exact synthetic would-be model requests. No provider is called."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from hive_canonical import diagnostics  # noqa: E402
from hive_canonical.controller import _protected_agent_call  # noqa: E402
from hive_canonical.legacy.workshop import hive, hive_review  # noqa: E402

SENTINEL = "SYNTHETIC_PROTECTED_SENTINEL_001C"
SCOPE = ("src/main/java/example/Widget.java",)


def capture() -> dict:
    raw = {"passed": False, "checks": [{"name": "frozen_junit_acceptance", "passed": False,
            "detail": {"tests": [{"class_name": SENTINEL, "tests": 3, "failures": 1,
                                  "errors": 0, "skipped": 0,
                                  "failure_diagnostics": [{"test_name": SENTINEL,
                                                           "message": SENTINEL}]}],
                       "stdout_tail": SENTINEL, "stderr_tail": SENTINEL,
                       "error": SENTINEL, "report_error": SENTINEL}}],
           "error": SENTINEL}
    run = {"request": "Change a public Widget value", "diff": "-value=1\n+value=2\n",
           "changed_files": list(SCOPE), "verification": raw,
           "targeted_verifications": [{"role": "backend", "result": raw}],
           "verified_stage_sha256": "a" * 64}
    context = diagnostics.SafeRunContext(SCOPE, 3)
    token = diagnostics.ACTIVE.set(context)
    try:
        correction = hive._targeted_repair_prompt(
            "backend", "public prior proposal", raw, SCOPE, ("public acceptance",),
            "change Widget", "public source bundle", original_task="public task",
            overall_objective="public objective", team_plan={"worker_files": {"backend": list(SCOPE)}},
        )
        review_context = hive_review.evidence(run)
        review = hive_review.prompt(review_context)
        repair = hive_review.prompt(review_context, repair_raw="malformed review JSON", error="parser error")
        seen = []
        async def fake_model(role, prompt):
            seen.append({"role": role, "prompt": str(prompt),
                         "response_schema": getattr(prompt, "response_schema", None)})
            return "{}"
        guarded = _protected_agent_call(fake_model, frozen_tests=True)
        async def invoke():
            await guarded("backend", correction)
            await guarded("reviewer", review)
            await guarded("reviewer", repair)
        asyncio.run(invoke())
        serial = json.dumps(seen, ensure_ascii=False)
        forbidden = (SENTINEL, SENTINEL.encode().hex(),
                     base64.b64encode(SENTINEL.encode()).decode())
        if SENTINEL not in json.dumps(raw) or any(token in serial for token in forbidden):
            raise ValueError("synthetic protected verifier text crossed model boundary")
        return {"classification": "QUALIFIED_FOR_BOUNDED_REPLAY",
                "model_calls": 0, "mock_calls": len(seen), "raw_audit_contains_sentinel": True,
                "model_requests_contain_sentinel": False,
                "raw_verifier_sha256": hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest(),
                "requests": seen}
    finally:
        diagnostics.ACTIVE.reset(token)


if __name__ == "__main__":
    output = ROOT / "recovery/rc1-replay/mock-transport.json"
    if output.exists():
        raise FileExistsError("refusing to overwrite prior diagnostic capture")
    value = capture()
    output.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({key: value[key] for key in ("classification", "model_calls", "mock_calls")}, sort_keys=True))

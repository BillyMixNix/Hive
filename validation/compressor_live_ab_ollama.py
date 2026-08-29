"""Run the live Raw-vs-Hive A/B with a local Ollama model.

This avoids requiring a cloud API secret in CI. It reuses the real failed
Compressor MVP CI log and the objective dependency-repair task from
`compressor_live_ab.py`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests

from compressor_live_ab import (
    EXPECTED_COMMAND,
    _events,
    _fetch_failed_ci_log,
    _prompt,
    _score,
)
from hive_compressor.coding_agent import adapt_coding_session


RESULT_PATH = Path("results/compressor_live_ab.json")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
MODEL = os.getenv("HIVE_AB_MODEL", "qwen2.5-coder:1.5b")


def _call_ollama(prompt: str) -> dict[str, Any]:
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL,
            "prompt": (
                "Solve the requested coding task from the supplied context. "
                "Do not explain your reasoning. Return only the requested JSON.\n\n"
                + prompt
            ),
            "stream": False,
            "options": {"temperature": 0, "num_predict": 160},
        },
        timeout=240,
    )
    response.raise_for_status()
    data = response.json()
    return {
        "provider": "ollama",
        "model": MODEL,
        "text": str(data.get("response") or ""),
        "input_tokens": int(data.get("prompt_eval_count") or 0),
        "output_tokens": int(data.get("eval_count") or 0),
    }


def main() -> int:
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ci_log, log_source = _fetch_failed_ci_log()
    events = _events(ci_log)
    adapted = adapt_coding_session(events)

    raw_history = json.dumps(events, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    hive_history = json.dumps(
        adapted["model_context"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )

    raw = _score(_call_ollama(_prompt("RAW", raw_history)))
    hive = _score(_call_ollama(_prompt("HIVE", hive_history)))

    raw_input = raw["input_tokens"]
    hive_input = hive["input_tokens"]
    saved = max(0, raw_input - hive_input)
    reduction = (saved / raw_input * 100.0) if raw_input else 0.0

    if raw["passed"] and hive["passed"]:
        status = "SUPPORTED_SINGLE_TASK"
    elif raw["passed"] and not hive["passed"]:
        status = "HIVE_REGRESSION"
    elif not raw["passed"] and hive["passed"]:
        status = "HIVE_ONLY_PASS_INCONCLUSIVE"
    else:
        status = "BOTH_FAILED_INCONCLUSIVE"

    result = {
        "benchmark": "compressor-live-ab-001-local",
        "task": "repair missing requests dependency after actual Compressor MVP CI failure",
        "expected_command": EXPECTED_COMMAND,
        "history_source": log_source,
        "status": status,
        "raw_context_bytes": len(raw_history.encode("utf-8")),
        "hive_context_bytes": len(hive_history.encode("utf-8")),
        "adapter_shadow": adapted["shadow"],
        "raw": raw,
        "hive": hive,
        "input_tokens_saved": saved,
        "input_token_reduction_percent": round(reduction, 2),
        "quality_equal": raw["passed"] == hive["passed"],
        "claim_scope": "one controlled live task on a small local coder model",
    }
    RESULT_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))

    return 1 if status == "HIVE_REGRESSION" else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Live Raw-vs-Hive coding benchmark.

Uses a real failure from the Compressor MVP CI run as the history source, then
asks the same model to solve the same next coding task from either:

1. RAW: the accumulated event history including the full CI log, or
2. HIVE: preserved latest human wording + structured machine state.

The task is objectively scored: repair the broken workflow dependency without
changing the test scope. This is intentionally a first controlled live A/B, not
an across-workload proof.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import requests

from hive_compressor.coding_agent import adapt_coding_session


FAILED_JOB_ID = 99136570796
EXPECTED_COMMAND = "python -m pip install pytest requests"
RESULT_PATH = Path("results/compressor_live_ab.json")


def _fetch_failed_ci_log() -> tuple[str, str]:
    """Fetch the actual failed Compressor MVP job log when available."""
    token = os.getenv("GITHUB_TOKEN", "")
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = f"https://api.github.com/repos/BillyMixNix/Hive/actions/jobs/{FAILED_JOB_ID}/logs"
    try:
        response = requests.get(url, headers=headers, timeout=30, allow_redirects=True)
        response.raise_for_status()
        text = response.text
        if "ModuleNotFoundError: No module named 'requests'" in text:
            return text, "github_actions_job_log"
    except Exception as exc:  # pragma: no cover - network fallback
        fallback_reason = f"github log fetch failed: {type(exc).__name__}: {exc}"
    else:
        fallback_reason = "github log fetched but expected failure marker was absent"

    excerpt = """Compressor MVP CI failed during pytest collection.
ImportError while loading conftest '/home/runner/work/Hive/Hive/tests/conftest.py'.
tests/conftest.py:1: in <module>
    import hive_llm
hive_llm.py:2: in <module>
    import requests
E   ModuleNotFoundError: No module named 'requests'
Process completed with exit code 4.
"""
    return excerpt, fallback_reason


def _events(ci_log: str) -> list[dict[str, Any]]:
    return [
        {
            "id": "human-build",
            "kind": "human_message",
            "effective_t": 1,
            "text": "Build the coding-agent adapter and put a focused CI gate around it.",
            "directives": [
                {
                    "kind": "goal",
                    "status": "active",
                    "effects": {"op": "build", "target": "coding-agent adapter + focused CI"},
                    "confidence": 1.0,
                }
            ],
        },
        {
            "id": "plan-ci",
            "kind": "plan",
            "effective_t": 2,
            "label": "Add lightweight Compressor MVP workflow",
            "state_effects": {
                "op": "plan",
                "target": ".github/workflows/compressor-ci.yml",
                "scope": "compressor-focused tests only",
            },
        },
        {
            "id": "workflow-change",
            "kind": "file_change",
            "effective_t": 3,
            "path": ".github/workflows/compressor-ci.yml",
            "change": "created",
            "state_effects": {
                "op": "file_change",
                "path": ".github/workflows/compressor-ci.yml",
                "install_command": "python -m pip install pytest",
                "test_scope": [
                    "tests/test_compressor_mvp.py",
                    "tests/test_source_preserving_adapter.py",
                    "tests/test_coding_agent_adapter.py",
                ],
            },
        },
        {
            "id": "ci-run",
            "kind": "tool_result",
            "effective_t": 4,
            "tool": "github_actions",
            "ok": False,
            "output": ci_log,
            "state_effects": {
                "op": "ci_result",
                "workflow": "Compressor MVP",
                "result": "failed_before_tests",
                "phase": "pytest_collection",
            },
        },
        {
            "id": "ci-failure",
            "kind": "failure",
            "effective_t": 5,
            "code": "missing_requests_dependency",
            "state_effects": {
                "op": "failure",
                "code": "missing_requests_dependency",
                "cause": "tests/conftest.py imports hive_llm.py which imports requests",
                "required_fix": "install requests in Compressor MVP workflow",
            },
        },
        {
            "id": "human-failed",
            "kind": "human_message",
            "effective_t": 6,
            "text": "No, it failed.",
            "directives": [
                {
                    "kind": "correction",
                    "status": "active",
                    "effects": {"op": "acknowledge_failure", "target": "Compressor MVP CI"},
                    "confidence": 1.0,
                }
            ],
        },
        {
            "id": "human-next",
            "kind": "human_message",
            "effective_t": 7,
            "text": "Fix only the missing dependency in the Compressor MVP workflow. Do not change the test scope.",
            "directives": [
                {
                    "kind": "task",
                    "status": "active",
                    "effects": {
                        "op": "fix_dependency",
                        "file": ".github/workflows/compressor-ci.yml",
                        "dependency": "requests",
                    },
                    "confidence": 1.0,
                },
                {
                    "kind": "constraint",
                    "status": "active",
                    "effects": {"op": "preserve", "target": "test_scope"},
                    "confidence": 1.0,
                },
            ],
        },
    ]


def _fixture() -> str:
    return """name: Compressor MVP
jobs:
  compressor-tests:
    steps:
      - name: Install test dependency
        run: python -m pip install pytest
      - name: Run compressor tests
        run: >-
          python -m pytest -q
          tests/test_compressor_mvp.py
          tests/test_source_preserving_adapter.py
          tests/test_coding_agent_adapter.py
"""


def _prompt(context_name: str, history_context: str) -> str:
    return f"""You are repairing a CI workflow after a real failed coding-agent run.

CONTEXT MODE: {context_name}

HISTORY CONTEXT:
{history_context}

CURRENT WORKFLOW:
```yaml
{_fixture()}
```

NEXT TASK:
Fix only the missing dependency that caused the shown failure. Do not change the test scope.

Return JSON only, exactly this shape:
{{"replacement_command":"..."}}

The replacement command must be the complete shell command that should replace the current install command.
"""


def _parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(stripped[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("model response was not a JSON object")
    return value


def _call_anthropic(prompt: str) -> dict[str, Any]:
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured in GitHub Actions secrets")

    import anthropic

    model = os.getenv("HIVE_AB_MODEL", "claude-sonnet-4-6")
    client = anthropic.Anthropic(api_key=api_key, timeout=90.0)
    response = client.messages.create(
        model=model,
        max_tokens=160,
        temperature=0,
        system=(
            "Solve the requested coding task from the supplied context. "
            "Do not explain your reasoning. Return only the requested JSON."
        ),
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(block.text for block in response.content if hasattr(block, "text"))
    usage = response.usage
    return {
        "provider": "anthropic",
        "model": model,
        "text": text,
        "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
    }


def _score(call: dict[str, Any]) -> dict[str, Any]:
    try:
        parsed = _parse_json_object(call["text"])
        command = str(parsed.get("replacement_command") or "").strip()
        passed = command == EXPECTED_COMMAND
        error = None
    except Exception as exc:
        command = ""
        passed = False
        error = f"{type(exc).__name__}: {exc}"
    return {
        **call,
        "parsed_command": command,
        "passed": passed,
        "parse_error": error,
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

    base_result: dict[str, Any] = {
        "benchmark": "compressor-live-ab-001",
        "task": "repair missing requests dependency after actual Compressor MVP CI failure",
        "expected_command": EXPECTED_COMMAND,
        "history_source": log_source,
        "adapter_shadow": adapted["shadow"],
        "raw_context_bytes": len(raw_history.encode("utf-8")),
        "hive_context_bytes": len(hive_history.encode("utf-8")),
    }

    if not os.getenv("ANTHROPIC_API_KEY"):
        base_result.update(
            {
                "status": "BLOCKED_MISSING_MODEL_CREDENTIAL",
                "detail": "ANTHROPIC_API_KEY is not configured in GitHub Actions secrets",
            }
        )
        RESULT_PATH.write_text(json.dumps(base_result, indent=2), encoding="utf-8")
        print(json.dumps(base_result, indent=2))
        return 2

    raw = _score(_call_anthropic(_prompt("RAW", raw_history)))
    hive = _score(_call_anthropic(_prompt("HIVE", hive_history)))

    raw_input = raw["input_tokens"]
    hive_input = hive["input_tokens"]
    token_saved = max(0, raw_input - hive_input)
    token_reduction = (token_saved / raw_input * 100.0) if raw_input else 0.0

    if raw["passed"] and hive["passed"]:
        status = "SUPPORTED_SINGLE_TASK"
    elif raw["passed"] and not hive["passed"]:
        status = "HIVE_REGRESSION"
    elif not raw["passed"] and hive["passed"]:
        status = "HIVE_ONLY_PASS_INCONCLUSIVE"
    else:
        status = "BOTH_FAILED_INCONCLUSIVE"

    result = {
        **base_result,
        "status": status,
        "raw": raw,
        "hive": hive,
        "input_tokens_saved": token_saved,
        "input_token_reduction_percent": round(token_reduction, 2),
        "quality_equal": raw["passed"] == hive["passed"],
    }
    RESULT_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))

    return 1 if status == "HIVE_REGRESSION" else 0


if __name__ == "__main__":
    sys.exit(main())

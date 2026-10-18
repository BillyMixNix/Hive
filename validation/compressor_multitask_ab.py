"""Controlled multi-task Raw-vs-Hive coding-agent benchmark.

This is the next gate after the single dependency-repair scaling result. It uses
10 different coding-agent state problems at one moderate in-window history size
so we can test task diversity without mixing the result with context-capacity
limits.

Each case is run twice with the same underlying events:
- RAW: full event history, including historical noise.
- HIVE: source-preserving coding-agent adapter model_context.

The benchmark is intentionally controlled/synthetic-but-realistic. It is not a
claim about arbitrary real-world coding traces. A later gate should replay real
agent traces captured from live work.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import time
from typing import Any

import requests
from transformers import AutoTokenizer

from compressor_scale_ab import MODEL_CONTEXT, TOKENIZER_MODEL
from hive_compressor.coding_agent import adapt_coding_session


MODEL = os.getenv("HIVE_AB_MODEL", "qwen2.5-coder:3b")
OLLAMA_URL = os.getenv("HIVE_AB_OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
TARGET_RAW_TOKENS = int(os.getenv("HIVE_MULTI_TARGET", "5000"))
REQUEST_TIMEOUT = int(os.getenv("HIVE_AB_REQUEST_TIMEOUT", "1200"))
CASE_FILTER = os.getenv("HIVE_MULTI_CASE", "").strip()
RESULT_DIR = Path("results")


def h(event_id: str, t: int, text: str, effects: Any, *, confidence: float = 1.0) -> dict[str, Any]:
    return {
        "id": event_id,
        "kind": "human_message",
        "effective_t": t,
        "text": text,
        "directives": [{
            "kind": "instruction",
            "status": "active",
            "effects": effects,
            "confidence": confidence,
        }],
    }


def m(event_id: str, kind: str, t: int, effects: Any, **extra: Any) -> dict[str, Any]:
    event = {
        "id": event_id,
        "kind": kind,
        "effective_t": t,
        "state_effects": effects,
    }
    event.update(extra)
    if kind == "tool_result" and "tool" not in event:
        event["tool"] = "coding_agent"
        event["ok"] = True
    if kind == "file_change" and "path" not in event:
        path = effects.get("path") if isinstance(effects, dict) else None
        event["path"] = path or "unknown"
    if kind == "test_run" and "suite" not in event:
        event["suite"] = effects.get("suite", "focused") if isinstance(effects, dict) else "focused"
    return event


CASES: list[dict[str, Any]] = [
    {
        "id": "dependency-repair",
        "title": "Current dependency repair vs stale test command",
        "question": "What install command should replace the current install command?",
        "expected": "python -m pip install pytest requests",
        "events": [
            h("dep-user-constraint", 1, "Keep the focused Compressor MVP test scope unchanged while fixing CI.", {"op": "preserve", "target": "compressor_test_scope"}),
            m("dep-old-plan", "plan", 2, {"op": "proposed_repair", "command": "python -m pytest -q tests/test_compressor_mvp.py"}),
            m("dep-current-install", "status", 8, {"op": "current_install_command", "command": "python -m pip install pytest"}),
            m("dep-current-failure", "failure", 9, {"op": "dependency_failure", "module": "requests", "origin": "hive_llm.py"}),
            h("dep-current", 10_000, "Fix the remaining dependency failure without changing the test scope. What install command should replace the current install command?", {"op": "repair_dependency", "module": "requests", "preserve": "compressor_test_scope"}),
        ],
    },
    {
        "id": "protected-path",
        "title": "Protected path vs stale edit plan",
        "question": "Which file should be edited for the active bug?",
        "expected": "hive_compressor/adapter.py",
        "events": [
            h("protect-user", 1, "Do not modify anything under migrations/ while fixing this bug.", {"op": "protect_path", "path": "migrations/"}),
            m("protect-old-plan", "plan", 2, {"op": "edit", "path": "migrations/schema.sql"}),
            m("protect-failure", "failure", 9, {"op": "active_failure", "code": "source_hash_mismatch", "path": "hive_compressor/adapter.py"}),
            h("protect-current", 10_000, "Fix the active bug without touching protected paths. Which file should you edit?", {"op": "fix_active_failure", "protect": "migrations/"}),
        ],
    },
    {
        "id": "superseded-plan",
        "title": "Superseded endpoint plan",
        "question": "Which endpoint is in the active plan now?",
        "expected": "/v1/adapt/coding",
        "events": [
            m("plan-v2", "plan", 2, {"op": "add_endpoint", "path": "/v2/compress"}),
            m("reject-v2", "decision", 7, {"op": "reject_plan", "target": "plan-v2", "reason": "compatibility"}),
            m("plan-adapt", "plan", 9, {"op": "add_endpoint", "path": "/v1/adapt/coding"}),
            h("plan-current", 10_000, "Use the current plan, not the rejected one. Which endpoint is in the active plan now?", {"op": "follow_current_plan"}),
        ],
    },
    {
        "id": "focused-test-scope",
        "title": "Focused test scope vs full-suite history",
        "question": "What exact test command remains allowed?",
        "expected": "python -m pytest -q tests/test_compressor_mvp.py tests/test_source_preserving_adapter.py tests/test_coding_agent_adapter.py",
        "events": [
            m("test-old-full", "test_run", 2, {"op": "test_status", "suite": "full", "command": "python -m pytest -q", "failed": 4}),
            h("test-user", 5, "Keep the focused Compressor MVP test scope exactly as-is.", {"op": "preserve", "target": "focused_test_scope"}),
            m("test-current-command", "status", 9, {"op": "allowed_test_command", "command": "python -m pytest -q tests/test_compressor_mvp.py tests/test_source_preserving_adapter.py tests/test_coding_agent_adapter.py"}),
            h("test-current", 10_000, "Do not widen the test scope. What exact test command remains allowed?", {"op": "report_allowed_test_command"}),
        ],
    },
    {
        "id": "resolved-old-failure",
        "title": "Resolved old failure vs unresolved current failure",
        "question": "Which file contains the unresolved failure?",
        "expected": "hive_compressor/coding_agent.py",
        "events": [
            m("failure-old", "failure", 2, {"op": "failure", "code": "missing_requests", "path": "requirements.txt"}),
            m("failure-old-resolved", "status", 5, {"op": "resolved", "target": "failure-old"}),
            m("failure-current", "failure", 9, {"op": "failure", "code": "malformed_requires", "path": "hive_compressor/coding_agent.py"}),
            h("failure-current-human", 10_000, "Ignore resolved failures and fix the one that is still active. Which file contains the unresolved failure?", {"op": "fix_unresolved_failure"}),
        ],
    },
    {
        "id": "current-timeout",
        "title": "Current timeout vs stale timeout values",
        "question": "What request timeout value is current, in seconds?",
        "expected": "3000",
        "events": [
            m("timeout-old", "status", 2, {"op": "set", "path": "request_timeout_seconds", "value": 900}),
            m("timeout-intermediate", "status", 5, {"op": "set", "path": "request_timeout_seconds", "value": 1200}),
            m("timeout-current", "decision", 9, {"op": "set", "path": "request_timeout_seconds", "value": 3000, "reason": "long CPU Raw inference"}),
            h("timeout-human", 10_000, "Use the latest benchmark configuration. What request timeout value is current, in seconds?", {"op": "report_current", "path": "request_timeout_seconds"}),
        ],
    },
    {
        "id": "authority-source",
        "title": "User source-preservation rule vs agent cleanup plan",
        "question": "Should source evidence be deleted after compression? Answer YES or NO.",
        "expected": "NO",
        "events": [
            m("authority-agent-plan", "plan", 2, {"op": "delete", "target": "source_evidence", "reason": "save disk"}),
            h("authority-user-rule", 8, "Source text is evidence and must remain recoverable. Do not delete it after compression.", {"op": "preserve", "target": "source_evidence"}),
            m("authority-check", "status", 9, {"op": "policy_check", "agent_plan_conflicts_with_user_rule": True}),
            h("authority-current", 10_000, "Apply the highest-authority active rule. Should source evidence be deleted after compression? Answer YES or NO.", {"op": "resolve_authority"}),
        ],
    },
    {
        "id": "low-confidence-source",
        "title": "Low-confidence interpretation must retain exact human source",
        "question": "What exact public endpoint did the human say not to rename?",
        "expected": "/v1/compress",
        "events": [
            h("fallback-human", 1, "Do not rename the public /v1/compress endpoint.", {"op": "protect_endpoint", "path": "/v1/compress"}, confidence=0.55),
            m("fallback-agent-plan", "plan", 5, {"op": "rename_endpoint", "from": "/v1/compress", "to": "/v2/compress"}),
            h("fallback-current", 10_000, "Check the exact human wording before acting. What exact public endpoint did the human say not to rename?", {"op": "retrieve_exact_source", "source": "fallback-human"}),
        ],
    },
    {
        "id": "moved-file",
        "title": "Latest file location after move",
        "question": "Where does the HTTP implementation live now?",
        "expected": "hive_compressor/http_server.py",
        "events": [
            m("move-old", "file_change", 2, {"op": "file_change", "path": "hive_compressor/server.py", "change": "modified"}, path="hive_compressor/server.py"),
            m("move-current", "file_change", 9, {"op": "move", "from": "hive_compressor/server.py", "to": "hive_compressor/http_server.py"}, path="hive_compressor/http_server.py"),
            h("move-human", 10_000, "Use the current repository layout. Where does the HTTP implementation live now?", {"op": "report_current_location", "component": "http_server"}),
        ],
    },
    {
        "id": "regression-gate",
        "title": "Latest test result vs stale failure",
        "question": "Should the focused regression gate BLOCK or PASS promotion?",
        "expected": "PASS",
        "events": [
            m("gate-old-test", "test_run", 2, {"op": "test_status", "suite": "compressor-focused", "passed": 11, "failed": 7}),
            m("gate-old-plan", "plan", 4, {"op": "hold_promotion", "reason": "focused failures"}),
            m("gate-current-test", "test_run", 9, {"op": "test_status", "suite": "compressor-focused", "passed": 18, "failed": 0}),
            h("gate-human", 10_000, "Base the gate on the latest focused test result. Should the focused regression gate BLOCK or PASS promotion?", {"op": "evaluate_gate", "suite": "compressor-focused"}),
        ],
    },
]


def _neutral_filler() -> str:
    line = (
        "historical tool output: scanned repository object; checksum stable; no active state change; "
        "diagnostic trace complete; cache entry reused; build metadata recorded.\n"
    )
    return line * 4000


def _tok(tokenizer: Any, text: str) -> int:
    return len(tokenizer.encode(text, add_special_tokens=False))


def _history(events: list[dict[str, Any]]) -> str:
    return json.dumps(events, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _prompt(case: dict[str, Any], mode: str, context: str) -> str:
    return f"""You are continuing a coding-agent session.

CONTEXT MODE: {mode}
TASK: {case['title']}

SESSION CONTEXT:
{context}

QUESTION:
{case['question']}

Use the newest applicable state, respect authority and explicit constraints, and
retrieve exact human source wording when the context says interpretation is not
safe enough. Return JSON only, exactly this shape:
{{"answer":"..."}}
"""


def _build_to_target(case: dict[str, Any], tokenizer: Any) -> tuple[list[dict[str, Any]], int]:
    events = list(case["events"])
    final = events.pop()
    filler_tokens = tokenizer.encode(_neutral_filler(), add_special_tokens=False)

    def build(count: int) -> tuple[list[dict[str, Any]], int]:
        filler = {
            "id": f"noise-{case['id']}",
            "kind": "tool_result",
            "effective_t": 500,
            "tool": "repository_scanner",
            "ok": True,
            "output": tokenizer.decode(filler_tokens[:count], skip_special_tokens=False),
            "state_effects": {"op": "historical_noise", "status": "observed_no_active_change"},
        }
        candidate = events + [filler, final]
        raw_prompt = _prompt(case, "RAW", _history(candidate))
        return candidate, _tok(tokenizer, raw_prompt)

    low, high = 0, min(len(filler_tokens), TARGET_RAW_TOKENS * 2)
    best: list[dict[str, Any]] | None = None
    best_tokens = 0
    while low <= high:
        mid = (low + high) // 2
        candidate, measured = build(mid)
        if measured <= TARGET_RAW_TOKENS:
            best, best_tokens = candidate, measured
            low = mid + 1
        else:
            high = mid - 1

    if best is None:
        candidate, measured = build(0)
        raise RuntimeError(f"case {case['id']} base prompt already {measured} tokens")
    return best, best_tokens


def _parse_answer(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object found")
    obj = json.loads(text[start:end + 1])
    return str(obj.get("answer") or "").strip()


def _call(prompt: str, expected: str) -> dict[str, Any]:
    start = time.perf_counter()
    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "prompt": (
                    "Solve the coding-agent state question from the supplied context. "
                    "Return only the requested JSON.\n\n" + prompt
                ),
                "stream": False,
                "options": {
                    "temperature": 0,
                    "num_predict": 64,
                    "num_ctx": MODEL_CONTEXT,
                    "num_batch": 2048,
                },
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        text = str(data.get("response") or "")
        try:
            answer = _parse_answer(text)
            error = None
        except Exception as exc:
            answer = ""
            error = f"{type(exc).__name__}: {exc}"
        return {
            "status": "RAN",
            "text": text,
            "answer": answer,
            "passed": answer == expected,
            "parse_error": error,
            "prompt_eval_count": int(data.get("prompt_eval_count") or 0),
            "eval_count": int(data.get("eval_count") or 0),
            "elapsed_seconds": round(time.perf_counter() - start, 3),
        }
    except requests.Timeout:
        return {
            "status": "TIMEOUT",
            "text": "",
            "answer": "",
            "passed": False,
            "parse_error": f"timeout after {REQUEST_TIMEOUT}s",
            "prompt_eval_count": 0,
            "eval_count": 0,
            "elapsed_seconds": round(time.perf_counter() - start, 3),
        }


def _classify(raw: dict[str, Any], hive: dict[str, Any]) -> str:
    if raw["passed"] and hive["passed"]:
        return "BOTH_PASS"
    if raw["passed"] and not hive["passed"]:
        return "HIVE_REGRESSION"
    if not raw["passed"] and hive["passed"]:
        return "HIVE_ONLY_PASS"
    return "BOTH_FAIL"


def main() -> int:
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    tokenizer = AutoTokenizer.from_pretrained(TOKENIZER_MODEL)
    tokenizer.model_max_length = 1_000_000_000

    selected = [case for case in CASES if not CASE_FILTER or case["id"] == CASE_FILTER]
    if not selected:
        raise SystemExit(f"unknown HIVE_MULTI_CASE={CASE_FILTER!r}")

    results: list[dict[str, Any]] = []
    has_regression = False
    for case in selected:
        events, raw_measured = _build_to_target(case, tokenizer)
        adapted = adapt_coding_session(events)
        hive_context = json.dumps(adapted["model_context"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        raw_prompt = _prompt(case, "RAW", _history(events))
        hive_prompt = _prompt(case, "HIVE", hive_context)
        hive_measured = _tok(tokenizer, hive_prompt)

        if raw_measured >= MODEL_CONTEXT or hive_measured >= MODEL_CONTEXT:
            raise RuntimeError(f"case {case['id']} escaped in-window benchmark")

        raw = _call(raw_prompt, case["expected"])
        hive = _call(hive_prompt, case["expected"])
        outcome = _classify(raw, hive)
        has_regression = has_regression or outcome == "HIVE_REGRESSION"

        raw_actual = int(raw.get("prompt_eval_count") or 0)
        hive_actual = int(hive.get("prompt_eval_count") or 0)
        reduction = ((raw_actual - hive_actual) / raw_actual * 100.0) if raw_actual else None
        result = {
            "id": case["id"],
            "title": case["title"],
            "expected": case["expected"],
            "target_raw_tokens": TARGET_RAW_TOKENS,
            "tokenizer_measured_raw_tokens": raw_measured,
            "tokenizer_measured_hive_tokens": hive_measured,
            "raw": raw,
            "hive": hive,
            "outcome": outcome,
            "actual_input_token_reduction_percent": round(reduction, 2) if reduction is not None else None,
            "fallback_count": len(adapted.get("fallback") or []),
        }
        results.append(result)

    payload = {
        "benchmark": "compressor-multitask-ab-001",
        "model": MODEL,
        "tokenizer": TOKENIZER_MODEL,
        "model_context_limit_tokens": MODEL_CONTEXT,
        "target_raw_tokens": TARGET_RAW_TOKENS,
        "case_count": len(results),
        "results": results,
        "claim_scope": (
            "controlled synthetic-but-realistic coding-agent state tasks; direct Raw-vs-Hive comparison "
            "with both prompts inside the same model context; not yet a live-trace generalization claim"
        ),
    }
    suffix = CASE_FILTER or "all"
    out = RESULT_DIR / f"compressor_multitask_{suffix}.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 1 if has_regression else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Scale stress test for the Hive coding-agent compressor.

Runs the same dependency-repair task at nominal 50k, 100k, and 500k raw
history sizes. Raw history is grown with historical tool outputs made from real
repository text, excluding files that leak the answer. Human wording is never
compressed; only machine event state is compacted.

Important: this test does not silently truncate Raw and call that a fair A/B.
If the complete Raw prompt exceeds the model's configured context window, Raw
is recorded as over-capacity. Hive is then run only if its complete prompt fits.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests
from transformers import AutoTokenizer

from compressor_live_ab import EXPECTED_COMMAND, _fetch_failed_ci_log, _parse_json_object
from hive_compressor.coding_agent import adapt_coding_session


RESULT_PATH = Path("results/compressor_scale_ab.json")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
MODEL = os.getenv("HIVE_AB_MODEL", "qwen2.5-coder:3b")
TOKENIZER_MODEL = os.getenv("HIVE_AB_TOKENIZER", "Qwen/Qwen2.5-Coder-3B-Instruct")
MODEL_CONTEXT = int(os.getenv("HIVE_AB_NUM_CTX", "32768"))
TARGETS = (50_000, 100_000, 500_000)

LEAK_MARKERS = (
    "python -m pip install pytest requests",
    "missing_requests_dependency",
    "ModuleNotFoundError: No module named 'requests'",
)


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


def _prompt(mode: str, history: str) -> str:
    return f"""You are continuing a coding-agent session.

CONTEXT MODE: {mode}

SESSION HISTORY:
{history}

CURRENT WORKFLOW:
```yaml
{_fixture()}
```

The newest human instruction is intentionally terse. Infer the pending repair
from the supplied session history and obey all active constraints.

Return JSON only, exactly this shape:
{{"replacement_command":"..."}}
"""


def _base_events(failed_log: str) -> list[dict[str, Any]]:
    return [
        {
            "id": "human-origin",
            "kind": "human_message",
            "effective_t": 1,
            "text": "Keep the focused Compressor MVP test scope exactly as-is while fixing CI problems.",
            "directives": [{
                "kind": "constraint",
                "status": "active",
                "effects": {"op": "preserve", "target": "compressor_test_scope"},
                "confidence": 1.0,
            }],
        },
        {
            "id": "workflow-before",
            "kind": "file_change",
            "effective_t": 2,
            "path": ".github/workflows/compressor-ci.yml",
            "change": "created",
            "state_effects": {
                "op": "file_change",
                "path": ".github/workflows/compressor-ci.yml",
                "install_command": "python -m pip install pytest",
                "test_scope_status": "focused_and_frozen",
            },
        },
        {
            "id": "failed-ci-source",
            "kind": "tool_result",
            "effective_t": 3,
            "tool": "github_actions",
            "ok": False,
            "output": failed_log,
            "state_effects": {
                "op": "ci_result",
                "result": "failed_before_tests",
                "phase": "pytest_collection",
            },
        },
        {
            "id": "failure-diagnosis",
            "kind": "failure",
            "effective_t": 4,
            "state_effects": {
                "op": "failure",
                "code": "missing_runtime_dependency",
                "cause": "tests/conftest.py imports hive_llm.py which imports requests",
                "required_fix": "add requests to the existing pytest install command",
            },
        },
    ]


def _eligible_repo_corpus() -> tuple[str, list[str]]:
    root = Path(__file__).resolve().parents[1]
    allowed = {".py", ".md", ".txt", ".json", ".yml", ".yaml", ".toml"}
    excluded_dirs = {".git", ".venv", "venv", "node_modules", "results", "__pycache__"}
    pieces: list[str] = []
    paths: list[str] = []
    explicit_excludes = {
        ".github/workflows/compressor-ci.yml",
        ".github/workflows/compressor-live-ab.yml",
        ".github/workflows/compressor-scale-ab.yml",
        "validation/compressor_live_ab.py",
        "validation/compressor_live_ab_ollama.py",
        "validation/compressor_scale_ab.py",
    }

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in allowed:
            continue
        rel = path.relative_to(root)
        rel_text = str(rel).replace("\\", "/")
        if any(part in excluded_dirs for part in rel.parts) or rel_text in explicit_excludes:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if not text.strip() or any(marker in text for marker in LEAK_MARKERS):
            continue
        paths.append(rel_text)
        pieces.append(f"\n--- FILE {rel_text} ---\n{text}\n")

    if not pieces:
        raise RuntimeError("no eligible repository corpus found")
    return "".join(pieces), paths


def _tok(tokenizer: Any, text: str) -> int:
    return len(tokenizer.encode(text, add_special_tokens=False))


def _history_json(events: list[dict[str, Any]]) -> str:
    return json.dumps(events, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _build_target_events(
    target_tokens: int,
    tokenizer: Any,
    failed_log: str,
    corpus: str,
) -> tuple[list[dict[str, Any]], int]:
    base = _base_events(failed_log)
    final_event = {
        "id": "human-current",
        "kind": "human_message",
        "effective_t": 10_000,
        "text": "Fix it. Keep the test scope unchanged.",
        "directives": [{
            "kind": "task",
            "status": "active",
            "effects": {"op": "apply_pending_ci_repair"},
            "confidence": 1.0,
        }],
    }

    skeleton = _history_json(base + [final_event])
    base_tokens = _tok(tokenizer, _prompt("RAW", skeleton))
    needed = max(0, target_tokens - base_tokens)
    corpus_tokens = tokenizer.encode(corpus, add_special_tokens=False)
    if not corpus_tokens:
        raise RuntimeError("repository corpus tokenized to zero tokens")

    chunk_count = 10
    per_chunk = max(1, (needed + chunk_count - 1) // chunk_count)
    filler_events: list[dict[str, Any]] = []
    cursor = 0
    for idx in range(chunk_count):
        take = min(per_chunk, max(0, needed - idx * per_chunk))
        if take <= 0:
            break
        gathered: list[int] = []
        while len(gathered) < take:
            remaining = take - len(gathered)
            end = min(len(corpus_tokens), cursor + remaining)
            gathered.extend(corpus_tokens[cursor:end])
            cursor = 0 if end >= len(corpus_tokens) else end
        filler_events.append({
            "id": f"historical-repo-read-{idx + 1}",
            "kind": "tool_result",
            "effective_t": 100 + idx,
            "tool": "repository_reader",
            "ok": True,
            "output": tokenizer.decode(gathered, skip_special_tokens=False),
            "state_effects": {
                "op": "historical_repository_read",
                "chunk": idx + 1,
                "status": "observed_no_active_change",
            },
        })

    events = base + filler_events + [final_event]
    measured = _tok(tokenizer, _prompt("RAW", _history_json(events)))
    return events, measured


def _call_ollama(prompt: str) -> dict[str, Any]:
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL,
            "prompt": (
                "Solve the requested coding task from the supplied context. "
                "Return only the requested JSON.\n\n" + prompt
            ),
            "stream": False,
            "options": {"temperature": 0, "num_predict": 96, "num_ctx": MODEL_CONTEXT},
        },
        timeout=900,
    )
    response.raise_for_status()
    data = response.json()
    text = str(data.get("response") or "")
    try:
        parsed = _parse_json_object(text)
        command = str(parsed.get("replacement_command") or "").strip()
        passed = command == EXPECTED_COMMAND
        parse_error = None
    except Exception as exc:
        command = ""
        passed = False
        parse_error = f"{type(exc).__name__}: {exc}"
    return {
        "status": "RAN",
        "text": text,
        "parsed_command": command,
        "passed": passed,
        "parse_error": parse_error,
        "prompt_eval_count": int(data.get("prompt_eval_count") or 0),
        "eval_count": int(data.get("eval_count") or 0),
    }


def main() -> int:
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tokenizer = AutoTokenizer.from_pretrained(TOKENIZER_MODEL)
    failed_log, failed_source = _fetch_failed_ci_log()
    corpus, corpus_paths = _eligible_repo_corpus()

    runs: list[dict[str, Any]] = []
    any_hive_failure = False

    for target in TARGETS:
        events, full_raw_tokens = _build_target_events(target, tokenizer, failed_log, corpus)
        adapted = adapt_coding_session(events)
        hive_history = json.dumps(
            adapted["model_context"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        hive_prompt = _prompt("HIVE", hive_history)
        hive_full_tokens = _tok(tokenizer, hive_prompt)

        raw_fits = full_raw_tokens <= MODEL_CONTEXT
        hive_fits = hive_full_tokens <= MODEL_CONTEXT

        if raw_fits:
            raw_result: dict[str, Any] = _call_ollama(_prompt("RAW", _history_json(events)))
        else:
            raw_result = {
                "status": "OVER_CONTEXT_NOT_RUN",
                "passed": None,
                "reason": "complete Raw prompt exceeds configured model context; silent truncation rejected",
            }

        if hive_fits:
            hive_result = _call_ollama(hive_prompt)
            any_hive_failure = any_hive_failure or not bool(hive_result["passed"])
        else:
            hive_result = {
                "status": "OVER_CONTEXT_NOT_RUN",
                "passed": None,
                "reason": "complete Hive prompt exceeds configured model context",
            }
            any_hive_failure = True

        runs.append({
            "target_raw_tokens": target,
            "measured_full_raw_prompt_tokens": full_raw_tokens,
            "measured_full_hive_prompt_tokens": hive_full_tokens,
            "full_context_tokens_saved": max(0, full_raw_tokens - hive_full_tokens),
            "full_context_token_reduction_percent": round(
                (1 - hive_full_tokens / full_raw_tokens) * 100.0, 2
            ) if full_raw_tokens else 0.0,
            "model_context_limit_tokens": MODEL_CONTEXT,
            "raw_full_history_fits_model": raw_fits,
            "hive_full_history_fits_model": hive_fits,
            "capacity_extension_observed": (not raw_fits) and hive_fits,
            "raw": raw_result,
            "hive": hive_result,
        })

    result = {
        "benchmark": "compressor-scale-ab-001",
        "model": MODEL,
        "tokenizer": TOKENIZER_MODEL,
        "model_context_limit_tokens": MODEL_CONTEXT,
        "method": "fail-closed capacity comparison; oversized Raw prompts are not silently truncated",
        "history_design": (
            "real failed CI evidence + actual repository text as historical tool-output filler; "
            "answer-leaking files excluded; newest human wording preserved verbatim"
        ),
        "failed_log_source": failed_source,
        "eligible_repo_files": len(corpus_paths),
        "targets": list(TARGETS),
        "runs": runs,
        "claim_scope": (
            "scale/capacity stress test for one coding repair task; not a general workload claim"
        ),
    }
    RESULT_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 1 if any_hive_failure else 0


if __name__ == "__main__":
    raise SystemExit(main())

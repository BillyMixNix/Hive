"""Fair in-window Raw-vs-Hive scaling benchmark.

Runs the same coding repair task at 8k, 16k, 24k, and 30k raw prompt sizes.
Both Raw and Hive must fit inside the same 32,768-token model context, so every
point is a direct quality + measured-token comparison rather than a capacity-only
comparison.

History growth uses real Hive repository text as historical tool output while
excluding files that leak the expected answer. Human wording remains verbatim.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from transformers import AutoTokenizer

from compressor_live_ab import _fetch_failed_ci_log
from compressor_scale_ab import (
    MODEL_CONTEXT,
    TOKENIZER_MODEL,
    _base_events,
    _call_ollama,
    _eligible_repo_corpus,
    _history_json,
    _prompt,
    _tok,
)
from hive_compressor.coding_agent import adapt_coding_session


DEFAULT_TARGETS = (8_000, 16_000, 24_000, 30_000)
MAX_SAFE_PROMPT = 31_500


def _targets() -> tuple[int, ...]:
    one = os.getenv("HIVE_AB_TARGET", "").strip()
    if one:
        return (int(one),)
    return DEFAULT_TARGETS


def _result_path() -> Path:
    return Path(os.getenv("HIVE_AB_RESULT_PATH", "results/compressor_inwindow_ab.json"))


def _failure_excerpt(log: str) -> str:
    """Keep the real failure neighborhood without dragging the whole CI install log in."""
    marker = "ModuleNotFoundError: No module named 'requests'"
    idx = log.find(marker)
    if idx < 0:
        return log[-4_000:]
    start = max(0, idx - 1_800)
    end = min(len(log), idx + 800)
    return log[start:end]


def _final_event() -> dict[str, Any]:
    return {
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


def _filler_event(text: str) -> dict[str, Any]:
    return {
        "id": "historical-repo-read",
        "kind": "tool_result",
        "effective_t": 100,
        "tool": "repository_reader",
        "ok": True,
        "output": text,
        "state_effects": {
            "op": "historical_repository_read",
            "status": "observed_no_active_change",
        },
    }


def _build_near_target(
    target_tokens: int,
    tokenizer: Any,
    failed_log: str,
    corpus: str,
) -> tuple[list[dict[str, Any]], int]:
    """Build the largest prompt not exceeding the requested token target."""
    base = _base_events(_failure_excerpt(failed_log))
    final = _final_event()
    corpus_tokens = tokenizer.encode(corpus[:400_000], add_special_tokens=False)
    if not corpus_tokens:
        raise RuntimeError("repository corpus tokenized to zero tokens")

    if len(corpus_tokens) < target_tokens:
        repeats = (target_tokens // len(corpus_tokens)) + 2
        corpus_tokens = (corpus_tokens * repeats)[: target_tokens * 2]

    def build_with(count: int) -> tuple[list[dict[str, Any]], int]:
        filler_text = tokenizer.decode(corpus_tokens[:count], skip_special_tokens=False)
        events = base + [_filler_event(filler_text), final]
        measured = _tok(tokenizer, _prompt("RAW", _history_json(events)))
        return events, measured

    low = 0
    high = min(len(corpus_tokens), target_tokens)
    best_events: list[dict[str, Any]] | None = None
    best_tokens = 0

    while low <= high:
        mid = (low + high) // 2
        events, measured = build_with(mid)
        if measured <= target_tokens:
            best_events = events
            best_tokens = measured
            low = mid + 1
        else:
            high = mid - 1

    if best_events is None:
        _, empty_tokens = build_with(0)
        raise RuntimeError(
            f"base prompt is already {empty_tokens} tokens, above target {target_tokens}"
        )
    return best_events, best_tokens


def _classify(raw_pass: bool, hive_pass: bool) -> str:
    if raw_pass and hive_pass:
        return "BOTH_PASS"
    if raw_pass and not hive_pass:
        return "HIVE_REGRESSION"
    if not raw_pass and hive_pass:
        return "HIVE_ONLY_PASS"
    return "BOTH_FAIL"


def main() -> int:
    result_path = _result_path()
    result_path.parent.mkdir(parents=True, exist_ok=True)
    tokenizer = AutoTokenizer.from_pretrained(TOKENIZER_MODEL)
    tokenizer.model_max_length = 1_000_000_000
    failed_log, failed_source = _fetch_failed_ci_log()
    corpus, corpus_paths = _eligible_repo_corpus()
    targets = _targets()

    runs: list[dict[str, Any]] = []
    hive_regression = False

    for target in targets:
        events, measured_raw = _build_near_target(target, tokenizer, failed_log, corpus)
        raw_history = _history_json(events)
        adapted = adapt_coding_session(events)
        hive_history = json.dumps(
            adapted["model_context"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        raw_prompt = _prompt("RAW", raw_history)
        hive_prompt = _prompt("HIVE", hive_history)
        measured_hive = _tok(tokenizer, hive_prompt)

        if measured_raw > MAX_SAFE_PROMPT:
            raise RuntimeError(
                f"raw prompt {measured_raw} exceeds safe in-window ceiling {MAX_SAFE_PROMPT}"
            )
        if measured_raw >= MODEL_CONTEXT or measured_hive >= MODEL_CONTEXT:
            raise RuntimeError("in-window benchmark produced an over-context prompt")

        raw = _call_ollama(raw_prompt)
        hive = _call_ollama(hive_prompt)
        status = _classify(bool(raw["passed"]), bool(hive["passed"]))
        hive_regression = hive_regression or status == "HIVE_REGRESSION"

        raw_actual = int(raw.get("prompt_eval_count") or 0)
        hive_actual = int(hive.get("prompt_eval_count") or 0)
        actual_saved = max(0, raw_actual - hive_actual)
        actual_reduction = (actual_saved / raw_actual * 100.0) if raw_actual else 0.0

        runs.append({
            "target_raw_prompt_tokens": target,
            "tokenizer_measured_raw_prompt_tokens": measured_raw,
            "tokenizer_measured_hive_prompt_tokens": measured_hive,
            "both_prompts_fit_model": measured_raw < MODEL_CONTEXT and measured_hive < MODEL_CONTEXT,
            "status": status,
            "raw": raw,
            "hive": hive,
            "actual_input_tokens_saved": actual_saved,
            "actual_input_token_reduction_percent": round(actual_reduction, 2),
        })

    comparable = [run for run in runs if run["status"] == "BOTH_PASS"]
    result = {
        "benchmark": "compressor-inwindow-ab-001",
        "model": os.getenv("HIVE_AB_MODEL", "qwen2.5-coder:3b"),
        "tokenizer": TOKENIZER_MODEL,
        "model_context_limit_tokens": MODEL_CONTEXT,
        "task": "repair missing requests dependency while preserving focused test scope",
        "history_design": (
            "relevant excerpt from the real failed CI evidence + actual Hive repository text as "
            "historical tool output; answer-leaking files excluded; newest human wording preserved verbatim"
        ),
        "failed_log_source": failed_source,
        "eligible_repo_files": len(corpus_paths),
        "targets": list(targets),
        "runs": runs,
        "both_pass_points": len(comparable),
        "all_points_directly_comparable": len(runs) == len(comparable),
        "claim_scope": (
            "direct Raw-vs-Hive quality and measured input-token comparison at sizes where both fit "
            "inside the same 32,768-token model context; one coding task only"
        ),
    }
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 1 if hive_regression else 0


if __name__ == "__main__":
    raise SystemExit(main())

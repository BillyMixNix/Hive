"""Export the fair Raw-vs-Hive coding benchmark as an Android asset.

The phone app does not invent its own benchmark. It consumes the same history
construction and Hive adapter used by the in-window validation harness, then
runs the resulting Raw and Hive prompts locally through llama.cpp.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from transformers import AutoTokenizer

from compressor_inwindow_ab import _build_near_target, _targets
from compressor_live_ab import EXPECTED_COMMAND, _fetch_failed_ci_log
from compressor_scale_ab import (
    TOKENIZER_MODEL,
    _eligible_repo_corpus,
    _history_json,
    _prompt,
    _tok,
)
from hive_compressor.coding_agent import adapt_coding_session


DEFAULT_TARGETS = (8_000, 16_000, 24_000, 30_000)
SYSTEM_PROMPT = (
    "Solve the requested coding task from the supplied context. "
    "Do not explain your reasoning. Return only the requested JSON."
)


def export_bundle(output: Path) -> dict:
    tokenizer = AutoTokenizer.from_pretrained(TOKENIZER_MODEL)
    tokenizer.model_max_length = 1_000_000_000
    failed_log, failed_source = _fetch_failed_ci_log()
    corpus, corpus_paths = _eligible_repo_corpus()

    cases = []
    for target in DEFAULT_TARGETS:
        events, _ = _build_near_target(target, tokenizer, failed_log, corpus)
        raw_history = _history_json(events)
        adapted = adapt_coding_session(events)
        hive_history = json.dumps(
            adapted["model_context"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        raw_prompt = _prompt("RAW", raw_history)
        hive_prompt = _prompt("HIVE", hive_history)
        cases.append(
            {
                "target": target,
                "raw_prompt": raw_prompt,
                "hive_prompt": hive_prompt,
                "raw_tokens": _tok(tokenizer, raw_prompt),
                "hive_tokens": _tok(tokenizer, hive_prompt),
            }
        )

    bundle = {
        "schema": "hive.phone-bench.v1",
        "benchmark": "compressor-inwindow-ab-phone-001",
        "tokenizer": TOKENIZER_MODEL,
        "expected_command": EXPECTED_COMMAND,
        "system_prompt": SYSTEM_PROMPT,
        "failed_log_source": failed_source,
        "eligible_repo_files": len(corpus_paths),
        "cases": cases,
        "claim_scope": (
            "same-model Raw-vs-Hive phone execution for one coding repair task; "
            "human wording remains verbatim and answer-leaking files are excluded"
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    bundle = export_bundle(args.output)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "cases": [
                    {
                        "target": c["target"],
                        "raw_tokens": c["raw_tokens"],
                        "hive_tokens": c["hive_tokens"],
                    }
                    for c in bundle["cases"]
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

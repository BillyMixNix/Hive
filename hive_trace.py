"""Opt-in capture of real Hive model calls for Raw-vs-Hive trace studies.

Tracing is disabled unless HIVE_TRACE_DIR is set. When enabled, every model
call is appended as one JSON object per line. The recorder is deliberately
best-effort: trace failures must never change agent behavior.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

TRACE_VERSION = "hive-real-trace-v1"


def trace_enabled() -> bool:
    return bool(os.getenv("HIVE_TRACE_DIR", "").strip())


def _trace_path() -> Path | None:
    raw = os.getenv("HIVE_TRACE_DIR", "").strip()
    if not raw:
        return None
    directory = Path(raw)
    directory.mkdir(parents=True, exist_ok=True)
    run_id = os.getenv("HIVE_TRACE_RUN_ID", "").strip() or "session"
    return directory / f"{run_id}.jsonl"


def record_model_call(
    *,
    provider: str,
    model: str,
    role: str,
    prompt: str,
    system: str | None = None,
    response: str | None = None,
    success: bool,
    started_at: float,
    elapsed_seconds: float,
    timeout_seconds: float | int | None = None,
    usage: dict[str, Any] | None = None,
    error: BaseException | None = None,
    attempt: int | None = None,
) -> None:
    """Append one exact model-boundary record when tracing is enabled."""
    path = _trace_path()
    if path is None:
        return

    try:
        record = {
            "trace_version": TRACE_VERSION,
            "call_id": str(uuid.uuid4()),
            "run_id": os.getenv("HIVE_TRACE_RUN_ID", "").strip() or "session",
            "started_at_unix": started_at,
            "finished_at_unix": started_at + elapsed_seconds,
            "recorded_at_unix": time.time(),
            "provider": provider,
            "model": model,
            "role": role,
            "prompt": prompt,
            "system": system,
            "response": response,
            "success": bool(success),
            "elapsed_seconds": float(elapsed_seconds),
            "timeout_seconds": timeout_seconds,
            "attempt": attempt,
            "usage": dict(usage or {}),
            "error": None if error is None else {
                "type": type(error).__name__,
                "message": str(error),
            },
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception:
        # Observability cannot become a new failure mode for the coding agent.
        return

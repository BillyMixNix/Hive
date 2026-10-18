"""Privacy-minimal SQLite metering.

Request content is never stored here; only counts and timings are retained.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_events (
    request_id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    key_hash TEXT NOT NULL,
    mode TEXT NOT NULL,
    record_count INTEGER NOT NULL,
    input_bytes INTEGER NOT NULL,
    output_bytes INTEGER NOT NULL,
    estimated_input_tokens INTEGER NOT NULL,
    estimated_output_tokens INTEGER NOT NULL,
    latency_ms REAL NOT NULL
);
"""


class UsageMeter:
    def __init__(self, path: str | Path = "hive_usage.db") -> None:
        self.path = str(path)
        with sqlite3.connect(self.path) as conn:
            conn.execute(SCHEMA)

    def record(self, request_id: str, key_hash: str, result: dict[str, Any], latency_ms: float) -> None:
        stats = result["stats"]
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                INSERT INTO usage_events (
                    request_id, created_at, key_hash, mode, record_count,
                    input_bytes, output_bytes, estimated_input_tokens,
                    estimated_output_tokens, latency_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    time.time(),
                    key_hash,
                    result["mode"],
                    stats["records"],
                    stats["input_bytes"],
                    stats["output_bytes"],
                    stats["estimated_input_tokens"],
                    stats["estimated_output_tokens"],
                    latency_ms,
                ),
            )

    def summary(self, key_hash: str) -> dict[str, Any]:
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                """
                SELECT COUNT(*), COALESCE(SUM(input_bytes), 0), COALESCE(SUM(output_bytes), 0),
                       COALESCE(SUM(estimated_input_tokens), 0),
                       COALESCE(SUM(estimated_output_tokens), 0),
                       COALESCE(AVG(latency_ms), 0)
                FROM usage_events WHERE key_hash = ?
                """,
                (key_hash,),
            ).fetchone()

        requests, input_bytes, output_bytes, in_tokens, out_tokens, avg_latency = row
        bytes_saved = max(0, input_bytes - output_bytes)
        reduction = (bytes_saved / input_bytes * 100.0) if input_bytes else 0.0
        return {
            "requests": requests,
            "input_bytes": input_bytes,
            "output_bytes": output_bytes,
            "bytes_saved": bytes_saved,
            "reduction_percent": round(reduction, 2),
            "estimated_input_tokens": in_tokens,
            "estimated_output_tokens": out_tokens,
            "average_latency_ms": round(avg_latency, 2),
        }

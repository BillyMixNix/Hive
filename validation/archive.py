"""Append-only provenance archive for empirical gate decisions and deployments."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_event(event: dict, archive_path: str | Path) -> dict:
    path = Path(archive_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(event)
    payload.setdefault("timestamp", utc_now())
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
    return payload


def read_events(archive_path: str | Path) -> list[dict]:
    path = Path(archive_path)
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def find_evaluation(evaluation_id: str, archive_path: str | Path) -> dict | None:
    for event in reversed(read_events(archive_path)):
        if (
            event.get("event_type") == "evaluation"
            and event.get("evaluation_id") == evaluation_id
        ):
            return event
    return None


def deployments_for(evaluation_id: str, archive_path: str | Path) -> list[dict]:
    return [
        event
        for event in read_events(archive_path)
        if event.get("event_type") == "deployment"
        and event.get("evaluation_id") == evaluation_id
    ]

"""Hive dependency Watcher.

The Watcher owns WAITING. It polls unresolved external dependencies, persists
resolution events, and invokes a resume command when something changes. It does
not reason about what to do next; the continuation controller/cognitive worker
owns that decision.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass
class Resolution:
    resolved: bool
    result: str | None = None
    evidence: dict[str, Any] | None = None


class Adapter(Protocol):
    def check(self, dependency: dict[str, Any]) -> Resolution: ...


class GitHubActionsAdapter:
    """Poll GitHub Actions using the REST API and an optional GITHUB_TOKEN."""

    def __init__(self, token: str | None = None):
        self.token = token or os.getenv("GITHUB_TOKEN")

    def check(self, dependency: dict[str, Any]) -> Resolution:
        repo = dependency["repo"]
        run_id = dependency["run_id"]
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/actions/runs/{run_id}",
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                **({"Authorization": f"Bearer {self.token}"} if self.token else {}),
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            return Resolution(False, evidence={"http_error": exc.code})
        status = payload.get("status")
        if status != "completed":
            return Resolution(False, evidence={"status": status})
        conclusion = payload.get("conclusion") or "unknown"
        return Resolution(
            True,
            result=conclusion,
            evidence={
                "status": status,
                "conclusion": conclusion,
                "run_id": run_id,
                "html_url": payload.get("html_url"),
                "head_sha": payload.get("head_sha"),
            },
        )


ADAPTERS: dict[str, type[Adapter]] = {"github_actions": GitHubActionsAdapter}


def append_event(queue: Path, event: dict[str, Any]) -> None:
    queue.parent.mkdir(parents=True, exist_ok=True)
    with queue.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, separators=(",", ":")) + "\n")


def watch_once(state_path: Path, queue_path: Path) -> int:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    dependency = state.get("waiting_on")
    if not dependency:
        return 0
    kind = dependency["kind"]
    adapter_cls = ADAPTERS.get(kind)
    if adapter_cls is None:
        raise ValueError(f"no watcher adapter for dependency kind {kind!r}")
    resolution = adapter_cls().check(dependency)
    if not resolution.resolved:
        return 0
    append_event(queue_path, {
        "kind": "dependency_resolved",
        "dependency": dependency,
        "result": resolution.result,
        "evidence": resolution.evidence or {},
        "observed_at": time.time(),
    })
    return 1


def daemon(state_path: Path, queue_path: Path, interval: float, resume_cmd: list[str] | None) -> None:
    seen_signature: str | None = None
    while True:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        dependency = state.get("waiting_on")
        signature = json.dumps(dependency, sort_keys=True) if dependency else None
        if signature and signature != seen_signature:
            if watch_once(state_path, queue_path):
                seen_signature = signature
                if resume_cmd:
                    subprocess.run(resume_cmd, check=False)
        elif not signature:
            seen_signature = None
        time.sleep(interval)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("state")
    ap.add_argument("--queue", default=".hive/events.jsonl")
    ap.add_argument("--interval", type=float, default=30.0)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--resume", nargs=argparse.REMAINDER)
    args = ap.parse_args()
    state, queue = Path(args.state), Path(args.queue)
    if args.once:
        return 0 if watch_once(state, queue) >= 0 else 1
    daemon(state, queue, args.interval, args.resume or None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

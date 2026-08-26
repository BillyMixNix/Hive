from __future__ import annotations

import json
from typing import Any, Callable, Protocol, Sequence

from .arena import ToolRequest
from .core import Seed


class TargetExecutionPlanner(Protocol):
    def plan(
        self,
        seed: Seed,
        target: Any,
        available_tools: Sequence[str],
    ) -> Sequence[ToolRequest]: ...


class HiveTargetExecutionPlanner:
    """Translate an executable construction leaf into concrete Arena requests."""

    def __init__(self, ask: Callable[..., str] | None = None, *, max_requests: int = 2):
        if ask is None:
            from hive_llm import ask_hive

            ask = ask_hive
        self.ask = ask
        self.max_requests = max_requests

    @staticmethod
    def _parse(text: str) -> dict[str, Any]:
        cleaned = text.strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]
        return json.loads(cleaned)

    def plan(
        self,
        seed: Seed,
        target: Any,
        available_tools: Sequence[str],
    ) -> Sequence[ToolRequest]:
        prompt = (
            "KINGDOM / CONSTRUCTION FRONTIER EXECUTION\n\n"
            f"Original intent: {seed.text}\n"
            f"Executable target: {getattr(target, 'statement', '')}\n"
            f"Target kind: {getattr(target, 'kind', '')}\n"
            f"Target reason: {getattr(target, 'reason', '')}\n"
            f"Named capability: {getattr(target, 'capability', '')}\n"
            f"Available Arena tools: {list(available_tools)}\n\n"
            "Convert this leaf into the smallest concrete reality-contact operation that can decide whether the "
            "target is satisfied. Prefer an available tool. If the required capability is absent, still request it "
            "by a concise stable tool name with a concrete operation and JSON payload so Kingdom can treat the "
            "absence as another capability target. Do not claim success yourself. "
            f"Return at most {self.max_requests} requests as JSON {{'requests': [...]}}. "
            "Each request has tool, operation, payload (object), purpose. JSON only."
        )
        payload = self._parse(self.ask(prompt, role="planner"))
        requests: list[ToolRequest] = []
        branch_id = str(getattr(target, "origin_branch_id", ""))
        for item in payload.get("requests", [])[: self.max_requests]:
            if not isinstance(item, dict):
                continue
            tool = str(item.get("tool") or "").strip()
            operation = str(item.get("operation") or "").strip()
            raw_payload = item.get("payload")
            if not tool or not operation or not isinstance(raw_payload, dict):
                continue
            requests.append(
                ToolRequest(
                    tool=tool,
                    operation=operation,
                    payload=dict(raw_payload),
                    purpose=str(item.get("purpose") or getattr(target, "statement", "")),
                    branch_id=branch_id,
                )
            )
        return tuple(requests)

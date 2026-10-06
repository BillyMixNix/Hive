"""OpenAI Managed Agents backend for Hive.

Hive remains the authority for planning contracts, deterministic edit validation,
verification, review, and promotion. This backend only supplies model calls.
Sessions are persistent per Hive role for the lifetime of one build, so repair and
replan calls retain the role's managed-agent context.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from . import providers

AGENTS_BETA = "agents=v1"
TERMINAL_TURN_STATES = {"completed", "failed", "cancelled"}


def _message(text: str) -> list[dict[str, Any]]:
    return [{"role": "user", "content": [{"type": "input_text", "text": text}]}]


def _assistant_text(items: dict, turn_id: str | None = None) -> str:
    for item in items.get("data", []) or []:
        if item.get("type") != "message" or item.get("role") != "assistant":
            continue
        if turn_id and item.get("turn_id") != turn_id:
            continue
        parts=[]
        for part in item.get("content", []) or []:
            if part.get("type") in ("output_text", "text") and part.get("text"):
                parts.append(part["text"])
        if parts:
            return "\n".join(parts).strip()
    return ""


def _usage_count(value: Any) -> int | None:
    """Keep absent/invalid usage unknown; zero is valid only when explicitly reported."""
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _turn_usage_fields(*sources: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize best-effort usage from newest turn detail, then the turn list."""
    def first_count(key: str, detail_key: str | None = None, nested_field: str | None = None) -> int | None:
        for source in sources:
            if not isinstance(source, dict):
                continue
            value = source.get(key)
            if detail_key:
                nested = source.get(detail_key)
                if isinstance(nested, dict) and nested_field and nested_field in nested:
                    value = nested.get(nested_field)
            count = _usage_count(value)
            if count is not None:
                return count
        return None

    input_tokens = first_count("input_tokens")
    output_tokens = first_count("output_tokens")
    total_tokens = first_count("total_tokens")
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    cached_input_tokens = first_count("cached_tokens", "input_tokens_details", "cached_tokens")
    reasoning_tokens = first_count("reasoning_tokens", "output_tokens_details", "reasoning_tokens")
    known = [input_tokens, output_tokens, total_tokens, cached_input_tokens, reasoning_tokens]
    if input_tokens is not None and output_tokens is not None:
        status = "reported"
    elif any(value is not None for value in known):
        status = "partial"
    else:
        status = "unavailable"
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cached_input_tokens": cached_input_tokens,
        "reasoning_tokens": reasoning_tokens,
        "usage_status": status,
        "usage_observed_at": datetime.now(timezone.utc).isoformat(),
    }


@dataclass
class PersistentAgentBackend:
    model: str = "gpt-6-astra"
    timeout: float = 900.0
    poll_seconds: float = 0.5
    multi_agent: bool = False
    max_concurrent_subagents: int = 2
    client: httpx.AsyncClient | None = None
    sessions: dict[str, str] = field(default_factory=dict)
    metrics: list[dict[str, Any]] = field(default_factory=list)

    def _headers(self) -> dict[str, str]:
        key=providers.openai_key()
        if not key:
            raise RuntimeError("Persistent Agents backend requires an OpenAI API key.")
        return {"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                "OpenAI-Beta": AGENTS_BETA}

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        if self.client is not None:
            response=await self.client.request(method, path, headers=self._headers(), **kwargs)
        else:
            async with httpx.AsyncClient(base_url=providers.OPENAI_BASE, timeout=60.0) as client:
                response=await client.request(method, path, headers=self._headers(), **kwargs)
        if not response.is_success:
            raise RuntimeError(f"OpenAI Agents {response.status_code}: {response.text[:1200]}")
        return response

    async def _create_session(self, role: str, prompt: str) -> tuple[str, str | None]:
        body = {
            "agent": {
                "model": self.model,
                "instructions": (
                    f"You are the bounded {role} agent inside Nix Workshop Hive Build Mode. "
                    "Follow the role contract exactly. Return only the response format Hive requests. "
                    "Hive, not you, owns verification and promotion."
                ),
                "multi_agent": {"enabled": self.multi_agent},
            },
            "environment": {"type": "none"},
            "input": _message(prompt),
        }    
        js=(await self._request("POST", "/agents/sessions", json=body)).json()
        session_id=js.get("id")
        if not session_id:
            raise RuntimeError("OpenAI Agents create-session response omitted id")
        self.sessions[role]=session_id
        # The initial turn may be exposed directly, but polling can discover it too.
        turn=js.get("turn") or {}
        return session_id, turn.get("id")

    async def _continue_session(self, session_id: str, prompt: str) -> None:
        body={"events":[{"type":"agent.session.input.message", "input":_message(prompt)}]}
        await self._request("POST", f"/agents/sessions/{session_id}/events", json=body)

    async def _wait_for_turn(self, session_id: str, previous_turn_ids: set[str]) -> dict:
        deadline=time.monotonic()+self.timeout
        latest=None
        while time.monotonic() < deadline:
            js=(await self._request("GET", f"/agents/sessions/{session_id}/turns",
                                    params={"order":"desc", "limit":20})).json()
            turns=js.get("data", []) or []
            candidates=[t for t in turns if t.get("id") not in previous_turn_ids]
            if candidates:
                latest=candidates[0]
                status=latest.get("status")
                if status in TERMINAL_TURN_STATES:
                    if status != "completed":
                        error=latest.get("error") or {}
                        raise RuntimeError(f"Persistent agent turn {status}: {error.get('message') or error}")
                    return latest
            await asyncio.sleep(self.poll_seconds)
        raise TimeoutError(f"Persistent agent exceeded {self.timeout:g}s waiting for a completed turn")

    async def _retrieve_turn_usage(self, session_id: str, turn: dict) -> tuple[dict[str, Any], str, str | None]:
        """Fetch the completed turn resource once; usage is telemetry, never a run gate."""
        listed_usage = turn.get("usage") if isinstance(turn, dict) else None
        turn_id = turn.get("id") if isinstance(turn, dict) else None
        detail_usage = None
        lookup_error = None
        if turn_id:
            try:
                detail = (await self._request(
                    "GET", f"/agents/sessions/{session_id}/turns/{turn_id}"
                )).json()
                if isinstance(detail, dict):
                    detail_usage = detail.get("usage")
            except Exception as exc:
                # A reporting endpoint failure must not turn successful model work into
                # a failed build. Keep the failure visible without persisting response
                # bodies, headers, or any credential-bearing material.
                lookup_error = type(exc).__name__
        fields = _turn_usage_fields(detail_usage, listed_usage)
        detail_has_counts = _turn_usage_fields(detail_usage)["usage_status"] != "unavailable"
        listed_has_counts = _turn_usage_fields(listed_usage)["usage_status"] != "unavailable"
        source = (
            "turn_detail+turn_list" if detail_has_counts and listed_has_counts
            else "turn_detail" if detail_has_counts
            else "turn_list" if listed_has_counts
            else "unavailable"
        )
        return fields, source, lookup_error

    async def __call__(self, role: str, prompt: str) -> str:
        started=time.monotonic()
        session_id=self.sessions.get(role)
        turn_id=None
        usage_fields=_turn_usage_fields()
        usage_source="unavailable"
        usage_lookup_error=None
        metric={
            "role":role, "provider":"openai_agents", "model":self.model,
            "session_id":session_id, "turn_id":None,
            **usage_fields,
        }
        previous=set()
        try:
            if session_id:
                turns=(await self._request("GET", f"/agents/sessions/{session_id}/turns",
                                           params={"order":"desc", "limit":100})).json()
                previous={t.get("id") for t in turns.get("data", []) or [] if t.get("id")}
                await self._continue_session(session_id, prompt)
            else:
                session_id, _ = await self._create_session(role, prompt)
            turn=await self._wait_for_turn(session_id, previous)
            turn_id=turn.get("id")
            usage_fields, usage_source, usage_lookup_error = await self._retrieve_turn_usage(session_id, turn)
            items=(await self._request("GET", f"/agents/sessions/{session_id}/items",
                                       params={"order":"desc", "limit":100})).json()
            text=_assistant_text(items, turn_id)
            if not text:
                raise RuntimeError("Persistent agent completed without an assistant text result")
            metric.update({
                "session_id":session_id, "turn_id":turn_id, **usage_fields,
                "usage_source":usage_source, "status":"completed",
            })
            if usage_lookup_error:
                metric["usage_lookup_error_type"] = usage_lookup_error
            return text
        except Exception as exc:
            metric.update({
                "session_id":session_id, "turn_id":turn_id, **usage_fields,
                "usage_source":usage_source, "status":"failed",
                "error_type":type(exc).__name__,
            })
            if usage_lookup_error:
                metric["usage_lookup_error_type"] = usage_lookup_error
            raise
        finally:
            metric["wall_seconds"] = round(time.monotonic()-started,3)
            self.metrics.append(metric)

"""Bounded prompt -> response adapters. No candidate execution or verifier authority.

OpenAI uses the documented REST Responses API, with no SDK dependency, tools,
redirects, proxy environment, automatic retries, or persisted API conversations.
Only the Authorization header contains a credential; that header is never saved.
"""
from __future__ import annotations

import asyncio
import hashlib
import http.client
import json
import math
import os
import re
import socket
import threading
import time
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Callable, Protocol


class ProviderFailure(RuntimeError):
    def __init__(self, classification: str):
        self.classification = classification
        super().__init__(classification)  # never use remote/transport exception text


class AgentProvider(Protocol):
    async def __call__(self, role: str, prompt: str) -> str: ...


def encode(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def instructions(role: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", role):
        raise ProviderFailure("INVALID_ROLE")
    return f"You are the bounded {role} agent inside Nix Workshop Hive Build Mode. Follow the role contract exactly."


@dataclass(frozen=True)
class Limits:
    max_model_calls: int = 1
    max_output_tokens: int = 32
    max_input_tokens: int = 512
    max_total_tokens: int = 1024
    timeout_seconds: float = 60
    max_experiment_seconds: float = 300
    max_prompt_bytes: int = 256_000
    # Optional conservative tariff, supplied and audited by the operator.
    max_cost_usd: str | None = None
    input_usd_per_million: str | None = None
    output_usd_per_million: str | None = None

    def __post_init__(self):
        for name in ("max_model_calls", "max_output_tokens", "max_input_tokens",
                     "max_total_tokens", "max_prompt_bytes"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ProviderFailure("INVALID_BUDGET")
        if self.max_output_tokens < 16:
            raise ProviderFailure("INVALID_BUDGET")
        for value in (self.timeout_seconds, self.max_experiment_seconds):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ProviderFailure("INVALID_BUDGET")
        rates = (self.max_cost_usd, self.input_usd_per_million, self.output_usd_per_million)
        if any(value is not None for value in rates):
            try:
                parsed = [Decimal(value) for value in rates]
                if not all(value.is_finite() and value > 0 for value in parsed):
                    raise ValueError()
            except (ValueError, TypeError, ArithmeticError):
                raise ProviderFailure("INVALID_TARIFF") from None


class Budget:
    """Serial, persistent one-experiment ledger. Unknown charge halts the run.

    The reservation includes the complete maximum output, including reasoning.
    Dollar reservation is conditional on operator-supplied current upper tariffs;
    token and model-call limits do not depend on those tariffs.
    """
    def __init__(self, limits: Limits, output: Path):
        self.limits = limits
        self.output = output
        self.started = time.monotonic()
        self.calls = self.input_tokens = self.output_tokens = self.reserved_tokens = 0
        self.api_requests = 0
        self.reserved_cost = Decimal(0)
        self.accounted_cost = Decimal(0)
        self.halted: str | None = None
        # Never resume a partly charged run or reset its allowance by reopening.
        self.output.mkdir(parents=True, exist_ok=False)
        self.save()

    def cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        if self.limits.max_cost_usd is None:
            return Decimal(0)
        return (Decimal(input_tokens) * Decimal(self.limits.input_usd_per_million)
                + Decimal(output_tokens) * Decimal(self.limits.output_usd_per_million)) / 1_000_000

    def check(self):
        if self.halted:
            raise ProviderFailure(self.halted)
        if self.calls >= self.limits.max_model_calls:
            raise ProviderFailure("MAX_MODEL_CALLS")
        if time.monotonic() - self.started >= self.limits.max_experiment_seconds:
            raise ProviderFailure("EXPERIMENT_DEADLINE")

    def reserve(self, count: int):
        self.check()
        if type(count) is not int or count < 0:
            raise ProviderFailure("INVALID_INPUT_COUNT")
        reserve = count + self.limits.max_output_tokens
        if count > self.limits.max_input_tokens:
            raise ProviderFailure("MAX_INPUT_TOKENS")
        if self.input_tokens + self.output_tokens + self.reserved_tokens + reserve > self.limits.max_total_tokens:
            raise ProviderFailure("MAX_TOTAL_TOKENS")
        cost = self.cost(count, self.limits.max_output_tokens)
        if self.limits.max_cost_usd is not None and self.accounted_cost + self.reserved_cost + cost > Decimal(self.limits.max_cost_usd):
            raise ProviderFailure("MAX_EXPERIMENT_COST")
        self.calls += 1
        self.reserved_tokens += reserve
        self.reserved_cost += cost
        self.save()  # persist before the potentially billable request

    def settle(self, usage: dict, count: int):
        if not isinstance(usage, dict):
            raise ProviderFailure("USAGE_UNAVAILABLE")
        values = [usage.get(name) for name in ("input_tokens", "output_tokens", "total_tokens")]
        if any(type(value) is not int or value < 0 for value in values) or values[0] + values[1] != values[2]:
            raise ProviderFailure("USAGE_UNAVAILABLE")
        incoming, outgoing, _ = values
        self.input_tokens += incoming
        self.output_tokens += outgoing
        self.reserved_tokens -= count + self.limits.max_output_tokens
        self.reserved_cost -= self.cost(count, self.limits.max_output_tokens)
        self.accounted_cost += self.cost(incoming, outgoing)
        self.save()
        if incoming > count or outgoing > self.limits.max_output_tokens or self.input_tokens + self.output_tokens > self.limits.max_total_tokens:
            raise ProviderFailure("PROVIDER_EXCEEDED_RESERVATION")
        if self.limits.max_cost_usd is not None and self.accounted_cost > Decimal(self.limits.max_cost_usd):
            raise ProviderFailure("PROVIDER_EXCEEDED_COST_RESERVATION")

    def halt(self, classification: str):
        self.halted = classification
        self.save()

    def summary(self):
        return {"limits": asdict(self.limits), "model_call_count": self.calls,
                "api_request_count": self.api_requests,
                "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "total_tokens": self.input_tokens + self.output_tokens,
                "unsettled_reserved_tokens": self.reserved_tokens,
                "accounted_cost_usd": str(self.accounted_cost) if self.limits.max_cost_usd else None,
                "unsettled_reserved_cost_usd": str(self.reserved_cost) if self.limits.max_cost_usd else None,
                "cost_basis": "OPERATOR_SUPPLIED_UPPER_TARIFF" if self.limits.max_cost_usd else "HARD_TOKEN_BUDGET",
                "halted": self.halted, "automatic_retries": 0}

    def save(self):
        temp = self.output / "budget.tmp"
        temp.write_bytes(encode(self.summary()) + b"\n")
        temp.replace(self.output / "budget.json")


Transport = Callable[[str, bytes, dict[str, str], float], tuple[int, dict[str, str], bytes]]


def openai_transport(path: str, body: bytes, headers: dict[str, str], timeout: float):
    """Fixed TLS origin; no redirects, environment proxies, shell, or debug logs."""
    if path not in ("/v1/responses", "/v1/responses/input_tokens"):
        raise ProviderFailure("INVALID_ENDPOINT")
    connection = http.client.HTTPSConnection("api.openai.com", timeout=timeout)
    deadline = time.monotonic() + timeout
    try:
        connection.request("POST", path, body=body, headers=headers)
        response = connection.getresponse()
        blocks, size = [], 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError()
            if connection.sock is not None:
                connection.sock.settimeout(remaining)
            block = response.read1(65536)
            if not block:
                break
            size += len(block)
            if size > 8_000_000:
                raise ProviderFailure("RESPONSE_TOO_LARGE")
            blocks.append(block)
        return response.status, {k.lower(): v for k, v in response.getheaders()
                                 if k.lower() == "x-request-id"}, b"".join(blocks)
    finally:
        connection.close()


class OpenAIProvider:
    name = "openai_responses"

    def __init__(self, *, model: str, budget: Budget, reasoning_effort: str | None = None,
                 transport: Transport = openai_transport):
        if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}", model):
            raise ProviderFailure("INVALID_MODEL")
        if reasoning_effort not in (None, "none", "minimal", "low", "medium", "high", "xhigh"):
            raise ProviderFailure("INVALID_REASONING_CONFIG")
        self.model, self.budget, self.reasoning_effort = model, budget, reasoning_effort
        self.transport = transport
        self._key = os.environ.pop("OPENAI_API_KEY", "")
        if not self._key:
            raise ProviderFailure("API_KEY_UNAVAILABLE")
        if "\n" in self._key or "\r" in self._key:
            raise ProviderFailure("INVALID_CREDENTIAL")
        self._lock = threading.Lock()
        self._cancelled = threading.Event()
        self._ordinal = 0

    def safe(self, data: bytes):
        # Guard payloads, responses, IDs and configuration without rewriting
        # experimental content. A contaminated artifact is refused, not redacted.
        if self._key.encode() in data or self._key.encode() in encode(self.model):
            raise ProviderFailure("SECRET_CONTAMINATION")

    def save(self, path: Path, data: bytes):
        self.safe(data)
        with path.open("xb") as stream:
            stream.write(data)

    def request(self, path: str, payload: dict, folder: Path, label: str, timeout: float):
        body = encode(payload)
        self.save(folder / f"{label}.request.json", body)
        started = time.time()
        t0 = time.monotonic()
        if self.budget.api_requests >= 2 * self.budget.limits.max_model_calls:
            raise ProviderFailure("MAX_API_REQUESTS")
        self.budget.api_requests += 1
        self.budget.save()
        try:
            status, headers, raw = self.transport(path, body, {
                "Authorization": "Bearer " + self._key,
                "Content-Type": "application/json", "Accept": "application/json",
            }, timeout)
        except BaseException:
            self.save(folder / f"{label}.metadata.json", encode({
                "endpoint": path, "status": "TRANSPORT_FAILED", "request_started_unix": started,
                "response_received_unix": None, "elapsed_seconds": time.monotonic() - t0,
                "request_sha256": sha(body), "api_request_id": None,
            }))
            raise
        self.safe(raw)
        request_id = headers.get("x-request-id")
        self.safe(encode(request_id))
        self.save(folder / f"{label}.response.json", raw)
        self.save(folder / f"{label}.metadata.json", encode({
            "endpoint": path, "http_status": status, "request_started_unix": started,
            "response_received_unix": time.time(), "elapsed_seconds": time.monotonic() - t0,
            "api_request_id": request_id, "request_sha256": sha(body), "response_sha256": sha(raw),
        }))
        if not 200 <= status < 300:
            kind = {401: "AUTHENTICATION_FAILURE", 403: "ACCESS_DENIED", 429: "RATE_LIMIT_OR_QUOTA"}.get(status,
                    "PROVIDER_SERVER_ERROR" if status >= 500 else "PROVIDER_REQUEST_REJECTED")
            raise ProviderFailure(kind)
        try:
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except (ValueError, TypeError):
            raise ProviderFailure("MALFORMED_PROVIDER_RESPONSE") from None

    def _call(self, role: str, prompt: str) -> str:
        with self._lock:
            folder, metadata = None, None
            try:
                if self._cancelled.is_set():
                    raise ProviderFailure("CANCELLED_CHARGE_UNKNOWN")
                self.budget.check()
                wrapper = instructions(role)
                if type(prompt) is not str or not prompt.strip() or len(prompt.encode()) > self.budget.limits.max_prompt_bytes:
                    raise ProviderFailure("INVALID_OR_OVERSIZED_PROMPT")
                payload = {"model": self.model, "instructions": wrapper, "input": prompt,
                           "max_output_tokens": self.budget.limits.max_output_tokens,
                           "store": False, "stream": False, "tools": []}
                if self.reasoning_effort is not None:
                    payload["reasoning"] = {"effort": self.reasoning_effort}
                self.safe(encode(payload))
                self._ordinal += 1
                folder = self.budget.output / f"call-{self._ordinal:04d}"
                folder.mkdir()
                metadata = {"provider": self.name, "configured_model": self.model, "role": role,
                            "prompt_sha256": sha(prompt.encode()), "configuration": payload.copy(),
                            "started_unix": time.time(), "status": "started", "retry_count": 0}
                metadata["configuration"].pop("input")
                metadata["configuration"].pop("instructions")
                self.save(folder / "prompt.txt", prompt.encode())
                # Same exact input and instructions; no tool/conversation state.
                count_payload = {key: payload[key] for key in ("model", "input", "instructions", "tools")}
                remaining = lambda: min(self.budget.limits.timeout_seconds,
                    self.budget.limits.max_experiment_seconds - (time.monotonic() - self.budget.started))
                if remaining() <= 0:
                    raise ProviderFailure("EXPERIMENT_DEADLINE")
                count = self.request("/v1/responses/input_tokens", count_payload, folder, "count", remaining()).get("input_tokens")
                if self._cancelled.is_set():
                    raise ProviderFailure("CANCELLED_CHARGE_UNKNOWN")
                self.budget.reserve(count)
                metadata["counted_input_tokens"] = count
                if remaining() <= 0:
                    raise ProviderFailure("EXPERIMENT_DEADLINE")
                result = self.request("/v1/responses", payload, folder, "generation", remaining())
                metadata.update(returned_model=result.get("model"), response_id=result.get("id"),
                                usage=result.get("usage"), provider_status=result.get("status"))
                self.budget.settle(result.get("usage"), count)
                if self._cancelled.is_set():
                    raise ProviderFailure("CANCELLED_CHARGE_UNKNOWN")
                if not isinstance(result.get("model"), str) or not result["model"]:
                    raise ProviderFailure("MODEL_IDENTITY_UNAVAILABLE")
                if result.get("status") != "completed":
                    raise ProviderFailure("INCOMPLETE_OR_FAILED_RESPONSE")
                output = result.get("output")
                if not isinstance(output, list):
                    raise ProviderFailure("MALFORMED_PROVIDER_RESPONSE")
                if any(not isinstance(item, dict) or item.get("type") not in ("message", "reasoning") for item in output):
                    raise ProviderFailure("UNEXPECTED_TOOL_OR_OUTPUT")
                text = ""
                for item in output:
                    if item["type"] != "message":
                        continue
                    if item.get("role") != "assistant" or item.get("status") not in (None, "completed"):
                        raise ProviderFailure("MALFORMED_PROVIDER_RESPONSE")
                    for content in item.get("content", []):
                        if content.get("type") != "output_text" or type(content.get("text")) is not str:
                            raise ProviderFailure("REFUSAL_OR_NON_TEXT_RESPONSE")
                        text += content["text"]
                if not text.strip():
                    raise ProviderFailure("EMPTY_RESPONSE")
                if time.monotonic() - self.budget.started > self.budget.limits.max_experiment_seconds:
                    raise ProviderFailure("EXPERIMENT_DEADLINE")
                self.save(folder / "response.txt", text.encode())
                metadata.update(status="completed", response_text_sha256=sha(text.encode()))
                return text
            except BaseException as exc:
                if isinstance(exc, ProviderFailure):
                    kind = exc.classification
                elif isinstance(exc, (TimeoutError, socket.timeout)):
                    kind = "PROVIDER_TIMEOUT_CHARGE_UNKNOWN"
                elif isinstance(exc, OSError):
                    kind = "PROVIDER_TRANSPORT_FAILURE_CHARGE_UNKNOWN"
                else:
                    kind = "PROVIDER_INTERNAL_FAILURE"
                self.budget.halt(kind)
                if metadata is not None:
                    metadata.update(status="failed", failure_class=kind)
                raise ProviderFailure(kind) from None
            finally:
                if metadata is not None:
                    metadata["completed_unix"] = time.time()
                    self.save(folder / "call.json", encode(metadata))

    async def __call__(self, role: str, prompt: str) -> str:
        try:
            return await asyncio.to_thread(self._call, role, prompt)
        except asyncio.CancelledError:
            # The bounded transport thread must account a response that may
            # already have been charged. It alone writes the ledger, and this
            # latch prevents another request from starting after cancellation.
            self._cancelled.set()
            raise


class MockProvider:
    """Offline callable for controller injection tests; never classified as API evidence."""
    name = "mock"

    def __init__(self, response: str = "HIVE_API_OK"):
        self.response = response
        self.calls = []

    async def __call__(self, role: str, prompt: str) -> str:
        instructions(role)
        self.calls.append((role, prompt))
        return self.response


class OllamaProvider:
    """Thin reuse of the unchanged local provider, for future matched comparisons.

    The historical provider's retry/format policies stay visible and unchanged.
    This adapter is not the bounded remote launcher and cannot qualify a run.
    """
    name = "ollama_legacy"

    def __init__(self, model: str, max_output_tokens: int, timeout_seconds: float = 900):
        self.model, self.max_output_tokens, self.timeout = model, max_output_tokens, timeout_seconds

    async def __call__(self, role: str, prompt: str) -> str:
        from hive_canonical.legacy.workshop import providers
        result = await providers.ollama_chat(self.model, [{"role": "user", "content": prompt}],
            instructions(role), max_output_tokens=self.max_output_tokens, total_timeout=self.timeout)
        return result["text"]

"""One-request OpenAI connectivity probe, separate from Hive's provider."""

from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal
import http.client
import json
import os
from pathlib import Path
import sys


MODEL = "gpt-5.4-mini-2026-03-17"
PROMPT = "Return exactly HIVE_API_OK."
OUTPUT_LIMIT = 16
INPUT_ENVELOPE = 4096  # Planning allowance, not an API-enforced input cap.
PRICE_REVIEW_EXPIRES = date(2026, 10, 14)
MAX_PLANNED_USD = Decimal("0.01")
INPUT_RATE = Decimal("0.75")
OUTPUT_RATE = Decimal("4.50")
INPUT_UPLIFT = Decimal("1.25") * Decimal("1.10") * Decimal("2")
OUTPUT_UPLIFT = Decimal("1.10") * Decimal("2")
ERROR_CODES = frozenset({
    "invalid_api_key", "insufficient_quota", "credit_balance_exhausted",
    "organization_spend_limit_exceeded", "project_spend_limit_exceeded",
    "organization_usage_limit_exceeded", "slow_down", "server_is_overloaded",
    "model_not_found", "unsupported_parameter", "rate_limit_exceeded",
})
ERROR_TYPES = frozenset({
    "invalid_request_error", "authentication_error", "permission_error",
    "rate_limit_error", "insufficient_quota", "service_unavailable_error",
    "server_error", "api_error",
})
ERROR_PARAMS = frozenset({
    "model", "input", "max_output_tokens", "reasoning", "reasoning.effort",
    "service_tier", "tools", "tool_choice", "store", "stream", "truncation",
})


class SmokeFailure(Exception):
    def __init__(self, classification: str, details: dict | None = None):
        super().__init__(classification)
        self.classification = classification
        self.details = details or {}


def safe_http_error(status: object, raw: bytes) -> dict:
    """Keep only fixed, recognized fields; never preserve server-supplied prose."""
    result = {}
    if type(status) is int and 400 <= status <= 599:
        result["http_status"] = status
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeError):
        return result
    if not isinstance(payload, dict) or not isinstance(payload.get("error"), dict):
        return result
    error = payload["error"]
    for source, target, allowed in (
        ("code", "error_code", ERROR_CODES),
        ("type", "error_type", ERROR_TYPES),
        ("param", "error_param", ERROR_PARAMS),
    ):
        value = error.get(source)
        if type(value) is str and value in allowed:
            result[target] = value
    return result


def planned_cost_usd() -> Decimal:
    return ((INPUT_ENVELOPE * INPUT_RATE * INPUT_UPLIFT)
            + (OUTPUT_LIMIT * OUTPUT_RATE * OUTPUT_UPLIFT)) / 1_000_000


def request_body(today: date | None = None) -> bytes:
    if (today or date.today()) > PRICE_REVIEW_EXPIRES:
        raise SmokeFailure("PRICE_REVIEW_EXPIRED")
    if planned_cost_usd() >= MAX_PLANNED_USD:
        raise SmokeFailure("PLANNED_COST_EXCEEDS_LIMIT")
    body = json.dumps({
        "model": MODEL,
        "input": PROMPT,
        "max_output_tokens": OUTPUT_LIMIT,
        "reasoning": {"effort": "none"},
        "service_tier": "default",
        "tools": [],
        "tool_choice": "none",
        "store": False,
        "stream": False,
        "truncation": "disabled",
    }, separators=(",", ":")).encode("ascii")
    if len(body) > 512:
        raise SmokeFailure("REQUEST_TOO_LARGE")
    return body


def run_smoke(key: str, *, connection_factory=http.client.HTTPSConnection,
              today: date | None = None) -> dict:
    body = request_body(today)
    if not key or not key.startswith("sk-"):
        raise SmokeFailure("API_KEY_UNAVAILABLE")
    connection = None
    try:
        connection = connection_factory("api.openai.com", timeout=60)
        connection.request("POST", "/v1/responses", body=body, headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
        })
        response = connection.getresponse()
        raw = response.read(65_537)
        if len(raw) > 65_536:
            raise SmokeFailure("RESPONSE_TOO_LARGE")
        if response.status != 200:
            raise SmokeFailure("API_HTTP_ERROR", safe_http_error(response.status, raw))
        payload = json.loads(raw)
        usage = payload.get("usage")
        if (payload.get("model") != MODEL or
                payload.get("service_tier") != "default" or
                payload.get("status") != "completed" or
                not isinstance(usage, dict)):
            raise SmokeFailure("RESPONSE_UNEXPECTED")
        incoming, outgoing, total = (usage.get(name) for name in
                                     ("input_tokens", "output_tokens", "total_tokens"))
        if (any(type(n) is not int or n < 0 for n in (incoming, outgoing, total)) or
                incoming + outgoing != total):
            raise SmokeFailure("USAGE_UNAVAILABLE")
        if incoming > INPUT_ENVELOPE or outgoing > OUTPUT_LIMIT:
            raise SmokeFailure("USAGE_EXCEEDED_ENVELOPE")
        return {
            "classification": "CONNECTIVITY_PASS",
            "model": MODEL,
            "service_tier": "default",
            "input_tokens": incoming,
            "output_tokens": outgoing,
            "total_tokens": total,
            "request_count": 1,
            "planned_upper_usd": str(planned_cost_usd()),
            "planning_input_envelope_tokens": INPUT_ENVELOPE,
            "pricing_review_expires": PRICE_REVIEW_EXPIRES.isoformat(),
            "qualification": "CONNECTIVITY_ONLY_NOT_HIVE_PROVIDER_OR_VERIFIER",
        }
    except SmokeFailure:
        raise
    except Exception:
        # Never emit exception strings, response bodies, or credential material.
        raise SmokeFailure("TRANSPORT_OR_RESPONSE_ERROR") from None
    finally:
        if connection is not None:
            connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    key = os.environ.pop("OPENAI_API_KEY", "")
    try:
        result = run_smoke(key)
        exit_code = 0
    except SmokeFailure as exc:
        result = {"classification": exc.classification, "request_count": "at_most_one",
                  "qualification": "CONNECTIVITY_ONLY_NOT_HIVE_PROVIDER_OR_VERIFIER",
                  **exc.details}
        exit_code = 2
    args.output_root.mkdir(parents=True, exist_ok=True)
    (args.output_root / "HIVE_API_CONNECTION_SMOKE.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(result["classification"], file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

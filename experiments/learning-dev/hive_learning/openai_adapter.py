"""Stateless OpenAI Responses transport for the recovered Hive controller.

No requests at import, no retries or model fallback, and no credential logging.
Request/output limits alone do not bound dollars. The one-shot cloud trial
additionally supplies the verified, conservative SpendingGuard.
"""
import os
from pathlib import Path
import re
import threading
import time
import urllib.error
import urllib.request

from .adapter import OllamaHive
from .evaluate import strict_json
from .ledger import canonical


ENDPOINT = "https://api.openai.com/v1/responses"
MAX_INPUT_BYTES = 250_000
MAX_RESPONSE_BYTES = 1_000_000
# Fixed labels preserve failure detail without logging provider bodies, prompts,
# credential-bearing exceptions, or other untrusted text. Never overwrite the
# first cause with the controller's subsequent refusal to retry.
FAILURE_CODES = {
    "OpenAI response is missing valid measured token usage": "invalid_usage",
    "OpenAI returned a different model; use an exact snapshot identifier": "model_mismatch",
    "OpenAI response did not complete; episode invalid": "response_incomplete",
    "OpenAI reported output beyond the configured token limit": "output_limit",
    "OpenAI response has invalid output items": "invalid_output_items",
    "OpenAI response must contain one assistant message and no tool actions": "unexpected_output_items",
    "OpenAI response refused or did not contain one complete text output": "refusal_or_invalid_message",
    "OpenAI output is not one strict JSON object": "invalid_json_object",
    "OpenAI response exceeds the fixed byte limit": "response_byte_limit",
    "OpenAI transport failed; no retry; usage may be incomplete": "network_failure",
    "cannot safely settle provider usage against the spending reservation": "unsettled_usage",
    "remaining trial budget cannot cover another full request": "spending_limit",
}
LESSON_FORMAT = {
    "type": "json_schema", "name": "hive_lesson", "strict": True,
    "schema": {"type": "object", "additionalProperties": False,
               "properties": {key: {"type": "string"}
                              for key in ("when", "summary", "rationale")},
               "required": ["when", "summary", "rationale"]},
}


def load_api_key(env_file=None):
    """Read a provisioned secret without placing it in child process environments.

    An explicitly selected env file takes precedence. This deliberately supports
    only a literal OPENAI_API_KEY assignment, not shell or dotenv expansion.
    It neither writes credentials nor searches the recipient workspace.
    """
    key = os.environ.pop("OPENAI_API_KEY", None)
    if env_file is not None:
        path = Path(env_file)
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 65_536:
                raise ValueError
            entries = []
            for line in path.read_text(encoding="utf-8").splitlines():
                name, separator, value = line.strip().removeprefix("export ").partition("=")
                if separator and name.strip() == "OPENAI_API_KEY":
                    value = value.strip()
                    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                        value = value[1:-1]
                    entries.append(value)
            if len(entries) != 1:
                raise ValueError
            key = entries[0]
        except (OSError, ValueError, UnicodeError):
            raise ValueError("cannot read one literal OPENAI_API_KEY from the selected env file") from None
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,1024}", key):
        raise ValueError("a provisioned OPENAI_API_KEY is required; do not supply it as a CLI argument")
    return key


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Authorization is never forwarded to a redirect target.
        return None


class RequestBudget:
    def __init__(self, cap, spending=None):
        if type(cap) is not int or not 1 <= cap <= 3889:
            raise ValueError("max_requests must be an integer from 1 to 3889")
        self.cap, self.calls, self.failed = cap, 0, False
        self.spending = spending
        self.lock = threading.Lock()

    def take(self):
        with self.lock:
            if self.failed or self.calls >= self.cap:
                raise RuntimeError("OpenAI episode request limit reached or prior transport failed")
            if self.spending is not None:
                self.spending.reserve()
            self.calls += 1  # Reserve before I/O, including failed attempts.

    def settle(self, model, input_tokens, output_tokens, service_tier):
        if self.spending is not None:
            self.spending.settle(model, input_tokens, output_tokens, service_tier)

    def fail(self):
        with self.lock:
            self.failed = True
            if self.spending is not None:
                self.spending.fail()


class OpenAIMeter:
    def __init__(self, model, api_key, cap, budget, max_output_tokens, *,
                 deadline=900, proposer=False):
        self.model, self._api_key, self.cap = model, api_key, cap
        self.budget, self.max_output_tokens = budget, max_output_tokens
        self.end = time.monotonic() + deadline
        self.proposer, self.failed = proposer, False
        self.failure_code = None
        self.usage = {"calls": 0, "prompt_tokens": 0, "output_tokens": 0}
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def __call__(self, messages, **kwargs):
        try:
            remaining = self.end - time.monotonic()
            if self.failed or self.usage["calls"] >= self.cap or remaining <= 0:
                raise RuntimeError("OpenAI recipient request limit or deadline reached")
            if (not isinstance(messages, list) or not messages
                    or any(not isinstance(m, dict) or set(m) != {"role", "content"}
                           or m["role"] not in {"system", "user", "assistant"}
                           or not isinstance(m["content"], str) for m in messages)):
                raise ValueError("OpenAI transport requires plain text chat messages")
            payload = {"model": self.model, "store": False, "service_tier": "default",
                       "instructions": "Return exactly one JSON object in the format requested by the task.",
                       "input": messages, "max_output_tokens": self.max_output_tokens,
                       "text": {"format": LESSON_FORMAT if self.proposer else {"type": "json_object"}}}
            raw_request = canonical(payload).encode("utf-8")
            if len(raw_request) > MAX_INPUT_BYTES:
                raise ValueError("OpenAI request exceeds the fixed input byte limit")
            self.budget.take()
            self.usage["calls"] += 1
            request = urllib.request.Request(ENDPOINT, data=raw_request,
                headers={"Content-Type": "application/json", "Authorization": "Bearer " + self._api_key})
            try:
                with self.opener.open(request, timeout=min(120, remaining)) as response:
                    raw = response.read(MAX_RESPONSE_BYTES + 1)
            except urllib.error.HTTPError as exc:
                status = exc.code
                # Only documented, fixed error codes can leave this boundary.
                safe_code = "unspecified"
                try:
                    body = strict_json(exc.read(65_537))
                    code = body.get("error", {}).get("code")
                    if code in {"insufficient_quota", "rate_limit_exceeded", "invalid_api_key",
                                "model_not_found", "permission_denied", "unsupported_parameter"}:
                        safe_code = code
                except Exception:
                    pass
                exc.close()
                # Error bodies and exception text may contain sensitive input.
                raise RuntimeError(f"OpenAI HTTP {status} ({safe_code}); no retry") from None
            except Exception:
                raise RuntimeError("OpenAI transport failed; no retry; usage may be incomplete") from None
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError("OpenAI response exceeds the fixed byte limit")
            try:
                value = strict_json(raw)
                usage = value["usage"]
                counts = [usage[key] for key in ("input_tokens", "output_tokens")]
                if any(type(count) is not int or count < 0 for count in counts):
                    raise ValueError
            except (ValueError, TypeError, KeyError):
                raise ValueError("OpenAI response is missing valid measured token usage") from None
            self.usage["prompt_tokens"] += counts[0]
            self.usage["output_tokens"] += counts[1]
            self.budget.settle(value.get("model"), *counts, value.get("service_tier"))
            if value.get("model") != self.model:
                raise ValueError("OpenAI returned a different model; use an exact snapshot identifier")
            if value.get("status") != "completed" or value.get("error") is not None:
                raise ValueError("OpenAI response did not complete; episode invalid")
            if counts[1] > self.max_output_tokens:
                raise ValueError("OpenAI reported output beyond the configured token limit")
            output = value.get("output")
            if not isinstance(output, list) or any(not isinstance(item, dict) for item in output):
                raise ValueError("OpenAI response has invalid output items")
            messages_out = [item for item in output if item.get("type") == "message"]
            if (len(messages_out) != 1
                    or any(item.get("type") not in {"reasoning", "message"} for item in output)):
                raise ValueError("OpenAI response must contain one assistant message and no tool actions")
            message = messages_out[0]
            content = message.get("content")
            if (message.get("role") != "assistant" or message.get("status") != "completed"
                    or not isinstance(content, list) or len(content) != 1
                    or not isinstance(content[0], dict) or content[0].get("type") != "output_text"
                    or not isinstance(content[0].get("text"), str)):
                raise ValueError("OpenAI response refused or did not contain one complete text output")
            text = content[0]["text"]
            try:
                if not isinstance(strict_json(text), dict):
                    raise ValueError
            except (ValueError, TypeError):
                raise ValueError("OpenAI output is not one strict JSON object") from None
            return text
        except Exception as exc:
            if self.failure_code is None:
                self.failure_code = FAILURE_CODES.get(str(exc), "transport_or_local_limit")
                if re.fullmatch(r"OpenAI HTTP [0-9]{3} \([a-z_]+\); no retry", str(exc)):
                    self.failure_code = "http_error"
            self.failed = True
            self.budget.fail()  # The controller cannot turn an error into paid retries.
            raise


class OpenAIHive(OllamaHive):
    def __init__(self, model, api_key, *, max_requests, max_output_tokens=4096, seed=42,
                 spending=None):
        if (not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,200}", model)
                or not isinstance(api_key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,1024}", api_key)):
            raise ValueError("an exact model identifier and a privately provisioned key are required")
        if type(max_output_tokens) is not int or not 1 <= max_output_tokens <= 32768:
            raise ValueError("max_output_tokens must be an integer from 1 to 32768")
        super().__init__(model, ENDPOINT, seed)
        self._api_key, self.max_output_tokens = api_key, max_output_tokens
        if spending is not None and (spending.model != model or spending.max_output_tokens != max_output_tokens):
            raise ValueError("spending guard does not match this transport")
        self.budget = RequestBudget(max_requests, spending)
        self.identity = {"scope": "development_real_model", "transport": "openai_responses",
                         "model": model, "url": ENDPOINT, "store": False,
                         "max_requests": max_requests, "max_output_tokens": max_output_tokens,
                         "max_input_bytes": MAX_INPUT_BYTES, "model_seed": None,
                         "output_format": "strict_lesson_schema_then_json_object",
                         "controller_sha256": self.identity["controller_sha256"]}
        self.identity["service_tier"] = "default"
        if spending is not None:
            self.identity["spending"] = spending.identity

    def _new_meter(self, cap, deadline=900, *, proposer=False):
        meter = OpenAIMeter(self.model, self._api_key, cap, self.budget,
                            self.max_output_tokens, deadline=deadline, proposer=proposer)
        self.meters.append(meter)
        return meter

    def observed_usage(self):
        result = super().observed_usage()
        for item, meter in zip(result, self.meters):
            if meter.failure_code is not None:
                item["failure_code"] = meter.failure_code
        return result

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
    "OpenAI transport requires plain text chat messages": "invalid_input_messages",
    "OpenAI request exceeds the fixed input byte limit": "input_byte_limit",
    "OpenAI recipient request limit or deadline reached": "recipient_limit_or_deadline",
    "OpenAI episode request limit reached or prior transport failed": "episode_limit_or_prior_failure",
    "OpenAI response is missing valid measured token usage": "invalid_usage",
    "OpenAI returned a different model; use an exact snapshot identifier": "model_mismatch",
    "OpenAI response did not complete; episode invalid": "response_incomplete",
    "OpenAI reported output beyond the configured token limit": "output_limit",
    "OpenAI response has invalid output items": "invalid_output_items",
    "OpenAI response must contain one assistant message and no tool actions": "unexpected_output_items",
    "OpenAI worker requires a controller task packet with tool contracts": "invalid_worker_packet",
    "OpenAI worker response must contain exactly one native Hive action": "invalid_native_action",
    "OpenAI native Hive action has invalid or unauthorized arguments": "invalid_native_arguments",
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


def worker_tool(messages):
    """Describe only actions offered in the controller's initial task packet.

    Contract argument values include placeholders, not JSON Schema definitions.
    The wrapper therefore carries a strict JSON string rather than inventing
    argument types. The recovered controller still checks and executes actions.
    Later tool results and model messages cannot expand this set of tools.
    """
    try:
        packet = strict_json(next(m["content"] for m in messages if m["role"] == "user"))
        allowed = packet["authority"]["allowed_tools"]
        contracts = packet["tool_contracts"]
        if (not isinstance(allowed, list) or not isinstance(contracts, list)
                or any(not isinstance(name, str) for name in allowed)):
            raise ValueError
        names = [item["name"] for item in contracts]
        if (not names or len(set(names)) != len(names)
                or any(not isinstance(name, str) or not re.fullmatch(r"[a-z_]{1,64}", name)
                       or name not in allowed for name in names)):
            raise ValueError
    except (StopIteration, ValueError, TypeError, KeyError):
        raise ValueError("OpenAI worker requires a controller task packet with tool contracts") from None
    names = sorted(set(names) | {"finish"})
    return {
        "type": "function", "name": "hive_action", "strict": True,
        "description": "Submit exactly one action for Hive to execute and record. Calling this function does not itself execute the action.",
        "parameters": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "name": {"type": "string", "enum": names},
                "arguments_json": {"type": "string", "description":
                    "A JSON object encoded as a string, using the exact argument keys from the task's tool contract or finish format."},
            },
            "required": ["name", "arguments_json"],
        },
    }


def message_text(message):
    content = message.get("content")
    if (message.get("role") != "assistant" or message.get("status") != "completed"
            or not isinstance(content, list) or len(content) != 1
            or not isinstance(content[0], dict) or content[0].get("type") != "output_text"
            or not isinstance(content[0].get("text"), str)
            or message.get("phase") not in {None, "commentary", "final_answer"}):
        raise ValueError("OpenAI response refused or did not contain one complete text output")
    return content[0]["text"]


def native_action(output, tool):
    calls = [item for item in output if item.get("type") == "function_call"]
    if (len(calls) != 1 or any(item.get("type") not in {"reasoning", "message", "function_call"}
                              for item in output)):
        raise ValueError("OpenAI worker response must contain exactly one native Hive action")
    for item in output:
        if item.get("type") == "message":
            message_text(item)  # Refusals remain failures; prose never becomes an action.
    call = calls[0]
    if call.get("name") != "hive_action" or call.get("status", "completed") != "completed":
        raise ValueError("OpenAI worker response must contain exactly one native Hive action")
    try:
        action = strict_json(call["arguments"])
        if (not isinstance(action, dict) or set(action) != {"name", "arguments_json"}
                or action["name"] not in tool["parameters"]["properties"]["name"]["enum"]
                or not isinstance(action["arguments_json"], str)):
            raise ValueError
        arguments = strict_json(action["arguments_json"])
        if not isinstance(arguments, dict):
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise ValueError("OpenAI native Hive action has invalid or unauthorized arguments") from None
    # Stateless bridge: Hive executes this JSON action and includes the actual
    # tool result in the next transcript. No API-side tool execution or claim of
    # success is manufactured here, and no provider response IDs are replayed.
    return canonical({"name": action["name"], "arguments": arguments})


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
                 deadline=900, proposer=False, observer=None):
        self.model, self._api_key, self.cap = model, api_key, cap
        self.budget, self.max_output_tokens = budget, max_output_tokens
        self.end = time.monotonic() + deadline
        self.proposer, self.failed = proposer, False
        self.failure_code = None
        self.observer = observer
        self.usage = {"calls": 0, "prompt_tokens": 0, "output_tokens": 0}
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def worker(self, messages):
        return self(messages, worker=True)

    def __call__(self, messages, *, worker=False, **kwargs):
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
            if worker:
                tool = worker_tool(messages)
                del payload["text"]
                payload.update({
                    "tools": [tool], "tool_choice": {"type": "function", "name": "hive_action"},
                    "parallel_tool_calls": False,
                    "instructions": "Submit exactly one action using the hive_action function. "
                    "Encode the task packet's JSON action name and arguments as name and arguments_json. "
                    "Hive executes the action only after you return; wait for its actual tool result "
                    "before claiming execution or completion. Text messages do not execute actions.",
                })
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
            if self.observer is not None:
                try:
                    self.observer(self.budget.calls, payload, value, self._api_key)
                except Exception:
                    raise RuntimeError("could not preserve redacted response evidence") from None
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
            if worker:
                return native_action(output, tool)
            messages_out = [item for item in output if item.get("type") == "message"]
            finals = [item for item in messages_out if item.get("phase") != "commentary"]
            if (len(finals) != 1
                    or any(item.get("type") not in {"reasoning", "message"} for item in output)):
                raise ValueError("OpenAI response must contain one assistant message and no tool actions")
            for message in messages_out:
                message_text(message)
            text = message_text(finals[0])
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
                 spending=None, observer=None):
        if (not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,200}", model)
                or not isinstance(api_key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,1024}", api_key)):
            raise ValueError("an exact model identifier and a privately provisioned key are required")
        if type(max_output_tokens) is not int or not 1 <= max_output_tokens <= 32768:
            raise ValueError("max_output_tokens must be an integer from 1 to 32768")
        super().__init__(model, ENDPOINT, seed)
        self._api_key, self.max_output_tokens = api_key, max_output_tokens
        self.observer = observer
        if spending is not None and (spending.model != model or spending.max_output_tokens != max_output_tokens):
            raise ValueError("spending guard does not match this transport")
        self.budget = RequestBudget(max_requests, spending)
        self.identity = {"scope": "development_real_model", "transport": "openai_responses",
                         "model": model, "url": ENDPOINT, "store": False,
                         "max_requests": max_requests, "max_output_tokens": max_output_tokens,
                         "max_input_bytes": MAX_INPUT_BYTES, "model_seed": None,
                         "output_format": "strict_lesson_schema_native_worker_action_json_judge_v2",
                         "controller_sha256": self.identity["controller_sha256"]}
        self.identity["service_tier"] = "default"
        if spending is not None:
            self.identity["spending"] = spending.identity

    def _new_meter(self, cap, deadline=900, *, proposer=False):
        meter = OpenAIMeter(self.model, self._api_key, cap, self.budget,
                            self.max_output_tokens, deadline=deadline, proposer=proposer,
                            observer=self.observer)
        self.meters.append(meter)
        return meter

    def observed_usage(self):
        result = super().observed_usage()
        for item, meter in zip(result, self.meters):
            if meter.failure_code is not None:
                item["failure_code"] = meter.failure_code
        return result

"""Direct typed Responses functions for Hive; the original controller is unchanged.

A JSON string in the old wrapper could contain invalid JSON. Here the arguments
object itself is constrained. Only tools from the initial controller packet can
be offered; the controller still authorizes and executes every returned action.
"""
import re
import time
import urllib.error
import urllib.request

from hive_learning.evaluate import strict_json
from hive_learning.ledger import canonical
from hive_learning.openai_adapter import (OpenAIMeter, OpenAIHive, ENDPOINT,
    MAX_INPUT_BYTES, MAX_RESPONSE_BYTES, FAILURE_CODES, LESSON_FORMAT,
    worker_tool, message_text)


ARGUMENTS = {
    "run_command": {"command": "string"},
    "read_source_lines": {"path": "string"},
    "submit_callable": {"source_file": "string", "definition_line": "integer"},
    "submit_location": {"callable_id": "string", "choice_id": "string"},
    "submit_cause": {"candidate_location_id": "string", "cause_choice_id": "string"},
    "confirm_candidate": {"candidate_location_id": "string"},
    "reject_cause_frontier": {"candidate_location_id": "string"},
    "submit_mechanism": {"location_id": "string", "mechanism": "string"},
    "replace_selected_expression": {"new": "string"},
    "replace_selected_leaf": {"choice_id": "string"},
    "review_snapshot": {},
    "submit_review": {"verdict": "string", "findings": "array"},
}


def object_schema(properties):
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


def native_tools(messages):
    worker_tool(messages)  # Existing validation of initial controller authority.
    packet = strict_json(next(m["content"] for m in messages if m["role"] == "user"))
    result = []
    for contract in packet["tool_contracts"]:
        name = contract["name"]
        if name not in ARGUMENTS or set(contract["arguments"]) != set(ARGUMENTS[name]):
            raise ValueError("unsupported controller tool contract")
        properties = {key: {"type": kind} for key, kind in ARGUMENTS[name].items()}
        if name == "submit_review":
            properties["verdict"]["enum"] = ["PASS", "FINDINGS"]
            properties["findings"]["items"] = {"type": "string"}
        result.append({"type": "function", "name": name, "strict": True,
            "description": "Submit this offered action to Hive. Use the exact current task contract values; Hive checks authority and executes it.",
            "parameters": object_schema(properties)})
    # The executive defaults absent evidence/artifacts/discovered_tasks to empty;
    # it independently ingests actual broker observations, not model claims.
    result.append({"type": "function", "name": "finish", "strict": True,
        "description": "Finish the bounded responsibility only after grounded tool evidence. Hive independently checks completion.",
        "parameters": object_schema({"status": {"type": "string", "enum": ["COMPLETED", "BLOCKED"]},
                                     "summary": {"type": "string"}})})
    return result


def matches(value, schema):
    kind = schema["type"]
    if kind == "object":
        return (isinstance(value, dict) and set(value) == set(schema["required"])
                and all(matches(value[k], s) for k, s in schema["properties"].items()))
    if kind == "array":
        return isinstance(value, list) and all(matches(v, schema["items"]) for v in value)
    if kind == "string":
        return isinstance(value, str) and ("enum" not in schema or value in schema["enum"])
    if kind == "integer":
        return type(value) is int
    return False


def typed_action(output, offered):
    calls = [v for v in output if v.get("type") == "function_call"]
    if len(calls) != 1 or any(v.get("type") not in {"function_call", "message", "reasoning"} for v in output):
        raise ValueError("OpenAI worker response must contain exactly one native Hive action")
    for item in output:
        if item.get("type") == "message":
            message_text(item)
    call = calls[0]
    schemas = {tool["name"]: tool["parameters"] for tool in offered}
    try:
        arguments = strict_json(call["arguments"])
        if (call.get("status", "completed") != "completed" or call["name"] not in schemas
                or not matches(arguments, schemas[call["name"]])):
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise ValueError("OpenAI native Hive action has invalid or unauthorized arguments") from None
    return canonical({"name": call["name"], "arguments": arguments})


class TypedMeter(OpenAIMeter):
    def __call__(self, messages, *, worker=False, **kwargs):
        if not worker:
            return super().__call__(messages, **kwargs)
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
                offered = native_tools(messages)
                del payload["text"]
                payload.update({
                    "tools": offered, "tool_choice": "required", "parallel_tool_calls": False,
                    "instructions": "Submit exactly one of the offered native function calls. "
                    "Pass the task contract's arguments directly as a JSON object. "
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
                return typed_action(output, offered)
        except Exception as exc:
            if self.failure_code is None:
                self.failure_code = FAILURE_CODES.get(str(exc), "transport_or_local_limit")
                if re.fullmatch(r"OpenAI HTTP [0-9]{3} \([a-z_]+\); no retry", str(exc)):
                    self.failure_code = "http_error"
            self.failed = True
            self.budget.fail()  # The controller cannot turn an error into paid retries.
            raise


class TypedHive(OpenAIHive):
    def __init__(self, *args, request_directory=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.request_directory = request_directory
        self.identity["output_format"] = "direct_typed_functions_v4"

    def _new_meter(self, cap, deadline=900, *, proposer=False):
        meter = TypedMeter(self.model, self._api_key, cap, self.budget,
                          self.max_output_tokens, deadline=deadline, proposer=proposer,
                          observer=self.observer)
        if self.request_directory is not None:
            from analysis.cloud_http400 import CaptureHTTP
            original, owner = meter.opener, self
            class Opener:
                def open(self, request, timeout):
                    directory = owner.request_directory / f"request-{owner.budget.calls:05d}"
                    directory.mkdir(parents=True, exist_ok=False)
                    return CaptureHTTP(original, directory, owner._api_key).open(request, timeout)
            meter.opener = Opener()
        self.meters.append(meter)
        return meter

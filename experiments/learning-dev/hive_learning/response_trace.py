"""Opt-in traces for the public synthetic development fixtures only.

Keep replayable final text/action outputs. Do not record API credentials,
response identifiers, hidden reasoning, encrypted reasoning, or HTTP errors.
"""
import hashlib
import json
import os
from pathlib import Path
import re


class ResponseTrace:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(exist_ok=False)

    def __call__(self, sequence, request, response, secret):
        def clean(value):
            if isinstance(value, str):
                value = value.replace(secret, "[REDACTED]")
                return re.sub(r"sk-[A-Za-z0-9_-]{12,}", "[REDACTED]", value)
            if isinstance(value, list):
                return [clean(item) for item in value]
            if isinstance(value, dict):
                return {clean(key): clean(item) for key, item in value.items()}
            return value
        output = []
        items = response.get("output", [])
        if not isinstance(items, list):
            items = [{"type": "non_array"}]
        for item in items[:32]:
            if not isinstance(item, dict):
                output.append({"type": "non_object"})
                continue
            # Reasoning is metadata only; final tool/text output is sufficient
            # to reproduce the decoder failure without exposing model reasoning.
            copied = {k: item[k] for k in ("type", "status", "role", "phase") if k in item}
            if item.get("type") != "reasoning":
                copied.update({k: item[k] for k in ("name", "arguments", "input", "text") if k in item})
                if isinstance(item.get("content"), list):
                    copied["content"] = [{k: part[k] for k in
                                          (("type", "text", "refusal") if part.get("type") in
                                           {"output_text", "refusal"} else ("type",)) if k in part}
                                         for part in item["content"] if isinstance(part, dict)]
            output.append(copied)
        selected = {k: response[k] for k in ("model", "status", "service_tier", "usage", "error")
                    if k in response}
        selected["output"] = output
        if selected.get("error") is not None:
            selected["error"] = {"present": True}
        record = clean({"sequence": sequence, "scope": "public_synthetic_development_trace",
                        "request": request, "response": selected,
                        "original_response_sha256": hashlib.sha256(
                            json.dumps(response, sort_keys=True).encode()).hexdigest()})
        with (self.directory / f"response-{sequence:04d}.json").open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(record, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

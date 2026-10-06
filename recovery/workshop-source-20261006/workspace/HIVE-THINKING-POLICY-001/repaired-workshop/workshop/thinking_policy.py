"""Host-approved thinking controls; omission preserves the provider default.

Profiles bind locally proven boolean controls to exact runtime/model identities.
A thinking-capable model does not necessarily support disabling thinking.
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path

PROFILES = json.loads(Path(__file__).with_name("thinking_profiles.json").read_text(encoding="utf-8"))
WORKER_ROLES = frozenset(("ui", "backend", "tests"))


def worker_options(model, role, *, provider="ollama", response_format=None,
                   max_output_tokens=None, total_timeout=None):
    """Choose once, before generation, only for bounded structured workers."""
    if provider != "ollama" or role not in WORKER_ROLES:
        return {}
    profile = PROFILES.get(model)
    if profile is None:
        return {}  # Unrelated combinations retain their existing/default policy.
    if not (response_format == "json" or isinstance(response_format, dict)):
        return {}
    if (type(max_output_tokens) is not int or max_output_tokens < 1
            or type(total_timeout) not in (int, float)
            or not math.isfinite(total_timeout) or total_timeout <= 0):
        return {}
    value = profile["bounded_worker_think"]
    if type(value) is not bool:
        raise ValueError("Invalid host thinking policy")
    return {"think": value}


async def validate(client, base, model, value):
    """Fail closed without generation when explicit control lacks local proof."""
    if type(value) is not bool:
        raise ValueError("think must be boolean or omitted")
    profile = PROFILES.get(model)
    if profile is None or not any(type(v) is bool and v is value for v in profile["values"]):
        raise ValueError("Explicit thinking control is not attested for this model")
    # Neither a tag name nor the mere presence of 'thinking' establishes support.
    version = await client.get(base + "/api/version")
    tags = await client.get(base + "/api/tags")
    show = await client.post(base + "/api/show", json={"model": model})
    for response in (version, tags, show):
        response.raise_for_status()
    details = show.json()
    actual = {
        "provider_version": version.json().get("version"),
        "model_digest": next((m.get("digest") for m in tags.json().get("models", []) if m.get("name") == model), None),
        "template_sha256": hashlib.sha256(details.get("template", "").encode()).hexdigest(),
    }
    if actual != {key: profile[key] for key in actual} or "thinking" not in details.get("capabilities", []):
        raise ValueError("Thinking-control capability identity mismatch; requalification required")
    return {"requested": value, "validation": "host-attested boolean control", **actual}

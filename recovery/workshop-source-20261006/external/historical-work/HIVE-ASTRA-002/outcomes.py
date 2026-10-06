"""Non-destructive experiment outcome classification over preserved raw reports."""

from __future__ import annotations

from enum import Enum


class Outcome(str, Enum):
    VERIFIED_SUCCESS = "VERIFIED_SUCCESS"
    MODEL_TASK_FAILURE = "MODEL_TASK_FAILURE"
    VERIFIER_INFRA_FAILURE = "VERIFIER_INFRA_FAILURE"
    PROVIDER_INFRA_FAILURE = "PROVIDER_INFRA_FAILURE"
    HARNESS_FAILURE = "HARNESS_FAILURE"
    FALSE_ACCEPTANCE = "FALSE_ACCEPTANCE"
    INVALID = "INVALID"


VERIFIER_INFRA_MARKERS = (
    "pthread_create failed", "unable to create native thread", "eagain",
    "docker is unavailable", "verifier image is unavailable", "gradle timeout",
    "external build-input cache", "approved cache", "dependency cache",
    "network_access_attempt", "source_immutability", "cache_integrity",
)
PROVIDER_INFRA_MARKERS = (
    "insufficient_quota", "credit_balance_exhausted", "billing_hard_limit",
    "rate_limit_exceeded", "server_overloaded", "provider timeout",
    "connection error", "agents api 401", "agents api 403", "agents api 429",
    "agents api 500", "agents api 502", "agents api 503", "agents api 504",
)


def _evidence_text(result: dict) -> str:
    parts = [str(result.get("error_message") or ""), str(result.get("diff_error") or "")]
    model = result.get("model") or {}
    parts.append(str(model.get("error_message") or ""))
    for check in ((result.get("acceptance") or {}), (result.get("full_gate") or {})):
        detail = check.get("detail") or {}
        if isinstance(detail, dict):
            parts.extend(str(detail.get(key) or "") for key in
                         ("stderr_tail", "stdout_tail", "report_error"))
        else:
            parts.append(str(detail))
    for issue in (result.get("review") or {}).get("issues") or []:
        parts.append(str(issue))
    return "\n".join(parts).casefold()


def classify(result: dict) -> Outcome:
    """Assign one class without rewriting the raw status or inventing usage."""
    if not isinstance(result, dict):
        return Outcome.INVALID
    status = str(result.get("status") or "").casefold()
    acceptance = result.get("acceptance") or {}
    full = result.get("full_gate") or {}
    claimed_success = status in {"ready", "verified"}
    if claimed_success and not (acceptance.get("passed") is True and full.get("passed") is True):
        return Outcome.FALSE_ACCEPTANCE
    if result.get("integrity_violation") or result.get("containment_violation") or status == "invalid":
        return Outcome.INVALID
    if (claimed_success and acceptance.get("passed") is True
            and full.get("passed") is True):
        return Outcome.VERIFIED_SUCCESS
    evidence = _evidence_text(result)
    if "string_above_max_length" in evidence or "request field exceeds" in evidence:
        return Outcome.HARNESS_FAILURE
    if any(marker in evidence for marker in VERIFIER_INFRA_MARKERS):
        return Outcome.VERIFIER_INFRA_FAILURE
    if any(marker in evidence for marker in PROVIDER_INFRA_MARKERS):
        return Outcome.PROVIDER_INFRA_FAILURE
    if status in {"infrastructure_error", "job_timeout"}:
        return Outcome.HARNESS_FAILURE
    if status in {"model_failed", "diff_rejected", "rejected", "verification_failed"}:
        return Outcome.MODEL_TASK_FAILURE
    return Outcome.INVALID

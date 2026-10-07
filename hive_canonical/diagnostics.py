"""Recovery-only, allowlisted verifier-to-model transport.

The copied historical verifier and controller still retain full raw audit records.
Only these projections may enter a post-verification model prompt in a bounded
canonical run. No JUnit, Gradle, exception, or candidate-emitted string is copied.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from .legacy.workshop import hive, hive_review


class DiagnosticBoundaryError(ValueError):
    """A safe diagnostic could not be constructed; no model call is allowed."""


class SafeVerificationDiagnostic(dict):
    """Nominally separate model-view object; raw verifier dictionaries are never accepted as this type."""


@dataclass
class SafeRunContext:
    scope: tuple[str, ...]
    expected_cases: int | None
    authorized_prompts: set[str] = field(default_factory=set)
    review_evidence_hashes: set[str] = field(default_factory=set)


ACTIVE: contextvars.ContextVar[SafeRunContext | None] = contextvars.ContextVar(
    "rc1_safe_diagnostic_context", default=None
)

_HEX = re.compile(r"[0-9a-f]{64}\Z")
_CHECKS = frozenset({"frozen_junit_acceptance", "isolated_verifier", "external_integrity",
                     "external_full_gate_prerequisite"})
_STATUSES = frozenset({"PASSED", "FAILED", "TIMED_OUT", "NOT_RUN"})
_CLASSES = frozenset({"NONE", "FROZEN_ACCEPTANCE_FAILED", "VERIFIER_FAILED",
                      "TIMEOUT", "SOURCE_INTEGRITY_FAILED", "UNKNOWN"})


def _hash(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def _count(value: Any) -> int:
    # XML counts are candidate-influenced. They are never verifier authority.
    if type(value) is not int or not 0 <= value <= 10000:
        raise DiagnosticBoundaryError("invalid or excessive reported XML count")
    return value


def _check_id(name: Any, scope: tuple[str, ...]) -> str:
    if type(name) is str and name in _CHECKS:
        return name.upper()
    if type(name) is str:
        for prefix, code in (("python_compile:", "PYTHON_COMPILE"),
                             ("javascript_parse:", "JAVASCRIPT_PARSE")):
            if name.startswith(prefix) and name[len(prefix):] in scope:
                return code
    return "UNKNOWN"


def project(report: Any, *, phase: str, scope: tuple[str, ...],
            expected_cases: int | None = None) -> dict:
    """Build a strict finite-domain projection; reject malformed topology."""
    if phase not in ("TARGETED", "FULL") or not isinstance(scope, tuple):
        raise DiagnosticBoundaryError("invalid host diagnostic policy")
    if expected_cases is not None and (type(expected_cases) is not int or not 0 <= expected_cases <= 10000):
        raise DiagnosticBoundaryError("invalid host expected case count")
    if not isinstance(report, dict) or type(report.get("passed")) is not bool:
        raise DiagnosticBoundaryError("verifier result is not a typed report")
    checks = report.get("checks")
    if not isinstance(checks, list) or len(checks) > 100:
        raise DiagnosticBoundaryError("verifier checks are malformed or excessive")
    ids = []
    for check in checks:
        if not isinstance(check, dict) or type(check.get("passed")) is not bool:
            raise DiagnosticBoundaryError("verifier check is malformed")
        ids.append({"check_id": _check_id(check.get("name"), scope),
                    "passed": check["passed"]})
    passed = hive_review.verification_status(report) == "passed"
    timeout = any(isinstance(c.get("detail"), dict) and
                  c["detail"].get("timed_out") is True for c in checks)
    failed_ids = {row["check_id"] for row in ids if not row["passed"]}
    failure_class = ("NONE" if passed else "TIMEOUT" if timeout else
                     "FROZEN_ACCEPTANCE_FAILED" if "FROZEN_JUNIT_ACCEPTANCE" in failed_ids else
                     "SOURCE_INTEGRITY_FAILED" if "EXTERNAL_INTEGRITY" in failed_ids else
                     "VERIFIER_FAILED" if failed_ids else "UNKNOWN")
    result = SafeVerificationDiagnostic({"schema_version": 1, "phase": phase,
              "verifier_status": "PASSED" if passed else "TIMED_OUT" if timeout else "FAILED",
              "failure_class": failure_class, "checks": ids,
              "host_expected_cases": expected_cases,
              "compilation_status": "UNKNOWN", "timeout": timeout,
              "correction_allowed": phase == "TARGETED" and not passed,
              "allowed_write_files": list(scope)})
    validate(result, scope=scope)
    return result


def validate(value: Any, *, scope: tuple[str, ...]) -> None:
    required = {"schema_version", "phase", "verifier_status", "failure_class", "checks",
                "host_expected_cases", "compilation_status", "timeout", "correction_allowed",
                "allowed_write_files"}
    if (not isinstance(value, dict) or set(value) != required or
            type(value["schema_version"]) is not int or value["schema_version"] != 1):
        raise DiagnosticBoundaryError("diagnostic schema mismatch")
    if value["phase"] not in ("TARGETED", "FULL") or value["verifier_status"] not in _STATUSES or value["failure_class"] not in _CLASSES:
        raise DiagnosticBoundaryError("diagnostic enum mismatch")
    if value["compilation_status"] != "UNKNOWN" or type(value["timeout"]) is not bool or type(value["correction_allowed"]) is not bool:
        raise DiagnosticBoundaryError("diagnostic status mismatch")
    if (value["verifier_status"] == "PASSED") != (value["failure_class"] == "NONE"):
        raise DiagnosticBoundaryError("contradictory pass/failure disposition")
    if value["verifier_status"] == "TIMED_OUT" and not value["timeout"]:
        raise DiagnosticBoundaryError("timeout disposition without timeout evidence")
    if value["verifier_status"] == "PASSED" and value["timeout"]:
        raise DiagnosticBoundaryError("pass disposition contradicts timeout")
    if value["correction_allowed"] != (value["phase"] == "TARGETED" and value["verifier_status"] != "PASSED"):
        raise DiagnosticBoundaryError("correction eligibility contradicts phase/status")
    if value["allowed_write_files"] != list(scope) or not isinstance(value["checks"], list):
        raise DiagnosticBoundaryError("diagnostic scope/check mismatch")
    for row in value["checks"]:
        if not isinstance(row, dict) or set(row) != {"check_id", "passed"} or type(row["passed"]) is not bool:
            raise DiagnosticBoundaryError("diagnostic check mismatch")
        if row["check_id"] not in {x.upper() for x in _CHECKS} | {"PYTHON_COMPILE", "JAVASCRIPT_PARSE", "UNKNOWN"}:
            raise DiagnosticBoundaryError("diagnostic check identifier mismatch")
    if value["verifier_status"] == "PASSED" and any(not row["passed"] for row in value["checks"]):
        raise DiagnosticBoundaryError("pass disposition contradicts failed check")
    expected = value["host_expected_cases"]
    if expected is not None:
        _count(expected)


class SafeReviewEvidence(dict):
    """Separate typed model projection; never a raw verification record."""


_ORIGINAL_TARGETED = hive._targeted_diagnostic
_ORIGINAL_REPAIR_PROMPT = hive._targeted_repair_prompt
_ORIGINAL_REVIEW_EVIDENCE = hive_review.evidence
_ORIGINAL_REVIEW_PROMPT = hive_review.prompt


def _targeted(verification: dict) -> str:
    ctx = ACTIVE.get()
    if ctx is None:
        return _ORIGINAL_TARGETED(verification)
    return json.dumps(project(verification, phase="TARGETED", scope=ctx.scope,
                              expected_cases=ctx.expected_cases), sort_keys=True)


def _repair_prompt(*args, **kwargs):
    prompt = _ORIGINAL_REPAIR_PROMPT(*args, **kwargs)
    ctx = ACTIVE.get()
    if ctx is not None:
        ctx.authorized_prompts.add(_hash(prompt))
    return prompt


def _review_evidence(run: dict) -> dict:
    ctx = ACTIVE.get()
    if ctx is None:
        return _ORIGINAL_REVIEW_EVIDENCE(run)
    # Candidate diff is legitimate semantic review input. Verifier emissions,
    # controller errors, and XML-derived names/messages are not copied.
    raw_diff = run.get("diff")
    if type(raw_diff) is not str:
        raise hive_review.ReviewEvidenceError("candidate diff is malformed")
    final = run.get("verification")
    try:
        final_diag = (project(final, phase="FULL", scope=ctx.scope,
                              expected_cases=ctx.expected_cases) if final is not None else None)
        targeted = [project(item["result"], phase="TARGETED", scope=ctx.scope,
                            expected_cases=ctx.expected_cases)
                    for item in run.get("targeted_verifications", [])]
    except (DiagnosticBoundaryError, KeyError, TypeError) as exc:
        raise hive_review.ReviewEvidenceError("safe verifier projection unavailable") from exc
    scope_changed = run.get("changed_files")
    if not isinstance(scope_changed, list) or any(type(path) is not str or path not in ctx.scope for path in scope_changed):
        raise hive_review.ReviewEvidenceError("host changed-file scope is invalid")
    identity = run.get("verified_stage_sha256")
    if identity is not None and (type(identity) is not str or not _HEX.fullmatch(identity)):
        raise hive_review.ReviewEvidenceError("stage identity is malformed")
    evidence = SafeReviewEvidence({
        "request": run["request"],
        "diff": hive_review.bounded_text(raw_diff, hive_review.MAX_DIFF_CHARS),
        "changed_files": scope_changed,
        "targeted_verification": {"attempts": targeted},
        "final_verification": final_diag or {"verifier_status": "NOT_RUN"},
        "artifact_identity": {"verified_stage_sha256": identity},
        "scope_and_ownership": {"host_write_scope": list(ctx.scope)},
        "omitted_data": ["Raw verifier evidence, JUnit names/messages, stdout/stderr and controller errors are human audit only."],
    })
    if len(json.dumps(evidence, ensure_ascii=False)) > hive_review.MAX_EVIDENCE_CHARS:
        raise hive_review.ReviewEvidenceError("safe review evidence exceeds bounded budget")
    ctx.review_evidence_hashes.add(hive_review.digest(evidence))
    return evidence


def _review_prompt(context: dict, *, repair_raw: str | None = None, error: str = ""):
    ctx = ACTIVE.get()
    if ctx is not None and (not isinstance(context, SafeReviewEvidence) or
                            hive_review.digest(context) not in ctx.review_evidence_hashes):
        raise hive_review.ReviewEvidenceError("raw review evidence cannot enter protected model context")
    prompt = _ORIGINAL_REVIEW_PROMPT(context, repair_raw=repair_raw, error=error)
    if ctx is not None:
        ctx.authorized_prompts.add(_hash(prompt))
    return prompt


def install_hooks() -> None:
    """Patch only private copied legacy modules; no archived source bytes change."""
    hive._targeted_diagnostic = _targeted
    hive._targeted_repair_prompt = _repair_prompt
    hive_review.evidence = _review_evidence
    hive_review.prompt = _review_prompt


def authorized(prompt: str, ctx: SafeRunContext | None) -> bool:
    return ctx is not None and _hash(prompt) in ctx.authorized_prompts

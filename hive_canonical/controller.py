"""Fail-closed RC1 adapter around the recovered FACTORIAL-003R1 controller.

The only public outcome is an isolated, hash-bound candidate and its evidence.
This module makes no provider call on its own; callers supply the bounded agent
call that the recovered pipeline uses.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Mapping

from .legacy.workshop import external_root, hive, hive_jvm, hive_review
from .promotion import PromotionUnavailableError, unavailable
from .provenance import CandidateIntegrityError, assert_scoped_change, source_index

# Importing the public package disables the copied engine's historical internal
# apply endpoints. Original archived source and its own regression suite stay
# unchanged. There is deliberately no promotion operation in RC1.
hive.apply_run = unavailable
hive._apply_run_locked = unavailable
hive.rollback_run = unavailable

AgentCall = Callable[[str, str], Awaitable[str]]


class CandidatePolicyError(ValueError):
    """Host policy was not complete enough to start an autonomous run."""


@dataclass(frozen=True)
class CandidateSpec:
    baseline_root: Path
    runs_root: Path
    request: str
    local_model: str
    allowed_write_files: tuple[str, ...]
    frozen_junit_tests: tuple[Mapping[str, object], ...] = ()
    require_independent_review: bool = False


@dataclass(frozen=True)
class CandidateResult:
    run_id: str
    run_record: Path
    baseline_sha256: str
    candidate_sha256: str
    candidate_stage: Path
    changed_files: tuple[str, ...]
    verification_status: str
    semantic_review: str
    software_verified: bool
    failure_class: str | None
    promotion_authorization: str = "unavailable"
    applied: bool = False


def _safe_scope(scope: tuple[str, ...], frozen_paths: set[str]) -> tuple[str, ...]:
    if not isinstance(scope, tuple) or not 1 <= len(scope) <= 100:
        raise CandidatePolicyError("host write scope must be a nonempty tuple of at most 100 exact files")
    normalized: list[str] = []
    for path in scope:
        if type(path) is not str or not path or path != hive._safe_relative_path(path):
            raise CandidatePolicyError("host write scope contains an unsafe path")
        if "\\" in path or ":" in path or path.startswith(".") or "/./" in f"/{path}/":
            raise CandidatePolicyError("host write scope contains a noncanonical path")
        if path in frozen_paths:
            raise CandidatePolicyError("frozen acceptance source cannot be writable")
        # The source inventory deliberately omits runtime/cache output trees.
        # An authorized edit must be part of the separately hashed source tree.
        parts = Path(path).parts
        if any(external_root._exclude_directory(Path(*parts[:index]))
               for index in range(1, len(parts))):
            raise CandidatePolicyError("runtime or cache output cannot be writable source")
        normalized.append(path)
    if len({path.casefold() for path in normalized}) != len(normalized):
        raise CandidatePolicyError("host write scope contains duplicate or case-colliding paths")
    return tuple(normalized)


def _failure_class(run: dict, verification_status: str) -> str | None:
    failures = list(run.get("errors") or [])
    for record in (run.get("agents") or {}).values():
        if isinstance(record, dict) and isinstance(record.get("failure"), dict):
            failures.append(record["failure"])
    if any(isinstance(item, dict) and item.get("stage") == "agent_call" for item in failures):
        return "LOCAL_RUNTIME_FAILURE"
    if any(isinstance(item, dict) and item.get("role") == "verifier"
           and item.get("stage") == "verify" for item in failures):
        return "VERIFIER_RUNTIME_FAILURE"
    if verification_status != "passed":
        return "DETERMINISTIC_VERIFICATION_FAILURE" if run.get("verification") else "NO_VERIFICATION_RESULT"
    if failures:
        return "CONTROLLER_FAILURE"
    return None


async def produce_candidate(spec: CandidateSpec, agent_call: AgentCall) -> CandidateResult:
    """Run the recovered pipeline in candidate-only mode; never apply to baseline."""
    if not isinstance(spec, CandidateSpec) or not callable(agent_call):
        raise CandidatePolicyError("a host CandidateSpec and agent callable are required")
    if type(spec.request) is not str or not spec.request.strip():
        raise CandidatePolicyError("a nonempty task is required")
    if type(spec.local_model) is not str or not spec.local_model.strip():
        raise CandidatePolicyError("a model identity is required")
    if type(spec.require_independent_review) is not bool:
        raise CandidatePolicyError("review obligation must be a host boolean")
    if not isinstance(spec.frozen_junit_tests, tuple):
        raise CandidatePolicyError("frozen acceptance inputs must be a host tuple")
    frozen_paths = {entry.get("path") for entry in spec.frozen_junit_tests
                    if isinstance(entry, Mapping) and isinstance(entry.get("path"), str)}
    allowed = _safe_scope(spec.allowed_write_files, frozen_paths)
    baseline = Path(spec.baseline_root).resolve(strict=True)
    runs = Path(spec.runs_root)
    if not runs.is_absolute():
        raise CandidatePolicyError("run storage must be an absolute path")
    runs = runs.resolve(strict=False)
    archive_repo = Path(__file__).resolve().parents[1]
    if runs == archive_repo or archive_repo in runs.parents:
        raise CandidatePolicyError("run storage cannot modify the RC1 source or recovered evidence")
    if runs == baseline or baseline in runs.parents or runs in baseline.parents:
        raise CandidatePolicyError("run storage and immutable baseline overlap")
    workshop = Path(__file__).resolve().parent / "legacy"
    external_root.resolve_external_root(str(baseline), workshop, runs)
    baseline_sha256 = external_root.tree_sha256(baseline)
    profile = hive_jvm.inspect_gradle_project(baseline)
    frozen = hive_jvm.freeze_junit_tests(baseline, list(spec.frozen_junit_tests))
    if profile is not None and not frozen:
        raise CandidatePolicyError("a Gradle candidate requires host-frozen acceptance tests")
    if profile is None and frozen:
        raise CandidatePolicyError("frozen JUnit acceptance requires a Gradle profile")

    run_id = secrets.token_hex(6)
    candidate_root = runs / "external_candidates" / run_id
    metadata = external_root.prepare_candidate(str(baseline), candidate_root, workshop, runs)
    if metadata["baseline_sha256"] != baseline_sha256:
        raise CandidateIntegrityError("baseline changed before the candidate snapshot completed")
    if profile is not None:
        candidate_profile = hive_jvm.inspect_gradle_project(candidate_root)
        if candidate_profile != profile:
            raise CandidateIntegrityError("isolated candidate changed its pinned Gradle profile")
        metadata["jvm_profile"] = dict(profile)
    if frozen:
        metadata["frozen_junit_tests"] = hive_jvm.store_frozen_junit_tests(frozen, runs / run_id)

    run = await hive.run_build(
        candidate_root, runs, spec.request, spec.local_model, agent_call,
        metadata={"external_root": metadata, "external_root_mode": "candidate_only",
                  "rc1_source_anchor": "HIVE-FACTORIAL-003R1"},
        run_id=run_id, external_root_mode=True,
        allowed_write_files=list(allowed),
        require_independent_review=spec.require_independent_review,
    )
    run_record = runs / run_id / "run.json"
    if not run_record.is_file() or run.get("id") != run_id:
        raise CandidateIntegrityError("run evidence or identity is missing")
    if run.get("applied") is not False:
        raise CandidateIntegrityError("candidate-only run reported an apply operation")
    if not external_root.baseline_unchanged(metadata):
        raise CandidateIntegrityError("immutable baseline changed during candidate generation")
    stage = runs / run_id / "stage"
    original_index = source_index(candidate_root)
    stage_index = source_index(stage)
    verification_status = hive_review.verification_status(run.get("verification"))
    changed = assert_scoped_change(
        original_index, stage_index, allowed, list(run.get("changed_files") or []),
        require_change=verification_status == "passed",
    )
    candidate_sha256 = external_root.tree_sha256(stage)
    if verification_status == "passed":
        _, legacy_identity = hive._source_manifest(stage)
        if legacy_identity != run.get("verified_stage_sha256"):
            raise CandidateIntegrityError("verified stage identity no longer matches run evidence")
    semantic = hive_review.state(run)["review_disposition"]
    failure = _failure_class(run, verification_status)
    verified = verification_status == "passed" and failure is None and bool(changed)
    return CandidateResult(
        run_id=run_id, run_record=run_record, baseline_sha256=baseline_sha256,
        candidate_sha256=candidate_sha256, candidate_stage=stage,
        changed_files=changed, verification_status=verification_status,
        semantic_review=semantic, software_verified=verified,
        failure_class=failure,
    )

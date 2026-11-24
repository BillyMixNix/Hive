"""Bounded integration of Hive's code agents with empirical candidate evaluation.

This module connects existing planner, coder, isolated-variant, and regression
APIs.  It deliberately stops at a *candidate* decision: it has no promotion or
live-repository write operation.

The isolation here protects the live checkout from ordinary candidate patches.
It is not an adversarial sandbox for executing hostile Python; production use
still requires an OS/container boundary around candidate execution.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from regression_gate import RegressionGate
from validation.archive import append_event
from validation.gate import DEFAULT_PROTECTED_PATHS, evaluate
from validation.variant import extract_target_file, sha256_text


DEFAULT_EDITABLE_TARGETS = frozenset({"planner.py", "coder.py", "executor.py"})
ScoreFunction = Callable[[Path], float]
RegressionRunner = Callable[[Path], Mapping[str, Any]]


def _normalize_repo_path(value: str) -> str:
    normalized = value.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    parts = normalized.split("/")
    if (
        not normalized
        or normalized.startswith("/")
        or re.match(r"^[A-Za-z]:/", normalized)
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise ValueError(f"Unsafe repository path: {value!r}")
    return "/".join(parts)


@dataclass(frozen=True)
class CandidatePolicy:
    """Explicit write authority for one recursive-improvement experiment."""

    editable_targets: frozenset[str] = DEFAULT_EDITABLE_TARGETS
    protected_paths: frozenset[str] = DEFAULT_PROTECTED_PATHS

    def assert_editable(self, target_file: str) -> str:
        target = _normalize_repo_path(target_file)
        for protected_entry in self.protected_paths:
            is_prefix = protected_entry.replace("\\", "/").endswith("/")
            protected = _normalize_repo_path(protected_entry.rstrip("/"))
            if is_prefix and (target == protected or target.startswith(protected + "/")):
                raise PermissionError(f"Candidate cannot edit protected path: {target}")
            if target == protected:
                raise PermissionError(f"Candidate cannot edit protected path: {target}")

        editable = {_normalize_repo_path(item) for item in self.editable_targets}
        if target not in editable:
            raise PermissionError(f"Candidate target is outside explicit write authority: {target}")
        return target

    def validate_patch_data(self, patch_data: Mapping[str, Any]) -> tuple[str, str]:
        if not isinstance(patch_data, Mapping):
            raise TypeError("Coder result must be a mapping")
        if patch_data.get("status") == "blocked":
            raise ValueError("Coder returned a blocked candidate")

        declared_target = self.assert_editable(str(patch_data.get("target_file") or ""))
        patch_text = str(patch_data.get("patch") or "").strip()
        if not patch_text:
            raise ValueError("Coder returned an empty patch")
        diff_target = extract_target_file(patch_text)
        if not diff_target:
            raise ValueError("Candidate patch does not declare a target file")
        diff_target = self.assert_editable(diff_target)
        if diff_target != declared_target:
            raise ValueError(
                f"Coder target {declared_target!r} does not match diff target {diff_target!r}"
            )
        return declared_target, patch_text


@dataclass(frozen=True)
class CandidateProposal:
    task_id: str
    task_note: str
    plan: Mapping[str, Any]
    patch_data: Mapping[str, Any]
    target_file: str
    patch_text: str


def propose_candidate(
    task: Mapping[str, Any],
    *,
    planner: Any,
    coder: Any,
    policy: CandidatePolicy | None = None,
) -> CandidateProposal:
    """Use Hive's existing planner/coder APIs without applying their patch."""

    policy = policy or CandidatePolicy()
    task_id = str(task.get("id") or "").strip()
    if not task_id:
        raise ValueError("Candidate task requires an id")

    plan = planner.plan_task(dict(task))
    if not isinstance(plan, Mapping):
        raise TypeError("Planner result must be a mapping")
    if plan.get("status") == "blocked":
        raise RuntimeError(f"Planner blocked candidate generation: {plan.get('llm_error') or 'unknown'}")

    patch_data = coder.generate_patch(dict(task), dict(plan))
    target_file, patch_text = policy.validate_patch_data(patch_data)
    return CandidateProposal(
        task_id=task_id,
        task_note=str(task.get("note") or ""),
        plan=dict(plan),
        patch_data=dict(patch_data),
        target_file=target_file,
        patch_text=patch_text,
    )


def make_regression_runner(cases_dir: str | Path) -> RegressionRunner:
    """Adapt Hive's recorded regression API to an isolated repository root."""

    cases_dir = Path(cases_dir).resolve()

    def run(repo_root: Path) -> Mapping[str, Any]:
        return RegressionGate(cases_dir).run_all(repo_root)

    return run


def evaluate_proposal(
    proposal: CandidateProposal,
    *,
    repo_root: str | Path,
    scorer: ScoreFunction | None = None,
    regression_runner: RegressionRunner | None = None,
    archive_path: str | Path | None = None,
    policy: CandidatePolicy | None = None,
    n: int = 3,
    k: float = 2.0,
    minimum_effect: float = 0.0,
) -> dict[str, Any]:
    """Evaluate a proposal in a disposable variant and never promote it."""

    policy = policy or CandidatePolicy()
    target_file, patch_text = policy.validate_patch_data(proposal.patch_data)
    if target_file != proposal.target_file or patch_text != proposal.patch_text:
        raise ValueError("Proposal fields no longer match validated coder output")

    repo_root = Path(repo_root).resolve()
    archive_path = Path(
        archive_path
        or repo_root.parent / f"{repo_root.name}-recursive-improvement-evidence.jsonl"
    )
    regression_runner = regression_runner or make_regression_runner(
        repo_root / "validation" / "regressions"
    )
    regression_capture: dict[str, Any] = {}

    def verify_regressions(variant_root: Path, _target_file: str) -> tuple[bool, str]:
        report = dict(regression_runner(variant_root))
        regression_capture["report"] = report
        passed = report.get("passed") is True
        passed_count = int(report.get("passed_count") or 0)
        case_count = int(report.get("case_count") or 0)
        return passed, f"recorded regressions: {passed_count}/{case_count} passed"

    record = evaluate(
        patch_text,
        proposal.task_note,
        repo_root=repo_root,
        scorer=scorer,
        verifier=verify_regressions,
        archive_path=archive_path,
        n=n,
        k=k,
        minimum_effect=minimum_effect,
        protected_paths=policy.protected_paths,
    )
    record["prototype_status"] = "candidate_evaluation_only"
    record["recursive_self_improvement_proven"] = False
    record["promotion_allowed"] = False
    record["planner_source"] = proposal.plan.get("source")
    record["coder_source"] = proposal.patch_data.get("source")
    record["regression_report"] = regression_capture.get("report")
    record["policy"] = {
        **dict(record.get("policy") or {}),
        "editable_targets": sorted(policy.editable_targets),
        "protected_paths": sorted(policy.protected_paths),
        "automatic_promotion": False,
    }
    append_event(
        {
            "event_type": "recursive_improvement_candidate_evaluation",
            "schema_version": 1,
            "evaluation_id": record.get("evaluation_id"),
            "task_id": proposal.task_id,
            "target_file": proposal.target_file,
            "patch_sha256": sha256_text(proposal.patch_text),
            "decision": record.get("decision"),
            "reason": record.get("reason"),
            "prototype_status": record["prototype_status"],
            "promotion_allowed": False,
            "recursive_self_improvement_proven": False,
            "planner_source": record.get("planner_source"),
            "coder_source": record.get("coder_source"),
            "regression_report": record.get("regression_report"),
            "policy": record["policy"],
        },
        archive_path,
    )
    return record


def concise_result(record: Mapping[str, Any]) -> str:
    """Stable, human-reviewable summary for logs and PR evidence."""

    return json.dumps(
        {
            "evaluation_id": record.get("evaluation_id"),
            "decision": record.get("decision"),
            "reason": record.get("reason"),
            "target_file": record.get("target_file"),
            "prototype_status": record.get("prototype_status"),
            "promotion_allowed": record.get("promotion_allowed"),
            "recursive_self_improvement_proven": record.get(
                "recursive_self_improvement_proven"
            ),
        },
        sort_keys=True,
    )

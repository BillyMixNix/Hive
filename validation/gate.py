"""Empirical validation gate with isolated variants and Pilot-controlled deployment.

The gate can recommend a patch as a deployment *candidate*. It never writes an
accepted candidate into the live repository. Promotion is a separate operation
that requires explicit ``pilot_approved=True`` and verifies that the live source
has not changed since evaluation.
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Callable

from validation.archive import append_event, deployments_for, find_evaluation
from validation.scoring import compute_stats
from validation.variant import (
    apply_patch_to_variant,
    discard_variant,
    extract_target_file,
    make_variant,
    self_verify,
    sha256_text,
)


ScoreFunction = Callable[[Path], float]
VerifyFunction = Callable[[Path, str], tuple[bool, str] | bool]

DEFAULT_PROTECTED_PATHS = frozenset(
    {
        "benchmark_harness.py",
        "benchmark_pack.py",
        "validation/gate.py",
        "validation/scoring.py",
        "validation/variant.py",
        "validation/archive.py",
    }
)
_SCORE_SENTINEL = "__HIVE_GATE_SCORE__"


def default_score_repo(repo_root: Path, *, timeout: int = 300) -> float:
    """Score a repository with its frozen reliability pack in a subprocess."""

    code = (
        "import json\n"
        "from benchmark_harness import ReliabilityBenchmarkHarness\n"
        "report = ReliabilityBenchmarkHarness().run_pack(include_reproducibility=False)\n"
        "summary = report['summary']\n"
        "total = int(summary['total_cases'])\n"
        "passed = int(summary['passed_cases'])\n"
        "score = (passed / total) if total else 0.0\n"
        f"print('{_SCORE_SENTINEL}' + json.dumps("
        "{'score': score, 'passed': passed, 'total': total}, sort_keys=True))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(repo_root),
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "benchmark subprocess failed: "
            + (completed.stderr.strip() or completed.stdout.strip() or "unknown error")
        )

    payload = None
    for line in reversed(completed.stdout.splitlines()):
        if line.startswith(_SCORE_SENTINEL):
            payload = json.loads(line[len(_SCORE_SENTINEL) :])
            break
    if payload is None:
        raise RuntimeError("benchmark subprocess did not emit a gate score")
    return float(payload["score"])


def _is_protected(target_file: str, protected_paths: set[str] | frozenset[str]) -> bool:
    normalized = target_file.replace("\\", "/").lstrip("./")
    return normalized in protected_paths or normalized.startswith(".github/workflows/")


def _archive_default(repo_root: Path) -> Path:
    return repo_root / "validation" / "archive.jsonl"


def evaluate(
    patch_text: str,
    task_note: str,
    *,
    repo_root: str | Path,
    scorer: ScoreFunction | None = None,
    verifier: VerifyFunction | None = None,
    archive_path: str | Path | None = None,
    n: int = 3,
    k: float = 2.0,
    minimum_effect: float = 0.0,
    protected_paths: set[str] | frozenset[str] = DEFAULT_PROTECTED_PATHS,
    evaluation_id: str | None = None,
) -> dict:
    """Evaluate one single-file patch without modifying the live repository."""

    repo_root = Path(repo_root).resolve()
    archive_path = Path(archive_path or _archive_default(repo_root))
    scorer = scorer or default_score_repo
    evaluation_id = evaluation_id or f"eval_{uuid.uuid4().hex}"
    record = {
        "event_type": "evaluation",
        "schema_version": 1,
        "evaluation_id": evaluation_id,
        "task_note": task_note,
        "target_file": None,
        "decision": "reject",
        "deployment_status": "not_deployed",
        "reason": "",
        "self_verified": False,
        "verification_reason": "",
        "baseline_scores": [],
        "variant_scores": [],
        "policy": {
            "n": n,
            "k": k,
            "minimum_effect": minimum_effect,
            "pilot_approval_required": True,
            "single_file_only": True,
        },
        "patch_text": patch_text,
    }

    variant_root = None
    try:
        if n < 2:
            raise ValueError("Empirical scoring requires at least two runs per side")
        if not repo_root.is_dir():
            raise FileNotFoundError(f"Repository root not found: {repo_root}")

        target_file = extract_target_file(patch_text)
        if not target_file:
            raise ValueError("Patch does not declare a target file")
        record["target_file"] = target_file

        if _is_protected(target_file, protected_paths):
            record["reason"] = f"grader_tamper_rejected: protected path {target_file}"
            return record

        live_target = repo_root / target_file
        if not live_target.is_file():
            record["reason"] = f"target_missing: {target_file}"
            return record

        pre_patch_content = live_target.read_text(encoding="utf-8")
        record["pre_patch_sha256"] = sha256_text(pre_patch_content)
        record["pre_patch_content"] = pre_patch_content

        variant_root = make_variant(repo_root, evaluation_id)
        _, _, post_patch_content = apply_patch_to_variant(
            variant_root,
            patch_text,
            target_file=target_file,
        )
        record["candidate_sha256"] = sha256_text(post_patch_content)
        record["candidate_content"] = post_patch_content

        verified, verification_reason = self_verify(
            variant_root,
            target_file=target_file,
            verifier=verifier,
        )
        record["self_verified"] = verified
        record["verification_reason"] = verification_reason
        if not verified:
            record["reason"] = f"self_verification_failed: {verification_reason}"
            return record

        baseline_scores = [float(scorer(repo_root)) for _ in range(n)]
        variant_scores = [float(scorer(variant_root)) for _ in range(n)]
        stats = compute_stats(
            baseline_scores,
            variant_scores,
            k=k,
            minimum_effect=minimum_effect,
        )
        record.update(stats)

        if stats["significant_improvement"]:
            record["decision"] = "candidate"
            record["reason"] = (
                f"measured improvement {stats['delta']:.6f} exceeded "
                f"threshold {stats['acceptance_threshold']:.6f}; "
                "awaiting Pilot approval"
            )
        else:
            record["reason"] = (
                f"no significant gain: delta {stats['delta']:.6f} <= "
                f"threshold {stats['acceptance_threshold']:.6f}"
            )
        return record

    except Exception as exc:
        record["reason"] = f"evaluation_error: {type(exc).__name__}: {exc}"
        return record
    finally:
        append_event(record, archive_path)
        if variant_root is not None:
            discard_variant(variant_root)


def promote_candidate(
    evaluation_id: str,
    *,
    repo_root: str | Path,
    archive_path: str | Path | None = None,
    pilot_approved: bool = False,
) -> dict:
    """Deploy an archived candidate only after explicit Pilot approval."""

    if pilot_approved is not True:
        raise PermissionError("Pilot approval is required to deploy a candidate")

    repo_root = Path(repo_root).resolve()
    archive_path = Path(archive_path or _archive_default(repo_root))
    evaluation = find_evaluation(evaluation_id, archive_path)
    if evaluation is None:
        raise KeyError(f"Unknown evaluation: {evaluation_id}")
    if evaluation.get("decision") != "candidate":
        raise ValueError(f"Evaluation {evaluation_id} is not a deployment candidate")
    if deployments_for(evaluation_id, archive_path):
        raise ValueError(f"Evaluation {evaluation_id} was already deployed")

    target_file = evaluation["target_file"]
    target_path = repo_root / target_file
    if not target_path.is_file():
        raise FileNotFoundError(f"Live target no longer exists: {target_file}")

    current_content = target_path.read_text(encoding="utf-8")
    current_hash = sha256_text(current_content)
    expected_hash = evaluation.get("pre_patch_sha256")
    if current_hash != expected_hash:
        raise RuntimeError(
            "Live target changed after evaluation; re-evaluate before deployment"
        )

    candidate_content = evaluation.get("candidate_content")
    if not isinstance(candidate_content, str):
        raise ValueError("Archived candidate content is missing")

    target_path.write_text(candidate_content, encoding="utf-8")
    deployment = {
        "event_type": "deployment",
        "schema_version": 1,
        "deployment_id": f"deploy_{uuid.uuid4().hex}",
        "evaluation_id": evaluation_id,
        "target_file": target_file,
        "pilot_approved": True,
        "pre_deploy_sha256": current_hash,
        "deployed_sha256": sha256_text(candidate_content),
        "status": "deployed",
    }
    return append_event(deployment, archive_path)


def rollback_deployment(
    evaluation_id: str,
    *,
    repo_root: str | Path,
    archive_path: str | Path | None = None,
    pilot_approved: bool = False,
) -> dict:
    """Restore the archived pre-patch content for a deployed candidate."""

    if pilot_approved is not True:
        raise PermissionError("Pilot approval is required to roll back a deployment")

    repo_root = Path(repo_root).resolve()
    archive_path = Path(archive_path or _archive_default(repo_root))
    evaluation = find_evaluation(evaluation_id, archive_path)
    if evaluation is None:
        raise KeyError(f"Unknown evaluation: {evaluation_id}")
    deployments = deployments_for(evaluation_id, archive_path)
    if not deployments:
        raise ValueError(f"Evaluation {evaluation_id} has not been deployed")

    target_file = evaluation["target_file"]
    target_path = repo_root / target_file
    pre_patch_content = evaluation.get("pre_patch_content")
    if not isinstance(pre_patch_content, str):
        raise ValueError("Archived rollback content is missing")

    target_path.write_text(pre_patch_content, encoding="utf-8")
    event = {
        "event_type": "rollback",
        "schema_version": 1,
        "rollback_id": f"rollback_{uuid.uuid4().hex}",
        "evaluation_id": evaluation_id,
        "target_file": target_file,
        "pilot_approved": True,
        "restored_sha256": sha256_text(pre_patch_content),
        "status": "rolled_back",
    }
    return append_event(event, archive_path)

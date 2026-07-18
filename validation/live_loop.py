"""Bridge Hive's normal patch workflow to the empirical validation gate.

The live adapter gives the gate task-level headroom without weakening the
regression standard:

* completion cues provide the measurable task score;
* the frozen reliability benchmark is a non-regression guard;
* successful evaluations become candidates, never automatic deployments;
* deployment and rollback still require an explicit Pilot action.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable

from validation.gate import (
    DEFAULT_PROTECTED_PATHS,
    default_score_repo,
    evaluate,
    promote_candidate,
    rollback_deployment,
)


BenchmarkScorer = Callable[[Path], float]
LIVE_PROTECTED_PATHS = frozenset(
    set(DEFAULT_PROTECTED_PATHS)
    | {
        "validation/live_loop.py",
        "validation/ab_run.py",
    }
)


def normalize_completion_cues(cues: Iterable[object] | None) -> list[str]:
    """Return stable, non-empty, de-duplicated completion cues."""

    normalized: list[str] = []
    seen: set[str] = set()
    for cue in cues or []:
        value = str(cue or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def completion_score(repo_root: str | Path, target_file: str, cues: Iterable[object]) -> float:
    """Score how many explicit task completion cues exist in the target file."""

    repo_root = Path(repo_root)
    normalized = normalize_completion_cues(cues)
    if not normalized:
        return 0.0

    target = repo_root / target_file
    if not target.is_file():
        return 0.0
    text = target.read_text(encoding="utf-8")
    matched = sum(1 for cue in normalized if cue in text)
    return matched / len(normalized)


def _compact_evaluation(record: dict) -> dict:
    """Keep decision evidence in runtime memory without duplicating source files."""

    keys = (
        "evaluation_id",
        "target_file",
        "decision",
        "deployment_status",
        "reason",
        "self_verified",
        "verification_reason",
        "baseline_scores",
        "variant_scores",
        "baseline_mean",
        "variant_mean",
        "baseline_variance",
        "variant_variance",
        "delta",
        "standard_error",
        "noise_band",
        "minimum_effect",
        "acceptance_threshold",
        "significant_improvement",
        "pre_patch_sha256",
        "candidate_sha256",
        "policy",
        "regression_baseline_score",
    )
    return {key: record.get(key) for key in keys if key in record}


def evaluate_patch_result(
    result: dict,
    *,
    task_note: str,
    repo_root: str | Path,
    completion_cues: Iterable[object] | None,
    archive_path: str | Path | None = None,
    benchmark_scorer: BenchmarkScorer | None = None,
    n: int = 2,
    k: float = 0.0,
    minimum_effect: float = 0.25,
) -> dict:
    """Evaluate a generated patch and return a candidate or blocked result.

    The benchmark score is used as a floor rather than as the improvement score.
    This avoids the old saturated-benchmark problem: a repository already scoring
    1.0 can still demonstrate task-specific improvement, but any benchmark
    regression rejects the candidate before scoring.
    """

    enriched = dict(result or {})
    if enriched.get("status") == "blocked":
        enriched["empirical_validation"] = {
            "decision": "skipped",
            "reason": "coder_blocked_before_empirical_evaluation",
        }
        return enriched

    patch_text = str(enriched.get("patch") or "").strip()
    target_file = str(enriched.get("target_file") or "").strip()
    cues = normalize_completion_cues(completion_cues)

    if not patch_text or not target_file:
        enriched.update(
            status="blocked",
            validation_outcome="failed",
            llm_error="empirical_gate_input_missing: patch or target file absent",
            empirical_validation={
                "decision": "reject",
                "reason": "empirical_gate_input_missing: patch or target file absent",
            },
        )
        return enriched

    if not cues:
        enriched.update(
            status="blocked",
            validation_outcome="failed",
            llm_error="empirical_gate_requires_completion_cues",
            empirical_validation={
                "decision": "reject",
                "reason": "empirical_gate_requires_completion_cues",
            },
        )
        return enriched

    repo_root = Path(repo_root).resolve()
    benchmark_scorer = benchmark_scorer or default_score_repo

    try:
        regression_baseline = float(benchmark_scorer(repo_root))
    except Exception as exc:
        reason = f"empirical_regression_baseline_failed: {type(exc).__name__}: {exc}"
        enriched.update(
            status="blocked",
            validation_outcome="failed",
            llm_error=reason,
            empirical_validation={"decision": "reject", "reason": reason},
        )
        return enriched

    variant_benchmark_cache: dict[str, float] = {}

    def regression_verifier(variant_root: Path, _target_file: str):
        cache_key = str(Path(variant_root).resolve())
        try:
            variant_score = variant_benchmark_cache.get(cache_key)
            if variant_score is None:
                variant_score = float(benchmark_scorer(Path(variant_root)))
                variant_benchmark_cache[cache_key] = variant_score
        except Exception as exc:
            return False, f"regression benchmark failed: {type(exc).__name__}: {exc}"

        if variant_score + 1e-12 < regression_baseline:
            return (
                False,
                f"regression detected: variant={variant_score:.6f} "
                f"baseline={regression_baseline:.6f}",
            )
        return (
            True,
            f"regression guard passed: variant={variant_score:.6f} "
            f"baseline={regression_baseline:.6f}",
        )

    def task_scorer(candidate_root: Path) -> float:
        return completion_score(candidate_root, target_file, cues)

    record = evaluate(
        patch_text,
        task_note,
        repo_root=repo_root,
        scorer=task_scorer,
        verifier=regression_verifier,
        archive_path=archive_path,
        n=n,
        k=k,
        minimum_effect=minimum_effect,
        protected_paths=LIVE_PROTECTED_PATHS,
    )
    record["regression_baseline_score"] = regression_baseline
    compact = _compact_evaluation(record)

    enriched["evaluation_id"] = record.get("evaluation_id")
    enriched["empirical_validation"] = compact
    enriched["validation_outcome"] = record.get("decision")

    if record.get("decision") == "candidate":
        enriched["status"] = "candidate"
        enriched.pop("llm_error", None)
    else:
        enriched["status"] = "blocked"
        enriched["llm_error"] = record.get("reason") or "empirical_gate_rejected"
        enriched["failure_code"] = "empirical_gate_rejected"

    return enriched


def _evaluation_id_from_metadata(metadata: dict) -> str:
    evaluation_id = metadata.get("evaluation_id")
    if not evaluation_id:
        evaluation_id = (metadata.get("empirical_validation") or {}).get("evaluation_id")
    if not evaluation_id:
        raise ValueError("Patch has no empirical evaluation candidate")
    return str(evaluation_id)


def deploy_approved_patch(
    metadata: dict,
    *,
    repo_root: str | Path,
    archive_path: str | Path | None = None,
) -> dict:
    """Deploy an evaluated candidate after the explicit Pilot apply command."""

    return promote_candidate(
        _evaluation_id_from_metadata(metadata),
        repo_root=repo_root,
        archive_path=archive_path,
        pilot_approved=True,
    )


def rollback_approved_patch(
    metadata: dict,
    *,
    repo_root: str | Path,
    archive_path: str | Path | None = None,
) -> dict:
    """Roll back an evaluated deployment after the explicit Pilot command."""

    return rollback_deployment(
        _evaluation_id_from_metadata(metadata),
        repo_root=repo_root,
        archive_path=archive_path,
        pilot_approved=True,
    )

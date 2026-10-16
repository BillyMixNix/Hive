from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class PromotionEvidence:
    integrity_passed: bool
    prior_capabilities_preserved: bool
    triggering_failure_solved: bool
    mutation_checks_passed: bool
    g0_transfer_score: int
    g1_transfer_score: int


def decide_promotion(evidence: PromotionEvidence) -> dict[str, Any]:
    transfer_improved = evidence.g1_transfer_score > evidence.g0_transfer_score
    promoted = (
        evidence.integrity_passed
        and evidence.prior_capabilities_preserved
        and evidence.triggering_failure_solved
        and evidence.mutation_checks_passed
        and transfer_improved
    )
    reasons = []
    if not evidence.integrity_passed:
        reasons.append("INTEGRITY_FAILED")
    if not evidence.prior_capabilities_preserved:
        reasons.append("REJECTED_REGRESSION")
    if not evidence.triggering_failure_solved:
        reasons.append("REJECTED_NO_GAIN")
    if not evidence.mutation_checks_passed:
        reasons.append("REJECTED_MUTATION_CHECK")
    if not transfer_improved:
        reasons.append("REJECTED_NO_TRANSFER_GAIN")
    return {
        "promoted": promoted,
        "disposition": "PROMOTED" if promoted else "REJECTED",
        "reasons": reasons,
        "transfer_improved": transfer_improved,
        "evidence": asdict(evidence),
    }

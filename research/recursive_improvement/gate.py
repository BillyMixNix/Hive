"""Conservative, reproducible selection of candidate self-improvements.

This module deliberately does not execute generated code or modify the repository.
A separate, isolated runner must produce the scored JSON reports.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from statistics import mean
from typing import Iterable


@dataclass(frozen=True)
class Trial:
    case_id: str
    correct: bool
    cost: float
    latency_ms: float

    def __post_init__(self):
        if not isinstance(self.case_id, str) or not self.case_id.strip() or type(self.correct) is not bool:
            raise ValueError("Invalid trial identity or correctness type")
        for measurement in (self.cost, self.latency_ms):
            if type(measurement) not in (int, float) or not math.isfinite(measurement) or measurement < 0:
                raise ValueError("Measurements must be finite nonnegative numbers")


@dataclass(frozen=True)
class Decision:
    accepted: bool
    reason: str
    baseline_accuracy: float
    candidate_accuracy: float
    baseline_cost: float
    candidate_cost: float


def evaluate_candidate(
    baseline: Iterable[Trial],
    candidate: Iterable[Trial],
    *,
    min_cases: int = 20,
    min_accuracy_gain: float = 0.05,
    max_cost_increase: float = 0.10,
) -> Decision:
    """Compare matched, independent evaluation trials; fail closed.

    Caller must enforce held-out tasks, identical task conditions, and isolation.
    This deterministic gate is not a statistical significance test.
    """
    if (type(min_cases) is not int or min_cases < 1
            or any(type(x) not in (int, float) or not math.isfinite(x) or x < 0
                   for x in (min_accuracy_gain, max_cost_increase))):
        raise ValueError("Invalid acceptance thresholds")
    base, cand = list(baseline), list(candidate)
    base_ids = [t.case_id for t in base]
    cand_ids = [t.case_id for t in cand]
    if len(base) < min_cases or len(base_ids) != len(set(base_ids)):
        raise ValueError("Insufficient or duplicate baseline cases")
    if len(cand_ids) != len(set(cand_ids)) or set(base_ids) != set(cand_ids):
        raise ValueError("Candidate must match unique baseline case IDs")
    b_acc = mean(t.correct for t in base)
    c_acc = mean(t.correct for t in cand)
    b_cost = sum(t.cost for t in base)
    c_cost = sum(t.cost for t in cand)
    if not math.isfinite(b_cost) or not math.isfinite(c_cost):
        raise ValueError("Aggregate costs must be finite")
    gain = c_acc - b_acc
    cost_ok = c_cost <= b_cost * (1 + max_cost_increase)
    # When baseline cost is zero, no positive cost is allowed.
    accepted = gain >= min_accuracy_gain and cost_ok
    reason = (
        "accepted: accuracy gain and cost budget satisfied"
        if accepted else
        "rejected: accuracy gain below threshold" if gain < min_accuracy_gain
        else "rejected: cost budget exceeded"
    )
    return Decision(accepted, reason, b_acc, c_acc, b_cost, c_cost)

"""Statistics for Hive's empirical validation gate."""

from __future__ import annotations

import math
import statistics
from typing import Iterable


def _coerce_scores(values: Iterable[float], name: str) -> list[float]:
    scores = [float(value) for value in values]
    if len(scores) < 2:
        raise ValueError(f"{name} requires at least two scores")
    if any(not math.isfinite(value) for value in scores):
        raise ValueError(f"{name} contains a non-finite score")
    return scores


def compute_stats(
    baseline_scores: Iterable[float],
    variant_scores: Iterable[float],
    *,
    k: float = 2.0,
    minimum_effect: float = 0.0,
) -> dict:
    """Compare repeated scores using Welch's standard error of the mean difference.

    A variant is significant when its mean improvement is greater than both:
      * ``minimum_effect``; and
      * ``k * standard_error``.

    Deterministic scorers have zero standard error, so a strictly positive
    improvement can pass when ``minimum_effect`` is zero.
    """

    baseline = _coerce_scores(baseline_scores, "baseline_scores")
    variant = _coerce_scores(variant_scores, "variant_scores")
    if k < 0:
        raise ValueError("k must be non-negative")
    if minimum_effect < 0:
        raise ValueError("minimum_effect must be non-negative")

    baseline_mean = statistics.fmean(baseline)
    variant_mean = statistics.fmean(variant)
    baseline_variance = statistics.variance(baseline)
    variant_variance = statistics.variance(variant)
    standard_error = math.sqrt(
        (baseline_variance / len(baseline)) + (variant_variance / len(variant))
    )
    noise_band = k * standard_error
    delta = variant_mean - baseline_mean
    threshold = max(float(minimum_effect), noise_band)

    return {
        "baseline_scores": baseline,
        "variant_scores": variant,
        "baseline_mean": baseline_mean,
        "variant_mean": variant_mean,
        "baseline_variance": baseline_variance,
        "variant_variance": variant_variance,
        "delta": delta,
        "standard_error": standard_error,
        "noise_band": noise_band,
        "minimum_effect": float(minimum_effect),
        "acceptance_threshold": threshold,
        "significant_improvement": delta > threshold,
    }

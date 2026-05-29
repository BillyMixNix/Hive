"""
Scoring helpers for the empirical validation gate.

Run the benchmark harness N times, compute mean/stdev, derive noise band.
k≈2 gives roughly 2σ confidence that the delta is real.
"""

import statistics


def _stdev_safe(values):
    if len(values) < 2:
        return 0.0
    try:
        return statistics.stdev(values)
    except statistics.StatisticsError:
        return 0.0


def pooled_stdev(base_scores, var_scores):
    """Standard deviation of the combined baseline + variant score distribution."""
    combined = list(base_scores) + list(var_scores)
    return _stdev_safe(combined)


def compute_stats(base_scores, var_scores, k=2.0):
    """
    Return all numbers needed by the accept/reject decision.

    Acceptance criterion: delta > noise_band
      where noise_band = k * pooled_stdev(base_scores, var_scores)
    """
    base_mean = statistics.mean(base_scores) if base_scores else 0.0
    var_mean = statistics.mean(var_scores) if var_scores else 0.0
    delta = var_mean - base_mean
    band = k * pooled_stdev(base_scores, var_scores)
    return {
        "baseline_scores": list(base_scores),
        "variant_scores": list(var_scores),
        "baseline_mean": round(base_mean, 4),
        "variant_mean": round(var_mean, 4),
        "delta": round(delta, 4),
        "noise_band": round(band, 4),
        "k": k,
    }

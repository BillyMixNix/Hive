"""
Scoring helpers for the empirical validation gate.

Run the benchmark harness N times, compute mean and standard error,
derive noise band.  k≈2 gives roughly 2σ confidence that the delta is real.

IMPORTANT — why pooled stdev was wrong:
  The old code computed stdev([base_scores + var_scores]) as the noise
  estimate.  That merges the two groups before measuring spread, so a
  larger real improvement *inflates* the noise band and becomes harder to
  detect.  For N=1 this makes acceptance mathematically impossible:
      noise_band = k * stdev([a, b]) = k * |a-b|/√2 ≈ 1.414 * |delta|
      so delta > noise_band ↔ delta > 1.414 * delta → 1 > 1.414 → always False.

  The correct statistic is the standard error of the *difference in means*
  (Welch's method):
      se = sqrt(Var(base)/n_base + Var(var)/n_var)
  This shrinks with N (more runs → tighter bound) and is independent of
  effect size.  With deterministic runs (Var=0), se=0 and any positive
  delta is accepted — correct behaviour.

Minimum N: 2 per side.  Spec recommends 5.
"""

import math
import statistics

MIN_RUNS = 2


def standard_error_of_difference(base_scores, var_scores):
    """
    Standard error of (mean_variant - mean_baseline) using Welch's method.

    Returns 0.0 when either side has fewer than MIN_RUNS points.
    Call compute_stats() which enforces the minimum and raises clearly.
    """
    n_b, n_v = len(base_scores), len(var_scores)
    if n_b < MIN_RUNS or n_v < MIN_RUNS:
        return 0.0
    var_b = statistics.variance(base_scores)
    var_v = statistics.variance(var_scores)
    return math.sqrt(var_b / n_b + var_v / n_v)


def compute_stats(base_scores, var_scores, k=2.0):
    """
    Return all numbers needed by the accept/reject decision.

    Acceptance criterion: delta > noise_band
      where noise_band = k * standard_error_of_difference(base, var)

    Raises ValueError when either side has fewer than MIN_RUNS (2) points.
    The spec recommends N=5; raise N if you see accepted patches that do
    not replicate.
    """
    n_b, n_v = len(base_scores), len(var_scores)
    if n_b < MIN_RUNS or n_v < MIN_RUNS:
        raise ValueError(
            f"Need ≥ {MIN_RUNS} runs per side for noise estimation "
            f"(got base={n_b}, var={n_v}). "
            f"Set N≥{MIN_RUNS}; spec recommends N=5. "
            f"With N=1, noise_band = k × |delta| × √2 ≥ |delta|, "
            f"making acceptance mathematically impossible."
        )

    base_mean = statistics.mean(base_scores)
    var_mean = statistics.mean(var_scores)
    delta = var_mean - base_mean
    se = standard_error_of_difference(base_scores, var_scores)
    noise_band = k * se

    return {
        "baseline_scores": list(base_scores),
        "variant_scores": list(var_scores),
        "baseline_mean": round(base_mean, 4),
        "variant_mean": round(var_mean, 4),
        "delta": round(delta, 4),
        "noise_band": round(noise_band, 4),
        "se_diff": round(se, 4),
        "k": k,
    }

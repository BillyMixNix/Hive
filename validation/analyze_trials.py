"""Post-hoc BLOCKED (stratified-by-pair) analysis of a .trials.jsonl from lesson_study.

Pooling all trials ignores that pairs are different tasks with different baseline
retry levels. This stratifies by pair: van Elteren (stratified Wilcoxon) on retries,
Cochran-Mantel-Haenszel on solve rate, and a cluster bootstrap CI on the average
within-pair retry reduction. No model calls — runs on saved data in <1s.

Usage:
    python -m validation.analyze_trials results/lesson_diag.trials.jsonl
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from validation.lesson_study import blocked_analysis  # reuse the same math


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m validation.analyze_trials <trials.jsonl>")
    rows = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
    b = blocked_analysis(rows)
    n_on = sum(1 for r in rows if r["arm"] == "on")
    n_off = sum(1 for r in rows if r["arm"] == "off")
    print(f"trials: {n_on} ON / {n_off} OFF across {len(b['per_pair_retry_reduction_off_minus_on'])} pairs\n")
    lo, hi = b["retries_within_pair_reduction_95ci"]
    print("BLOCKED (stratified by pair):")
    print(f"  within-pair retry reduction (off-on): {b['retries_within_pair_mean_reduction_off_minus_on']:+.3f}"
          f"  95% CI [{lo:.3f}, {hi:.3f}]   <- CI excluding 0 => real within-task effect")
    print(f"  van Elteren (stratified Wilcoxon), retries: z={b['retries_van_elteren_z']:.3f}  p={b['retries_van_elteren_p']:.4f}")
    print(f"  CMH, solve rate:                            chi2={b['solve_cmh_chi2']:.3f}  p={b['solve_cmh_p']:.4f}")
    print("\n  per-pair retry reduction (off-on):")
    for k, v in b["per_pair_retry_reduction_off_minus_on"].items():
        print(f"    {k:<14} {v:+.3f}")


if __name__ == "__main__":
    main()

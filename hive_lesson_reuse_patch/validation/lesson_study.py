"""
Live lesson-efficacy study — the "big enough test to prove the hypothesis".

Hypothesis under test
---------------------
    Accumulated failure lessons make Hive's coder measurably better at NEW tasks:
    it solves them in fewer attempts (and/or solves more of them within a fixed
    retry budget) when a relevant lesson is present than when it is not.

Why this design (read before trusting any number)
--------------------------------------------------
1.  REAL MODEL, NOT A MOCK.  The deterministic CI test
    (tests/test_lesson_reuse_sequence.py) proves the *plumbing* — lessons get
    recorded, retrieved, injected, and change behaviour.  It cannot prove a real
    model benefits, because the mock is rigged to react to guidance.  This study
    runs the live coder (Ollama / qwen2.5-coder:7b) with `live_coder=True`, so the
    only thing that differs between arms is whether a lesson is in the store.

2.  GENERALIZATION, NOT MEMORIZATION.  Each pair seeds a lesson whose origin file
    differs from the reuse task's file.  A win therefore requires a *generalized*
    lesson to transfer across files — not exact-match recall.

3.  THE METRIC IS RETRIES-TO-SOLVE, NOT FIRST-ATTEMPT SUCCESS.  Verified
    empirically against this codebase: on a task's FIRST attempt `failure_code`
    is None, so `LessonMemory.get_retry_lessons` skips `find_relevant_lessons`
    (HiveLessonMemory.py ~line 510) and only `get_recent_lessons(file=...)` runs,
    which filters by exact file.  Cross-file generalized lessons are thus injected
    only on attempt 2+ (after the task fails once and yields a matching
    failure_code).  So Hive's cross-file learning is *reactive*: it reduces
    retries, it does not lift first-attempt success.  Measuring first-attempt
    success would understate (and misframe) the real effect.

4.  TWO ARMS, N REPEATS, STATISTICS.  For each pair we run the reuse task N times
    with lessons ON (store seeded) and N times with lessons OFF (empty store),
    pooled across pairs.  We report mean retries, solve-rate-within-budget, the
    differences with bootstrap 95% CIs, a Mann-Whitney U on retries, and a
    two-proportion z on solve-rate.  Verdict requires the CI to exclude zero.

5.  CALIBRATION IS MANDATORY.  Because the author could not run the model, the
    starter cases are NOT guaranteed to sit in the sensitive band (baseline solve
    rate strictly between 0 and 1).  Run `--preflight` first; if a pair's OFF-arm
    solve rate is 0.0 or 1.0 there is no headroom and that pair proves nothing —
    adjust its difficulty (see LESSON_STUDY.md) before trusting the main run.

Usage
-----
    # 1) sanity + calibration (small N), checks injection fires and headroom:
    python -m validation.lesson_study --preflight --n 4

    # 2) full study (this is the proof; expect to run for a while):
    python -m validation.lesson_study --n 20 --budget 3 --out results/lesson_study.json

Requires a running Ollama with the model in hive_llm.DEFAULT_MODEL.
"""

import argparse
import json
import math
import random
import statistics
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from benchmark_harness import ReliabilityBenchmarkHarness
from validation.lesson_study_cases import build_pairs


# --------------------------------------------------------------------------- #
# Seeding
# --------------------------------------------------------------------------- #
def seed_lesson(session, spec):
    """Inject a crafted, trusted, GENERALIZED lesson (file=None) so it can transfer
    across files. Mirrors what organic promotion would eventually produce, but
    deterministically, so the experiment isolates 'lesson present vs absent'."""
    session["coder"].lesson_memory.add_lesson(
        file=None,
        change_type="diff_patch",
        failure_reason=spec["failure_code"],
        retry_instruction=spec["retry_instruction"],
        source="coder",
        failure_code=spec["failure_code"],
        lesson_level="generalized",
        promotion_state="trusted",
        times_used=5,
        success_after_use=4,
        trigger_pattern=spec.get("trigger_pattern"),
        fix_strategy=spec.get("fix_strategy"),
        context_requirements={},
    )


# --------------------------------------------------------------------------- #
# One trial
# --------------------------------------------------------------------------- #
def run_trial(pair, lessons_on, budget):
    """Run the reuse task once, live. Returns (solved: bool, retries: int)."""
    h = ReliabilityBenchmarkHarness()
    session = h._create_session(lessons_enabled=lessons_on)
    try:
        if lessons_on:
            seed_lesson(session, pair["lesson"])
        reuse = dict(pair["reuse"])
        reuse["live_coder"] = True
        reuse.setdefault("max_revisions", budget)
        res = h._run_one(session, reuse)
        solved = res.get("final_status") == "proposed"
        retries = int(res.get("retry_count", 0) or 0)
        return solved, retries
    finally:
        h._cleanup_session(session)


# --------------------------------------------------------------------------- #
# Statistics
# --------------------------------------------------------------------------- #
def _bootstrap_diff_ci(a, b, iters=10000, seed=0):
    """95% CI for mean(a) - mean(b) by bootstrap resampling."""
    rng = random.Random(seed)
    diffs = []
    for _ in range(iters):
        ra = [a[rng.randrange(len(a))] for _ in a]
        rb = [b[rng.randrange(len(b))] for _ in b]
        diffs.append(statistics.fmean(ra) - statistics.fmean(rb))
    diffs.sort()
    lo = diffs[int(0.025 * iters)]
    hi = diffs[int(0.975 * iters)]
    return lo, hi


def _mann_whitney_u(a, b):
    """Two-sided Mann-Whitney U with normal approximation. Returns (U, z, p)."""
    n1, n2 = len(a), len(b)
    if n1 == 0 or n2 == 0:
        return float("nan"), float("nan"), float("nan")
    combined = sorted([(v, 0) for v in a] + [(v, 1) for v in b])
    ranks = [0.0] * len(combined)
    i = 0
    while i < len(combined):
        j = i
        while j + 1 < len(combined) and combined[j + 1][0] == combined[i][0]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[k] = avg
        i = j + 1
    r1 = sum(r for r, (_, grp) in zip(ranks, combined) if grp == 0)
    u1 = r1 - n1 * (n1 + 1) / 2.0
    mu = n1 * n2 / 2.0
    sigma = math.sqrt(n1 * n2 * (n1 + n2 + 1) / 12.0)
    if sigma == 0:
        return u1, 0.0, 1.0
    z = (u1 - mu) / sigma
    p = 2 * (1 - _norm_cdf(abs(z)))
    return u1, z, p


def _two_prop_z(succ_a, n_a, succ_b, n_b):
    """Two-proportion z-test (a vs b). Returns (diff, z, p)."""
    if n_a == 0 or n_b == 0:
        return float("nan"), float("nan"), float("nan")
    pa, pb = succ_a / n_a, succ_b / n_b
    pool = (succ_a + succ_b) / (n_a + n_b)
    se = math.sqrt(pool * (1 - pool) * (1 / n_a + 1 / n_b))
    if se == 0:
        return pa - pb, 0.0, 1.0
    z = (pa - pb) / se
    p = 2 * (1 - _norm_cdf(abs(z)))
    return pa - pb, z, p


def _norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


# --------------------------------------------------------------------------- #
# Study
# --------------------------------------------------------------------------- #
def run_study(n, budget, pairs=None, out=None, preflight=False):
    pairs = pairs if pairs is not None else build_pairs()
    per_pair = []
    pooled = {"on_retries": [], "off_retries": [], "on_solved": [], "off_solved": []}

    for pair in pairs:
        on_r, off_r, on_s, off_s = [], [], [], []
        for _ in range(n):
            s, r = run_trial(pair, lessons_on=True, budget=budget)
            on_s.append(1 if s else 0); on_r.append(r)
            s, r = run_trial(pair, lessons_on=False, budget=budget)
            off_s.append(1 if s else 0); off_r.append(r)

        rec = {
            "name": pair["name"], "band": pair["band"],
            "seed_file": pair["lesson"].get("origin_file"),
            "reuse_file": pair["reuse"]["target_file"],
            "n": n, "budget": budget,
            "on_solve_rate": statistics.fmean(on_s), "off_solve_rate": statistics.fmean(off_s),
            "on_mean_retries": statistics.fmean(on_r), "off_mean_retries": statistics.fmean(off_r),
            "headroom_ok": 0.0 < statistics.fmean(off_s) < 1.0,
        }
        per_pair.append(rec)
        pooled["on_retries"] += on_r; pooled["off_retries"] += off_r
        pooled["on_solved"] += on_s; pooled["off_solved"] += off_s

        if preflight:
            inj = _injection_fires(pair)
            rec["injection_fires_on_retry"] = inj
            print(f"[preflight] {pair['name']:<28} off_solve={rec['off_solve_rate']:.2f} "
                  f"on_solve={rec['on_solve_rate']:.2f} headroom={'OK' if rec['headroom_ok'] else 'NONE'} "
                  f"injection={'OK' if inj else 'FAIL'}")

    # Pooled stats
    rr_lo, rr_hi = _bootstrap_diff_ci(pooled["off_retries"], pooled["on_retries"])  # off - on (>0 => lessons help)
    u, z, p_ret = _mann_whitney_u(pooled["off_retries"], pooled["on_retries"])
    diff_solve, z_s, p_solve = _two_prop_z(
        sum(pooled["on_solved"]), len(pooled["on_solved"]),
        sum(pooled["off_solved"]), len(pooled["off_solved"]),
    )
    retry_drop = statistics.fmean(pooled["off_retries"]) - statistics.fmean(pooled["on_retries"])
    solve_lift = statistics.fmean(pooled["on_solved"]) - statistics.fmean(pooled["off_solved"])

    helps = (rr_lo > 0) or (diff_solve > 0 and p_solve < 0.05)
    verdict = (
        "LESSONS HELP (significant)" if helps
        else "no significant effect — check preflight headroom/injection before concluding"
    )

    summary = {
        "n_per_arm_per_pair": n, "retry_budget": budget, "pairs": len(pairs),
        "pooled": {
            "mean_retries_off": statistics.fmean(pooled["off_retries"]),
            "mean_retries_on": statistics.fmean(pooled["on_retries"]),
            "retry_reduction_off_minus_on": retry_drop,
            "retry_reduction_95ci": [rr_lo, rr_hi],
            "mann_whitney_z": z, "mann_whitney_p": p_ret,
            "solve_rate_off": statistics.fmean(pooled["off_solved"]),
            "solve_rate_on": statistics.fmean(pooled["on_solved"]),
            "solve_rate_lift_on_minus_off": solve_lift,
            "two_proportion_z": z_s, "two_proportion_p": p_solve,
        },
        "verdict": verdict,
        "per_pair": per_pair,
        "caveats": [
            "Cross-file effect is reactive (retry reduction), not first-attempt — by design.",
            "Pairs with off_solve_rate 0.0 or 1.0 have no headroom and prove nothing; recalibrate.",
            "Generalized lessons are seeded directly (trusted) to isolate presence-vs-absence; "
            "this tests transfer, not the organic promotion threshold.",
        ],
    }
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps(summary, indent=2))
        _write_markdown(summary, Path(out).with_suffix(".md"))
    return summary


def _injection_fires(pair):
    """Deterministic check (no model): does the seeded generalized lesson reach the
    reuse task's prompt on a retry across files? Uses a guidance-sensitive stub."""
    marker = pair["lesson"]["retry_instruction"].split()[0]
    h = ReliabilityBenchmarkHarness()
    session = h._create_session(lessons_enabled=True)
    seen = []
    try:
        seed_lesson(session, pair["lesson"])
        malformed = ("TARGET_FILE: %s\nCHANGE_TYPE: diff_patch\nRISK_LEVEL: low\n"
                     "STATUS: proposed\nREASON: x\nPATCH:\n@@ -1,0 +1,1 @@\n+    pass\n"
                     % pair["reuse"]["target_file"])
        def responder(prompt, *a, **k):
            seen.append(marker in prompt); return malformed
        reuse = dict(pair["reuse"]); reuse["coder_response"] = responder
        h._run_one(session, reuse)
        return any(seen)
    finally:
        h._cleanup_session(session)


def _write_markdown(summary, path):
    p = summary["pooled"]
    lo, hi = p["retry_reduction_95ci"]
    lines = [
        "# Lesson-efficacy study — results", "",
        f"- Pairs: {summary['pairs']} | N per arm per pair: {summary['n_per_arm_per_pair']} | "
        f"retry budget: {summary['retry_budget']}", "",
        f"**Verdict: {summary['verdict']}**", "",
        "## Pooled", "",
        f"- Mean retries — OFF {p['mean_retries_off']:.3f} vs ON {p['mean_retries_on']:.3f}",
        f"- Retry reduction (OFF − ON): **{p['retry_reduction_off_minus_on']:.3f}** "
        f"(95% CI [{lo:.3f}, {hi:.3f}]) — CI excluding 0 ⇒ real effect",
        f"- Mann-Whitney p (retries): {p['mann_whitney_p']:.4f}",
        f"- Solve-rate — OFF {p['solve_rate_off']:.3f} vs ON {p['solve_rate_on']:.3f} "
        f"(lift {p['solve_rate_lift_on_minus_off']:+.3f}, two-prop p {p['two_proportion_p']:.4f})", "",
        "## Per pair", "",
        "| pair | band | seed→reuse files | OFF solve | ON solve | OFF retries | ON retries | headroom |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in summary["per_pair"]:
        lines.append(
            f"| {r['name']} | {r['band']} | {r['seed_file']}→{r['reuse_file']} | "
            f"{r['off_solve_rate']:.2f} | {r['on_solve_rate']:.2f} | "
            f"{r['off_mean_retries']:.2f} | {r['on_mean_retries']:.2f} | "
            f"{'OK' if r['headroom_ok'] else 'NONE'} |")
    lines += ["", "## Caveats", ""] + [f"- {c}" for c in summary["caveats"]]
    path.write_text("\n".join(lines))


def main():
    ap = argparse.ArgumentParser(description="Live lesson-efficacy study")
    ap.add_argument("--n", type=int, default=20, help="trials per arm per pair")
    ap.add_argument("--budget", type=int, default=3, help="retry budget (max_revisions)")
    ap.add_argument("--out", default="results/lesson_study.json")
    ap.add_argument("--preflight", action="store_true",
                    help="small calibration run: prints headroom + injection per pair")
    args = ap.parse_args()
    n = min(args.n, 4) if args.preflight else args.n
    summary = run_study(n=n, budget=args.budget, out=args.out, preflight=args.preflight)
    print(json.dumps(summary["pooled"], indent=2))
    print("VERDICT:", summary["verdict"])


if __name__ == "__main__":
    main()

"""
A/B benchmark runner for the empirical validation gate.

Runs the benchmark harness N times against the live codebase (baseline) and
N times against a patched variant, then prints the comparison and verdict.

Usage (CLI):
    python -m validation.ab_run                        # demo patch, n=3
    python -m validation.ab_run --patch my.patch       # patch from file
    python -m validation.ab_run --n 5 --k 2.0          # custom params
    python -m validation.ab_run --patch my.patch --n 5 --no-challenge

Programmatic:
    from validation.ab_run import run
    result = run(patch_text, task_note, n=5, k=2.0)
    print(result["verdict"])

Output:
    A JSON + human-readable table showing baseline scores, variant scores,
    delta, noise_band, and a plain-language verdict.
"""

import argparse
import json
import math
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from validation.variant import (
    apply_patch_to_variant,
    discard_variant,
    make_variant,
    score_variant,
    self_verify,
    _extract_target_file,
)
from validation.scoring import compute_stats


# ---------------------------------------------------------------------------
# Demo patch used when no --patch file is supplied.
# ---------------------------------------------------------------------------
_DEMO_PATCH = (
    "TARGET_FILE: interface.py\n"
    "CHANGE_TYPE: diff_patch\n"
    "RISK_LEVEL: low\n"
    "STATUS: proposed\n"
    "REASON: Copy the optional context mapping before storing it in the response.\n"
    "PATCH:\n"
    "--- interface.py\n"
    "+++ interface.py\n"
    "@@ -44,7 +44,7 @@ class Interface:\n"
    "     def _build_response(self, intent, text, context=None):\n"
    "         return {\n"
    '             "intent": intent,\n'
    '-            "context": context or {},\n'
    '+            "context": dict(context or {}),\n'
    '             "raw_text": text,\n'
    "         }\n"
)
_DEMO_TASK_NOTE = "Copy the optional context mapping before returning it in _build_response."


# ---------------------------------------------------------------------------
# Core A/B function
# ---------------------------------------------------------------------------

def run(patch_text, task_note, n=3, k=2.0, repo_root=None, use_challenge_pack=False):
    """
    Run the A/B benchmark comparison for a given patch.

    Args:
        patch_text:         Hive-format patch string.
        task_note:          Human description of the change.
        n:                  Number of benchmark runs per side (min 2, rec 5).
        k:                  Noise multiplier — accept when delta > k * se_diff.
        repo_root:          Path to the live codebase root.
        use_challenge_pack: If True, score against build_challenge_pack() cases
                            instead of the standard reliability pack.  Useful
                            when the standard pack hits the 1.0 ceiling.

    Returns a dict with keys:
        baseline_scores, variant_scores, baseline_mean, variant_mean,
        delta, noise_band, se_diff, k, decision, verdict, self_verified,
        patch_applied, error (present only on failure), ceiling_warning.
    """
    if repo_root is None:
        repo_root = _REPO_ROOT
    repo_root = Path(repo_root)

    result = {
        "patch_applied": False,
        "self_verified": False,
        "baseline_scores": [],
        "variant_scores": [],
        "baseline_mean": 0.0,
        "variant_mean": 0.0,
        "delta": 0.0,
        "noise_band": 0.0,
        "se_diff": 0.0,
        "k": k,
        "decision": "reject",
        "verdict": "",
        "error": None,
        "ceiling_warning": None,
    }

    target_file = _extract_target_file(patch_text)
    if target_file is None:
        result["error"] = "No TARGET_FILE: header found in patch."
        result["verdict"] = "ERROR: " + result["error"]
        return result

    variant_dir = None
    try:
        # Step 1 — Score baseline (live repo, unmodified)
        _print_progress(f"[A] Scoring baseline ({n} run{'s' if n != 1 else ''})…")
        extra_args = ["--challenge"] if use_challenge_pack else []
        base_scores = _score_n(repo_root, n, extra_args)
        result["baseline_scores"] = base_scores

        # Step 2 — Build variant and apply patch
        _print_progress(f"[B] Building variant and applying patch…")
        variant_dir, vid = make_variant(repo_root)
        ok, err = apply_patch_to_variant(variant_dir, patch_text, target_file=target_file)
        if not ok:
            result["error"] = f"Patch apply failed: {err}"
            result["verdict"] = f"BLOCKED: {result['error']}"
            return result
        result["patch_applied"] = True

        # Step 3 — Self-verify
        sv_ok, sv_reason = self_verify(variant_dir, task_note, patch_text, target_file=target_file)
        result["self_verified"] = sv_ok
        if not sv_ok:
            result["error"] = f"Self-verify failed: {sv_reason}"
            result["verdict"] = f"BLOCKED: {result['error']}"
            return result

        # Step 4 — Score variant
        _print_progress(f"[B] Scoring variant ({n} run{'s' if n != 1 else ''})…")
        var_scores = _score_n(variant_dir, n, extra_args)
        result["variant_scores"] = var_scores

        # Step 5 — Statistics and decision
        stats = compute_stats(base_scores, var_scores, k=k)
        result.update(stats)

        if stats["delta"] > stats["noise_band"]:
            result["decision"] = "accept"
            result["verdict"] = (
                f"ACCEPT — delta {stats['delta']:+.4f} > noise_band {stats['noise_band']:.4f} "
                f"(k={k}, se={stats['se_diff']:.4f})"
            )
        else:
            result["decision"] = "reject"
            result["verdict"] = (
                f"REJECT — delta {stats['delta']:+.4f} <= noise_band {stats['noise_band']:.4f} "
                f"(k={k}, se={stats['se_diff']:.4f})"
            )

        # Ceiling warning: standard pack always 1.0
        if stats["baseline_mean"] >= 1.0 and not use_challenge_pack:
            result["ceiling_warning"] = (
                "Baseline at 1.0 — standard pack is a regression guard only. "
                "Re-run with --challenge (build_challenge_pack) to get meaningful deltas."
            )

        return result

    except Exception as exc:
        result["error"] = str(exc)
        result["verdict"] = f"ERROR: {exc}"
        return result

    finally:
        if variant_dir is not None:
            discard_variant(variant_dir)


def _score_n(codebase_dir, n, extra_args=()):
    """
    Run the harness N times, return list of float scores.
    Passes extra_args to the benchmark subprocess (e.g. ['--challenge']).
    """
    import subprocess
    import sys

    scores = []
    for _ in range(n):
        cmd = [sys.executable, "benchmark_harness.py", "--score"] + list(extra_args)
        result = subprocess.run(
            cmd,
            cwd=str(codebase_dir),
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Harness failed (exit {result.returncode}): {result.stderr.strip()[:400]}"
            )
        data = json.loads(result.stdout.strip())
        scores.append(float(data["score"]))
    return scores


def _print_progress(msg):
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Pretty-print report
# ---------------------------------------------------------------------------

def _format_report(result, patch_text, task_note):
    lines = []
    lines.append("=" * 64)
    lines.append("  HIVE VALIDATION GATE — A/B BENCHMARK REPORT")
    lines.append("=" * 64)
    lines.append(f"  Task : {task_note}")
    target = _extract_target_file(patch_text) or "unknown"
    lines.append(f"  File : {target}")
    lines.append(f"  k    : {result['k']}")
    lines.append("")

    if result.get("error") and not result["baseline_scores"]:
        lines.append(f"  ERROR: {result['error']}")
        lines.append("=" * 64)
        return "\n".join(lines)

    # Score table
    base = result["baseline_scores"]
    var  = result["variant_scores"]
    n    = max(len(base), len(var))
    lines.append(f"  {'Run':>4}  {'Baseline':>10}  {'Variant':>10}  {'Delta':>10}")
    lines.append(f"  {'-'*4}  {'-'*10}  {'-'*10}  {'-'*10}")
    for i in range(n):
        b = f"{base[i]:.4f}" if i < len(base) else "—"
        v = f"{var[i]:.4f}" if i < len(var) else "—"
        if i < len(base) and i < len(var):
            d = f"{var[i] - base[i]:+.4f}"
        else:
            d = "—"
        lines.append(f"  {i+1:>4}  {b:>10}  {v:>10}  {d:>10}")
    lines.append(f"  {'-'*4}  {'-'*10}  {'-'*10}  {'-'*10}")
    lines.append(f"  {'mean':>4}  {result['baseline_mean']:>10.4f}  {result['variant_mean']:>10.4f}  {result['delta']:>+10.4f}")
    lines.append("")
    lines.append(f"  SE of difference : {result['se_diff']:.6f}")
    lines.append(f"  Noise band (k×SE): {result['noise_band']:.6f}")
    lines.append(f"  Self-verified    : {result['self_verified']}")
    lines.append(f"  Patch applied    : {result['patch_applied']}")
    lines.append("")
    lines.append(f"  ► {result['verdict']}")
    if result.get("ceiling_warning"):
        lines.append("")
        lines.append(f"  ⚠  {result['ceiling_warning']}")
    if result.get("error"):
        lines.append("")
        lines.append(f"  ✗  {result['error']}")
    lines.append("=" * 64)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args():
    p = argparse.ArgumentParser(
        description="Run the A/B benchmark comparison for a Hive patch.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--patch", metavar="FILE",
        help="Path to a Hive-format patch file. Defaults to a built-in demo patch.",
    )
    p.add_argument(
        "--task-note", metavar="TEXT",
        help="Human description of the change (used for intent check).",
    )
    p.add_argument(
        "--n", type=int, default=3,
        help="Number of benchmark runs per side (min 2, recommended 5). Default: 3.",
    )
    p.add_argument(
        "--k", type=float, default=2.0,
        help="Noise multiplier (accept when delta > k × SE). Default: 2.0.",
    )
    p.add_argument(
        "--repo-root", metavar="DIR",
        help="Path to the Hive repo root. Defaults to the directory containing this file.",
    )
    p.add_argument(
        "--challenge", action="store_true",
        help="Score against build_challenge_pack() instead of the standard pack.",
    )
    p.add_argument(
        "--json", action="store_true", dest="json_output",
        help="Emit only raw JSON to stdout (no human-readable table).",
    )
    return p.parse_args()


def main():
    args = _parse_args()

    if args.patch:
        patch_text = Path(args.patch).read_text(encoding="utf-8")
        task_note  = args.task_note or f"patch from {args.patch}"
    else:
        patch_text = _DEMO_PATCH
        task_note  = args.task_note or _DEMO_TASK_NOTE
        _print_progress("[ab_run] No --patch given; using built-in demo patch.")

    result = run(
        patch_text=patch_text,
        task_note=task_note,
        n=args.n,
        k=args.k,
        repo_root=args.repo_root,
        use_challenge_pack=args.challenge,
    )

    if args.json_output:
        print(json.dumps(result, indent=2))
    else:
        print(_format_report(result, patch_text, task_note))
        print()
        print(json.dumps(result, indent=2))

    sys.exit(0 if result["decision"] == "accept" else 1)


if __name__ == "__main__":
    main()

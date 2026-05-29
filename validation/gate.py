"""
Empirical validation gate — Darwin Gödel Machine §4/§5 pattern.

Public API:
  evaluate(patch, task_note, anchors=None, repo_root=None, n=5, k=2.0) -> dict

The live repo_root is ONLY modified when decision == "accept" (at the promote step).
Everything before that runs in an isolated variant copy.

Acceptance criterion (stated once):
  self_verified AND anchors_ok AND (variant_mean - baseline_mean) > k * pooled_stdev
"""

import datetime
import shutil
import uuid
from pathlib import Path

from validation.scoring import compute_stats
from validation.variant import (
    apply_patch_to_variant,
    discard_variant,
    make_variant,
    score_variant,
    self_verify,
    _extract_target_file,
)


def _now():
    return datetime.datetime.utcnow().isoformat() + "Z"


def _repo_root_default():
    return Path(__file__).resolve().parent.parent


def anchors_satisfied(patch_text, anchors):
    """
    Check that the patch respects all declared anchors.

    Supported anchor keys:
      target_file       — patch TARGET_FILE header must match
      no_new_imports    — no '+import' or '+from' lines in the diff

    Returns (ok: bool, violations: list[str]).
    """
    if not anchors:
        return True, []

    violations = []
    patch_target = _extract_target_file(patch_text)

    expected_file = anchors.get("target_file")
    if expected_file and patch_target and patch_target != expected_file:
        violations.append(
            f"anchor_file_mismatch: patch targets '{patch_target}', expected '{expected_file}'"
        )

    if anchors.get("no_new_imports"):
        for line in patch_text.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                stripped = line[1:].strip()
                if stripped.startswith("import ") or stripped.startswith("from "):
                    violations.append(f"no_new_imports violated: {stripped}")

    return len(violations) == 0, violations


def _promote(variant_dir, repo_root, target_file):
    """Copy the single patched file from variant back into the live repo."""
    src = Path(variant_dir) / target_file
    dst = Path(repo_root) / target_file
    shutil.copy2(str(src), str(dst))


def _patch_summary(patch_text):
    for line in patch_text.splitlines():
        if line.startswith("REASON:"):
            return line.split(":", 1)[1].strip()
    return patch_text[:80].replace("\n", " ")


def evaluate(patch, task_note, anchors=None, repo_root=None, n=5, k=2.0, variant_id=None):
    """
    Validate a candidate patch empirically.

    Args:
      patch        Hive-format patch string (TARGET_FILE: ... / PATCH: / unified diff).
      task_note    Human description of what the patch is meant to do.
      anchors      Optional dict of constraints (target_file, no_new_imports, ...).
      repo_root    Path to the live codebase. Defaults to the Hive root.
      n            Number of benchmark runs per side (start=5; raise if variance is high).
      k            Noise multiplier (~2σ). Accept only if delta > k * pooled_stdev.
      variant_id   Optional explicit variant ID for traceability.

    Returns a validation_record dict. Check record["decision"] for "accept" or "reject".
    The live repo is only touched when decision == "accept".
    """
    if repo_root is None:
        repo_root = _repo_root_default()
    repo_root = Path(repo_root)

    vid = variant_id or (
        f"v_{datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    )

    record = {
        "variant_id": vid,
        "parent_id": f"main@{repo_root}",
        "task_note": task_note,
        "patch_summary": _patch_summary(patch),
        "anchors_checked": sorted(anchors.keys()) if anchors else [],
        "self_verified": False,
        "baseline_scores": [],
        "variant_scores": [],
        "baseline_mean": 0.0,
        "variant_mean": 0.0,
        "delta": 0.0,
        "noise_band": 0.0,
        "decision": "reject",
        "reason": "",
        "timestamp": _now(),
    }

    # Step 1 — Anchor check
    anchors_ok, violations = anchors_satisfied(patch, anchors)
    if not anchors_ok:
        record["reason"] = f"anchor_violation: {'; '.join(violations)}"
        return record

    # Step 2 — Build isolated variant and apply patch
    target_file = _extract_target_file(patch)
    if target_file is None:
        record["reason"] = "patch_apply_failed: TARGET_FILE header missing from patch"
        return record

    variant_dir = None
    try:
        variant_dir, _ = make_variant(repo_root, variant_id=vid)

        ok, err = apply_patch_to_variant(variant_dir, patch, target_file=target_file)
        if not ok:
            record["reason"] = f"patch_apply_failed: {err}"
            return record

        # Step 3 — Self-verification (cheap; runs before expensive scoring)
        sv_ok, sv_reason = self_verify(variant_dir, task_note, patch, target_file=target_file)
        record["self_verified"] = sv_ok
        if not sv_ok:
            record["reason"] = f"self_verification_failed: {sv_reason}"
            return record

        # Step 4 — Score baseline and variant N times each
        try:
            base_scores = score_variant(repo_root, n=n)
        except Exception as exc:
            record["reason"] = f"baseline_scoring_failed: {exc}"
            return record

        try:
            var_scores = score_variant(variant_dir, n=n)
        except Exception as exc:
            record["reason"] = f"variant_scoring_failed: {exc}"
            return record

        stats = compute_stats(base_scores, var_scores, k=k)
        record.update(stats)

        # Step 5 — Decide
        if stats["delta"] > stats["noise_band"]:
            _promote(variant_dir, repo_root, target_file)
            record["decision"] = "accept"
            record["reason"] = (
                f"delta {stats['delta']:.4f} > noise_band {stats['noise_band']:.4f} "
                f"and self_verified and anchors_ok"
            )
        else:
            record["decision"] = "reject"
            record["reason"] = (
                f"no_significant_gain: delta {stats['delta']:.4f} "
                f"<= noise_band {stats['noise_band']:.4f}"
            )

        return record

    finally:
        if variant_dir is not None:
            discard_variant(variant_dir)


if __name__ == "__main__":
    import json
    import sys

    # Phase 3 manual demo: route a hand-written patch through the gate.
    # Usage: python -m validation.gate  (from the Hive root)
    #
    # This uses a known-good patch from benchmark_pack as the test case.
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
    n_runs = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    print(f"[gate demo] n={n_runs}, k=2.0 — routing demo patch through the gate...")
    result = evaluate(
        patch=_DEMO_PATCH,
        task_note="Copy the optional context mapping before returning it in _build_response.",
        anchors={"target_file": "interface.py"},
        n=n_runs,
        k=2.0,
    )
    print(json.dumps(result, indent=2))

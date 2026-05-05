import json
import sys
from pathlib import Path

from scripts.stress_runner import run_stress, run_tier2


def main():
    Path('tmp_stress').mkdir(parents=True, exist_ok=True)
    # Ensure CI target has a simple single-arg function for intent checks
    ci_target = Path('tmp_stress/ci_target.py')
    if not ci_target.exists():
        ci_target.write_text('def compute(x):\n    return x * 2\n', encoding='utf-8')

    # Tier 1 quick: unsafe and safe (10 each)
    print('Running Tier-1 quick checks...')
    unsafe = run_stress('tmp_stress/ci_target.py', concurrency=4, iterations=10, safe=False, log_path='tmp_stress/ci_log_unsafe.jsonl')
    safe = run_stress('tmp_stress/ci_target.py', concurrency=4, iterations=10, safe=True, log_path='tmp_stress/ci_log_safe.jsonl')

    # Tier 2 quick with intent checks enabled (10 iterations per case)
    print('Running Tier-2 quick checks (intent-enabled)...')
    tier2 = run_tier2('tmp_stress/ci_target.py', concurrency=4, iterations_per_case=10, log_dir='tmp_stress')

    metrics = {
        'tier1': {'unsafe': unsafe, 'safe': safe},
        'tier2': tier2,
    }

    # Additionally run an explicit intent-drift quick loop on a controlled CI target
    from scripts.fuzzer_patch_generator import correct_context_wrong_intent_patch
    from scripts.intent_detector import check_intent_with_patch

    intent_quick_target = Path('tmp_stress/ci_target.py')
    intent_quick_target.write_text('def compute(x):\n    return x * 2\n', encoding='utf-8')
    intent_checks = {'started': 0, 'drift_detected': 0, 'applied': 0}
    for i in range(10):
        intent_checks['started'] += 1
        patch = correct_context_wrong_intent_patch(str(intent_quick_target), wrong_return=1000 + i)
        res = check_intent_with_patch(str(intent_quick_target), patch, 'compute', [2, 3, 5], [4, 6, 10])
        if isinstance(res, dict):
            if res.get('applied'):
                intent_checks['applied'] += 1
            if res.get('drift_detected'):
                intent_checks['drift_detected'] += 1

    metrics['intent_quick'] = intent_checks
    Path('tmp_stress/ci_metrics.json').write_text(json.dumps(metrics, indent=2), encoding='utf-8')

    # Conservative gate thresholds (allow small flakiness):
    # - unsafe must have 0 accepted patches (strict)
    # - safe must succeed on at least 90% of trials
    # - intent detector must flag drift on at least 90% of intent trials
    unsafe_ok = unsafe.get('succeeded', 0) == 0
    safe_started = safe.get('started', 0)
    safe_succeeded = safe.get('succeeded', 0)
    safe_ratio = (safe_succeeded / safe_started) if safe_started > 0 else 0.0

    intent_case = tier2.get('correct_context_wrong_intent', {})
    intent_started = intent_case.get('started', 0)
    intent_detected = intent_case.get('drift_detected', 0)
    intent_ratio = (intent_detected / intent_started) if intent_started > 0 else 0.0

    ok = True
    if not unsafe_ok:
        print('CI Gate FAIL: unsafe fuzzer produced accepted patches')
        ok = False

    if safe_ratio < 0.9:
        print(f'CI Gate FAIL: safe patches success ratio too low ({safe_succeeded}/{safe_started} = {safe_ratio:.2f})')
        ok = False

    # also consider the explicit quick intent loop if available
    intent_quick = metrics.get('intent_quick')
    intent_quick_ratio = (intent_quick.get('drift_detected', 0) / intent_quick.get('started', 1)) if intent_quick else 0.0

    if intent_ratio < 0.9 and intent_quick_ratio < 0.9:
        print(f'CI Gate FAIL: intent detector rate too low (tier2: {intent_detected}/{intent_started} = {intent_ratio:.2f}, quick: {intent_quick.get("drift_detected",0)}/{intent_quick.get("started",0)} = {intent_quick_ratio:.2f})')
        ok = False

    print('CI quick metrics:')
    print(json.dumps({'unsafe': unsafe, 'safe': safe, 'intent_case': intent_case}, indent=2))

    if not ok:
        print('CI gate: failing build. See tmp_stress/ci_metrics.json and logs for details.')
        sys.exit(1)

    print('CI gate: all checks passed (quick).')


if __name__ == '__main__':
    main()

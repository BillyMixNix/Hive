import threading
import time
import sys
from pathlib import Path

# Ensure repo root is importable when running scripts directly
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from executor import ExecutorAgent
from scripts.fuzzer_patch_generator import random_patch_change, safe_patch_for_target
import json
from scripts.fuzzer_patch_generator import (
    syntax_corrupt_patch,
    semantic_undefined_self_call_patch,
    wrong_target_patch,
    oversized_diff_patch,
    duplicate_helper_insertion_patch,
    correct_context_wrong_intent_patch,
)
from scripts.intent_detector import check_intent_with_patch, run_function_from_file


def run_stress(target_file, concurrency=8, iterations=50, safe=False, log_path=None):
    """Run concurrent patch attempts against `target_file`.

    Args:
        target_file: path to the file to patch
        concurrency: max concurrent threads
        iterations: total patch attempts
        safe: if True use `safe_patch_for_target`, else use random fuzzer
        log_path: optional path to write per-trial JSONL logs
    """
    executor = ExecutorAgent()
    target = Path(target_file)
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('def sample():\n    return 0\n')

    stats = {'started': 0, 'succeeded': 0, 'failed': 0}

    log_fp = None
    if log_path:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        log_fp = open(log_path, 'a', encoding='utf-8')

    def worker(i):
        stats['started'] += 1
        if safe:
            patch = safe_patch_for_target(str(target), variation=(i % 10) + 1)
        else:
            patch = random_patch_change()

        try:
            report = executor.test_patch_in_sandbox(patch, str(target), patch_reason=f'stress-{i}')
            entry = {
                'i': i,
                'mode': 'safe' if safe else 'unsafe',
                'patch': patch,
                'report': report,
            }
            if log_fp:
                log_fp.write(json.dumps(entry) + '\n')

            if report.get('applied') and report.get('syntax_valid') and report.get('semantic_valid'):
                stats['succeeded'] += 1
            else:
                stats['failed'] += 1
        except Exception as e:
            stats['failed'] += 1
            entry = {'i': i, 'mode': 'safe' if safe else 'unsafe', 'patch': patch, 'error': str(e)}
            if log_fp:
                log_fp.write(json.dumps(entry) + '\n')

    threads = []
    for i in range(iterations):
        t = threading.Thread(target=worker, args=(i,))
        threads.append(t)
        t.start()
        if len(threads) >= concurrency:
            for th in threads:
                th.join()
            threads = []

    # join remaining
    for th in threads:
        th.join()

    if log_fp:
        log_fp.close()

    return stats


def run_tier2(target_file, concurrency=6, iterations_per_case=20, log_dir='tmp_stress'):
    """Run Tier-2 adversarial suites probing syntax/semantic/size/wrong-target cases.

    Produces per-case JSONL logs and an aggregated metrics file under `log_dir`.
    """
    cases = {
        'syntax_failures': syntax_corrupt_patch,
        'semantic_undefined_self_call': semantic_undefined_self_call_patch,
        'wrong_target_edits': lambda: wrong_target_patch('nonexistent_func'),
        'oversized_diffs': lambda: oversized_diff_patch(size=300),
        'duplicate_helper_insertion': lambda: duplicate_helper_insertion_patch('helper_fn'),
        'correct_context_wrong_intent': lambda: correct_context_wrong_intent_patch(target_file, wrong_return=12345),
    }

    aggregate = {}
    for name, generator in cases.items():
        stats = {'started': 0, 'succeeded': 0, 'failed': 0, 'drift_detected': 0}
        log_path = Path(log_dir) / f'log_tier2_{name}.jsonl'
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        # open log file in append mode for efficiency
        with log_path.open('a', encoding='utf-8') as lf:
            for i in range(iterations_per_case):
                stats['started'] += 1
                patch = generator()
                try:
                    report = ExecutorAgent().test_patch_in_sandbox(patch, str(target_file), patch_reason=f'tier2-{name}-{i}')

                    entry = {'case': name, 'i': i, 'patch': patch, 'report': report}

                    # If this is the intent case, run the intent detector and attach results
                    if name == 'correct_context_wrong_intent':
                        # attempt to derive a function name from the target file
                        func_name = None
                        try:
                            lines = Path(target_file).read_text(encoding='utf-8').splitlines()
                            for line in lines:
                                s = line.lstrip()
                                if s.startswith('def '):
                                    fn = s[4:]
                                    fn = fn.split('(')[0].strip()
                                    func_name = fn
                                    break
                        except Exception:
                            func_name = None

                        # default test inputs
                        test_inputs = [2, 3, 5]
                        expected = None
                        if func_name:
                            try:
                                expected = run_function_from_file(str(target_file), func_name, test_inputs)
                            except Exception:
                                expected = None

                        if func_name and expected is not None:
                            intent_res = check_intent_with_patch(str(target_file), patch, func_name, test_inputs, expected)
                            entry['intent_check'] = intent_res
                            if intent_res.get('drift_detected'):
                                stats['drift_detected'] += 1

                    lf.write(json.dumps(entry) + '\n')

                    if report.get('applied') and report.get('syntax_valid') and report.get('semantic_valid'):
                        stats['succeeded'] += 1
                    else:
                        stats['failed'] += 1
                except Exception as e:
                    stats['failed'] += 1
                    entry = {'case': name, 'i': i, 'patch': patch, 'error': str(e)}
                    lf.write(json.dumps(entry) + '\n')

        aggregate[name] = stats

    # write aggregate metrics
    metrics_path = Path(log_dir) / 'metrics_tier2.json'
    metrics_path.write_text(json.dumps(aggregate, indent=2), encoding='utf-8')
    return aggregate


if __name__ == '__main__':
    # Run unsafe (expected rejections) then safe (expected accepts)
    print('Running unsafe fuzzer...')
    unsafe_stats = run_stress('tmp_stress/target.py', concurrency=6, iterations=100, safe=False, log_path='tmp_stress/log_unsafe.jsonl')
    print('Unsafe stats:', unsafe_stats)

    print('Running safe fuzzer...')
    safe_stats = run_stress('tmp_stress/target.py', concurrency=6, iterations=100, safe=True, log_path='tmp_stress/log_safe.jsonl')
    print('Safe stats:', safe_stats)
    print('Running Tier-2 adversarial suite (short)...')
    tier2 = run_tier2('tmp_stress/target.py', concurrency=4, iterations_per_case=20, log_dir='tmp_stress')
    print('Tier-2 results:', tier2)

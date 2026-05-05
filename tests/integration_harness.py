import threading
import time
import sys
from pathlib import Path

# Ensure repo root is importable when running this module directly
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from repo_map import RepoMap
from executor import ExecutorAgent


def run_integration_cycle(sample_dir, num_patches=5):
    # Build repo map snapshot
    repo = RepoMap(root='.')
    repo_snapshot = repo.build()

    executor = ExecutorAgent()

    sample_dir = Path(sample_dir)
    sample_dir.mkdir(parents=True, exist_ok=True)

    # create a simple sample file
    target = sample_dir / 'target_module.py'
    target.write_text('def compute(x):\n    return x * 2\n')

    results = []

    def worker(i):
        # craft a simple patch that changes return value
        patch = '\n'.join([
            '@@',
            '-def compute(x):',
            '-    return x * 2',
            '+def compute(x):',
            f'+    return x * {2 + i}',
        ])

        report = executor.test_patch_in_sandbox(patch, str(target), patch_reason=f'integration-{i}')
        results.append((i, report))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_patches)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    return repo_snapshot, results


if __name__ == '__main__':
    snap, res = run_integration_cycle('tmp_integration', num_patches=4)
    print('Repo known files:', len(snap.get('known_files', [])))
    for idx, report in res:
        print(f'Patch {idx}: applied={report.get("applied")}, syntax={report.get("syntax_valid")}, semantic={report.get("semantic_valid")}, errors={report.get("errors")}')

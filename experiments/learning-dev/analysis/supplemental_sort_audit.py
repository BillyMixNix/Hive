"""Supplemental semantic audit, authored before inspecting confirmation results.

Motivation: a SCREEN-1 neutral repair uses temporary mutation to pass fixed
examples. Probe the stated sorting contract with varied lengths, duplicate keys,
negative ranks and unorderable payload dictionaries. This diagnostic does NOT
change the pre-registered decision rule or supply feedback to any model.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hive_learning.evaluate import grade


def test_source(case):
    variant = int(case['id'].rsplit('_', 1)[1])
    module = next(p[:-3] for p in case['files'] if not p.startswith('test_'))
    common = (f'from {module} import arrange_{variant} as arrange\n'
              'import copy\nimport random\n\ndef test_varied_contract():\n'
              '    rng = random.Random(8317)\n'
              '    for size in range(17):\n'
              '        for repetition in range(6):\n')
    if variant % 3 == 0:
        body = ("labels = [rng.randrange(-3, 4) for _ in range(size)]\n"
                "payloads = [{'identity': i} for i in range(size)]\n"
                "expected = sorted(zip(labels, payloads), key=lambda pair: pair[0])\n"
                "assert arrange(labels, payloads) == expected\n")
        extra = ("\ndef test_length_mismatch():\n    import pytest\n"
                 "    with pytest.raises(ValueError):\n        arrange([1, 2], ['x'])\n"
                 "    with pytest.raises(ValueError):\n        arrange([], ['x'])\n")
    elif variant % 3 == 1:
        body = ("rows = [{'rank': rng.randrange(-3, 4), 'value': {'identity': i}, 'extra': i + 70} for i in range(size)]\n"
                "original = copy.deepcopy(rows)\n"
                "expected = sorted(copy.deepcopy(rows), key=lambda row: row['rank'])\n"
                "assert arrange(rows) == expected\n"
                "assert rows == original\n")
        extra = ''
    else:
        body = ("rows = [(rng.choice(['a', 'b', 'c']), rng.randrange(-3, 4), {'identity': i}) for i in range(size)]\n"
                "expected = sorted([((row[0], row[1]), row[2]) for row in rows], key=lambda pair: pair[0])\n"
                "assert arrange(rows) == expected\n")
        extra = ''
    return common + ''.join('            '+line+'\n' for line in body.splitlines()) + extra


def main():
    p = argparse.ArgumentParser();p.add_argument('evidence');a = p.parse_args()
    study = json.loads((ROOT/'examples/lesson-study-v2.json').read_text())
    cases = {c['id']: c for c in study['cases']}
    results = []
    for path in sorted(Path(a.evidence).glob('recipients/*/result.json')):
        result = json.loads(path.read_text())
        if result['family'] != 'paired_sort' or 'candidate' not in result:
            continue
        test = test_source(cases[result['case_id']])
        results.append({'case_id': result['case_id'], 'arm': result['arm'],
                        'original_test_pass': result['passed'],
                        'audit_test_sha256': hashlib.sha256(test.encode()).hexdigest(),
                        'supplemental_grade': grade(result['candidate'], {'test_supplemental.py': test})})
    print(json.dumps({'scope': 'supplemental_diagnostic_only',
                      'audit_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                      'selection_or_promotion_eligible': False, 'results': results}, indent=2))


if __name__ == '__main__':
    main()

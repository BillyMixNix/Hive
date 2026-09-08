"""Fresh confirmation of a retained three-lesson bank after the interrupted V2.

All outcomes are retained. No formation, refinement, endpoint selection or
repeated recipient is allowed in this study. API errors stop the phase.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import random
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from analysis.cloud_http400 import CaptureHTTP
from hive_learning.cloud_trial import allowed_launch
from hive_learning.cloud_study import DeadlineHive, implementation
from hive_learning.evaluate import strict_json
from hive_learning.ledger import digest
from hive_learning.lesson_study import ARMS, compact, neutral_lesson, run_recipient, save_json
from hive_learning.openai_adapter import load_api_key
from hive_learning.response_trace import ResponseTrace
from hive_learning.spending import LIMIT_NUSD, MODEL, SpendingGuard


def source_hashes():
    paths = ['analysis/lesson_bank_study.py', 'analysis/cloud_http400.py', 'analysis/supplemental_sort_audit.py']
    return implementation(ROOT) | {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in paths}


def exact_mean_p(differences):
    """Exact one-sided paired sign-flip test, using integer dynamic programming."""
    differences = [int(x) for x in differences if x]
    distribution = {0: 1}
    for delta in differences:
        next_distribution = {}
        for total, count in distribution.items():
            for value in (total + abs(delta), total - abs(delta)):
                next_distribution[value] = next_distribution.get(value, 0) + count
        distribution = next_distribution
    observed = sum(differences)
    return sum(count for total, count in distribution.items() if total >= observed) / 2**len(differences)


def assess(state, study):
    rows = state['trials']
    target = {(case['id'], arm) for case in study['cases'] for arm in ARMS}
    keys = [(row['case_id'], row['arm']) for row in rows]
    if len(keys) != len(set(keys)) or set(keys) != target:
        return {'verdict': 'INCOMPLETE', 'recipients': len(rows)}
    if not all(row['integrity_valid'] for row in rows):
        return {'verdict': 'INVALID', 'reason': 'recipient integrity failure'}
    transfer = [case['id'] for case in study['cases'] if case['split']=='confirmation']
    retention = [case['id'] for case in study['cases'] if case['split']=='retention']
    paired = {case: {r['arm']: r for r in rows if r['case_id']==case} for case in transfer}
    successes = {arm: sum(pair[arm]['passed'] for pair in paired.values()) for arm in ARMS}
    def score(row):
        return row['usage']['calls'] if row['passed'] else study['calls_per_recipient']
    comparisons = {}
    for control in ('baseline','neutral'):
        differences = [score(pair[control])-score(pair['lesson']) for pair in paired.values()]
        baseline = sum(score(pair[control]) for pair in paired.values())
        treatment = sum(score(pair['lesson']) for pair in paired.values())
        comparisons[control] = {'control_penalized_calls': baseline, 'lesson_penalized_calls': treatment,
            'relative_reduction': 1-treatment/baseline, 'paired_differences': differences,
            'one_sided_exact_p': exact_mean_p(differences),
            'control_successes': successes[control], 'lesson_successes': successes['lesson']}
    retained = all(r['passed'] for r in rows if r['case_id'] in retention and r['arm']=='lesson')
    passed = successes['lesson']==len(transfer) and retained and all(
        row['relative_reduction'] >= study['policy']['minimum_reduction'] and
        row['one_sided_exact_p'] <= study['policy']['alpha_one_sided'] for row in comparisons.values())
    return {'verdict': 'CONFIRMED_GAIN' if passed else 'GAIN_NOT_CONFIRMED',
        'endpoint': 'model_calls_to_verified_repair_with_failure_penalty_36',
        'tasks_per_arm': len(transfer), 'successes': successes, 'retention_passed': retained,
        'comparisons': comparisons,
        'interpretation': 'Conditional evidence for retained guidance on these authored tasks and model alias. Failure penalty is a utility score, not a billed call or dollar charge. Model weights are unchanged.'}


def checked_file(name, expected):
    if not isinstance(name,str) or Path(name).is_absolute() or '..' in Path(name).parts:
        raise ValueError('invalid committed input path')
    raw=(ROOT/name).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected:
        raise ValueError('committed input changed')
    return strict_json(raw)


def read_plan():
    plan=strict_json((ROOT/'lesson-bank-plan.json').read_bytes())
    phase=plan['phase']
    if (type(phase) is not int or not 1<=phase<=5
            or plan['launch_message']!=f'Run authorized Hive lesson bank phase {phase}'
            or not re.fullmatch(r'[a-f0-9]{40}',plan['launch_parent'])
            or plan['source_sha256']!=digest(source_hashes())):
        raise ValueError('invalid bank study launch')
    study=checked_file(plan['study'],plan['study_sha256'])
    preflight=checked_file(plan['preflight'],plan['preflight_sha256'])
    if (study['schema']!='hive.lesson-bank.v3' or study['model']!=MODEL
            or study['calls_per_recipient']!=36 or len(study['cases'])!=26
            or digest(study['cases'])!=preflight['cases_sha256'] or not preflight['verified']):
        raise ValueError('invalid frozen/preflighted study')
    prior=checked_file(plan['prior_report'],plan['prior_report_sha256'])
    spent=prior['spending']['total_upper_nano_usd']
    if (type(spent) is not int or not 0<=spent<=LIMIT_NUSD
            or prior['spending']['unresolved_reservation_nano_usd']):
        raise ValueError('unsettled predecessor')
    previous=None
    if phase>1:
        previous=checked_file(plan['prior_state'],plan['prior_state_sha256'])
        if (prior['study_state_sha256']!=plan['prior_state_sha256']
                or previous['study_sha256']!=plan['study_sha256']
                or prior['source_sha256']!=plan['source_sha256']):
            raise ValueError('bank or implementation changed')
    elif plan['prior_state'] is not None or plan['prior_state_sha256'] is not None:
        raise ValueError('phase one must start fresh')
    return plan,study,prior,previous


class CapturedHive(DeadlineHive):
    def __init__(self,*args,request_directory,**kwargs):
        super().__init__(*args,**kwargs)
        self.request_directory=request_directory

    def _new_meter(self,*args,**kwargs):
        meter=super()._new_meter(*args,**kwargs)
        original=meter.opener
        owner=self
        class Opener:
            def open(self,request,timeout):
                directory=owner.request_directory/f'request-{owner.budget.calls:05d}'
                directory.mkdir(parents=True,exist_ok=False)
                return CaptureHTTP(original,directory,owner._api_key).open(request,timeout)
        meter.opener=Opener()
        return meter


def run_phase(adapter,study,study_sha,phase,output,previous=None):
    state=copy.deepcopy(previous) if previous is not None else {
        'schema':'hive.lesson-bank.state.v3','study_sha256':study_sha,
        'bank_sha256':digest(study['lessons']),'phases':[],'trials':[]}
    if (state['study_sha256']!=study_sha or state['bank_sha256']!=digest(study['lessons'])
            or [p['phase'] for p in state['phases']]!=list(range(1,phase))
            or any(p['status']!='completed' for p in state['phases'])):
        raise ValueError('phase already consumed or predecessor incomplete')
    cases=[c for c in study['cases'] if c['phase']==phase]
    schedule=[(case,arm) for case in cases for arm in ARMS]
    random.Random(study['seed']+phase).shuffle(schedule)
    event={'phase':phase,'status':'running','schedule':[{'case_id':c['id'],'arm':a} for c,a in schedule]}
    state['phases'].append(event)
    path=output/'study-state.json';save_json(path,state)
    for case,arm in schedule:
        guidance=[] if arm=='baseline' else study['lessons'] if arm=='lesson' else [neutral_lesson(l) for l in study['lessons']]
        record=run_recipient(adapter,case,guidance,arm,output/'recipients'/(case['id']+'-'+arm))
        state['trials'].append(compact(record));save_json(path,state)
        print('HIVE_BANK_PROGRESS '+json.dumps({'phase':phase,'case':case['id'],'arm':arm,'passed':record['passed'],'calls':record.get('usage',{}).get('calls')},sort_keys=True),flush=True)
    event['status']='completed'
    if phase==5:
        state['assessment']=assess(state,study)
    save_json(path,state)
    return state


def main():
    plan,study,prior,previous=read_plan()
    event=strict_json(Path(os.environ['GITHUB_EVENT_PATH']).read_bytes())
    if not allowed_launch({**os.environ,'HIVE_LAUNCH_PARENT':plan['launch_parent']},event,plan['launch_message']):
        os.environ.pop('OPENAI_API_KEY',None);return 2
    if sys.argv[1:]==['--check']:
        print(json.dumps({'status':'COMMITMENT_VERIFIED','phase':plan['phase'],'prior_upper_nano_usd':prior['spending']['total_upper_nano_usd']}));return 0
    output=Path(sys.argv[1]);output.mkdir(parents=True,exist_ok=False)
    manifest={'plan':plan,'run_id':os.environ['GITHUB_RUN_ID'],'commit':os.environ['GITHUB_SHA'],
              'source_hashes':source_hashes(),'bank_sha256':digest(study['lessons']),'prior_episode':prior['episode_id']}
    save_json(output/'manifest.json',manifest)
    report={'episode_id':digest(manifest),'scope':'fresh_lesson_bank_confirmation','phase':plan['phase'],
            'study_sha256':plan['study_sha256'],'source_sha256':plan['source_sha256'],
            'continued_after':prior['episode_id'],'status':'INVALID'}
    guard=adapter=None
    try:
        key=load_api_key()
        guard=SpendingGuard(output/'spending.jsonl',prior_upper_nano_usd=prior['spending']['total_upper_nano_usd'])
        adapter=CapturedHive(MODEL,key,max_requests=648,spending=guard,observer=ResponseTrace(output/'responses'),
                             request_directory=output/'requests',seed=study['seed'])
        del key
        state=run_phase(adapter,study,plan['study_sha256'],plan['phase'],output,previous)
        report.update(status='COMPLETED',assessment=state.get('assessment'))
    except Exception as exc:
        report['error_type']=type(exc).__name__
    finally:
        os.environ.pop('OPENAI_API_KEY',None)
        if guard:
            report['spending']=guard.snapshot();guard.close()
        if adapter:
            report['transport_usage']=adapter.observed_usage()
    if (output/'study-state.json').exists():
        report['study_state_sha256']=hashlib.sha256((output/'study-state.json').read_bytes()).hexdigest()
    errors=[strict_json(p.read_bytes()) for p in sorted(output.glob('requests/*/http-error.json'))]
    if errors:
        report['http_errors']=errors
    save_json(output/'report.json',report)
    save_json(output/'checksums.json',{p.relative_to(output).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output.rglob('*')) if p.is_file()})
    print('HIVE_BANK_REPORT '+json.dumps(report,sort_keys=True),flush=True)
    return 0 if report['status']=='COMPLETED' else 2


if __name__=='__main__':
    raise SystemExit(main())

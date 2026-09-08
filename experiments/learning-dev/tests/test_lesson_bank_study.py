import copy
import itertools
import json
from pathlib import Path

import pytest

from analysis.lesson_bank_study import assess, exact_mean_p, run_phase
from hive_learning.ledger import digest

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    study = json.loads((ROOT/'examples/lesson-bank-v3.json').read_text())
    rows = [{'case_id': c['id'], 'arm': arm, 'integrity_valid': True,
             'passed': True, 'usage': {'calls': 8 if arm=='lesson' else 12}}
            for c in study['cases'] for arm in ('baseline','lesson','neutral')]
    return study, {'trials': rows}


@pytest.mark.parametrize('differences', [[8,8,-1,-1], [0,0], [1,-1,3], [5,1,0,-2,6]])
def test_exact_mean_distribution_against_full_enumeration(differences):
    observed = sum(differences)
    sums = [sum(a*b for a,b in zip(differences,signs))
            for signs in itertools.product((-1,1), repeat=len(differences))]
    assert exact_mean_p(differences) == sum(x>=observed for x in sums)/len(sums)


def test_full_sample_both_controls_and_retention_are_required():
    study,state = fixture()
    assert assess(state,study)['verdict']=='CONFIRMED_GAIN'
    missing=copy.deepcopy(state);missing['trials'].pop()
    assert assess(missing,study)['verdict']=='INCOMPLETE'
    duplicate=copy.deepcopy(state);duplicate['trials'].append(duplicate['trials'][0])
    assert assess(duplicate,study)['verdict']=='INCOMPLETE'
    for row in state['trials']:
        if row['arm']=='neutral': row['usage']['calls']=8
    assert assess(state,study)['verdict']=='GAIN_NOT_CONFIRMED'
    study,state=fixture()
    next(r for r in state['trials'] if 'retention' in r['case_id'] and r['arm']=='lesson')['passed']=False
    assert assess(state,study)['verdict']=='GAIN_NOT_CONFIRMED'


def test_quick_wrong_lesson_and_corrupt_trial_cannot_confirm():
    study,state=fixture()
    row=next(r for r in state['trials'] if r['arm']=='lesson')
    row['passed']=False;row['usage']['calls']=1
    assert assess(state,study)['verdict']=='GAIN_NOT_CONFIRMED'
    row['integrity_valid']=False
    assert assess(state,study)['verdict']=='INVALID'


def test_original_model_lessons_and_fresh_sample():
    study,state=fixture()
    origin=json.loads((ROOT/'results/lesson-v2-screen1/study-state.json').read_text())
    assert study['lessons']==[origin['lessons'][f] for f in study['families']]
    assert len(study['lessons'])==3
    assert all(sum(c['family']==f for c in study['cases'])==8 for f in study['families'])
    old=json.loads((ROOT/'examples/lesson-study-v2.json').read_text())
    assert not set(c['id'] for c in study['cases']) & set(c['id'] for c in old['cases'])
    assert study['policy']['alpha_one_sided']==.0125


def test_consumed_phase_and_changed_bank_refused(tmp_path):
    study,_=fixture()
    state={'study_sha256':'fixed','bank_sha256':digest(study['lessons']),
           'phases':[{'phase':1,'status':'running'}],'trials':[]}
    with pytest.raises(ValueError):
        run_phase(None,study,'fixed',1,tmp_path,state)
    state['phases']=[];state['bank_sha256']='changed'
    with pytest.raises(ValueError):
        run_phase(None,study,'fixed',1,tmp_path,state)

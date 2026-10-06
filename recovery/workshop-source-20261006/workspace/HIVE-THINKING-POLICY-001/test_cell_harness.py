import json,subprocess
from pathlib import Path
import pytest
from cell_harness import capture_candidate,record_verifiers,collect_cell
from recorder import VerifierRecorder
from qcommon import hive,external_root

@pytest.mark.parametrize('kind',['targeted','full'])
@pytest.mark.parametrize('keywords',[False,True])
def test_actual_candidate_capture_and_wrapper_seam(tmp_path,kind,keywords):
    tree=tmp_path/'stage';tree.mkdir();(tree/'Example.java').write_text('class Example {}\n')
    before=external_root.tree_sha256(tree);result={'passed':False,'checks':[]};seen=[]
    def original(*a,**kw):seen.append((a,kw));return result
    rec=VerifierRecorder(tmp_path/'measurement',capture=capture_candidate);wrapped=rec.wrap(original,kind)
    kwargs={'tree':tree,'agent':'backend','changed_files':['Example.java']} if kind=='targeted' else {'tree':tree}
    args=(tree,'backend',['Example.java']) if kind=='targeted' else (tree,)
    assert (wrapped(**kwargs) if keywords else wrapped(*args)) is result
    assert len(seen)==1 and external_root.tree_sha256(tree)==before
    assert (tmp_path/'measurement/1/applied-source/Example.java').read_bytes()==(tree/'Example.java').read_bytes()
    assert rec.summary()['measurement_status']=='MEASURED'

def test_real_seam_restored_after_exception(tmp_path,monkeypatch):
    exc=ValueError('controlled real seam fixture');seen=[]
    def fake_target(*a):seen.append(a);raise exc
    fake_full=lambda *a:{'passed':True}
    monkeypatch.setattr(hive,'targeted_verify',fake_target);monkeypatch.setattr(hive,'verify_tree',fake_full)
    rec=VerifierRecorder(tmp_path)
    with pytest.raises(ValueError) as raised:
        with record_verifiers(rec):hive.targeted_verify('tree','backend',['p'])
    assert raised.value is exc and len(seen)==1
    assert hive.targeted_verify is fake_target and hive.verify_tree is fake_full
    assert rec.summary()['measurement_status']=='MEASURED'

@pytest.mark.parametrize('outcome',['fail','raise','timeout'])
def test_controlled_production_wrapper_path_distinctions(tmp_path,monkeypatch,outcome):
    result={'passed':False,'checks':[{'name':'controlled','passed':False}]}
    exc=RuntimeError('fixture failure') if outcome=='raise' else subprocess.TimeoutExpired('fixture',240)
    def target(*a):
        if outcome=='fail':return result
        raise exc
    monkeypatch.setattr(hive,'targeted_verify',target)
    rec=VerifierRecorder(tmp_path)
    with record_verifiers(rec):
        if outcome=='fail':assert hive.targeted_verify('tree','backend',[]) is result
        else:
            with pytest.raises(type(exc)) as raised:hive.targeted_verify('tree','backend',[])
            assert raised.value is exc
    assert rec.records[0]['outcome']==('returned' if outcome=='fail' else 'raised')

def test_collector_does_not_relabel_measurement_failure_as_verifier_failure(tmp_path):
    rec=VerifierRecorder(tmp_path);rec.records.append({'verifier_kind':'targeted','outcome':'pending'})
    run={'status':'verified','verification':{'passed':True},'semantic_review':{'disposition':'approved'},'applied':False}
    row=collect_cell(run,rec)
    assert row['measurement_status']=='MEASUREMENT_FAILURE'
    assert row['native_verification']=={'passed':True} and row['software_outcome'] is None
    assert not row['measurement']['scoring_permitted']

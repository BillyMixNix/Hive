import asyncio,json
import pytest
from qcommon import hive,external_root,FREEZE,forbid_models
from cell_harness import scripted_cell
from scripted_fixture import fixtures

@pytest.mark.parametrize('broken_writer',[False,True])
def test_complete_controller_cell_preserves_failure_rollback_and_aggregation(tmp_path,monkeypatch,broken_writer):
    forbid_models();count=[]
    def verifier(tree,role,paths):
        count.append(external_root.tree_sha256(tree))
        return {'passed':False,'checks':[{'name':'controlled_fixture_failure','passed':False,'detail':'Controlled failure, not a frozen test decision.'}]}
    monkeypatch.setattr(hive,'targeted_verify',verifier)
    def full(*a):raise AssertionError('Full verifier must be skipped after failed worker prerequisite')
    monkeypatch.setattr(hive,'verify_tree',full)
    def broken(*a,**k):raise RuntimeError('INSTRUMENTATION ONLY')
    options={'event_writer':broken,'result_writer':broken} if broken_writer else {}
    task,plan,worker,review=fixtures()
    row,run,rec=asyncio.run(scripted_cell(tmp_path/'cell',task,plan,worker,review,options))
    assert len(count)==1 and count[0]!=FREEZE['baseline']['sha256']
    assert run['verification']['full_gate_skipped'] is True
    assert run['semantic_review']['disposition']=='rejected'
    assert run['applied'] is False and run['changed_files']==[]
    assert external_root.tree_sha256(__import__('pathlib').Path(row['stage_root']))==FREEZE['baseline']['sha256']
    assert any(e.get('targeted_correction_repeated') for e in run.get('errors',[]))
    assert 'INSTRUMENTATION ONLY' not in json.dumps(run)
    assert row['measurement_status']==('MEASUREMENT_FAILURE' if broken_writer else 'MEASURED')
    assert row['software_outcome'] is None and row['model_calls']==0
    assert hive.targeted_verify is verifier and hive.verify_tree is full

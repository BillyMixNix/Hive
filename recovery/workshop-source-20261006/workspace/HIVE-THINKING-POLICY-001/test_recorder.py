import json,subprocess
from pathlib import Path
import pytest
from recorder import VerifierRecorder,collect_records

@pytest.mark.parametrize('kind',['targeted','full'])
@pytest.mark.parametrize('result',[{'passed':True,'checks':[]},{'passed':False,'checks':[{'name':'test','passed':False}]},
    {'passed':True,'new_field':{'opaque_to_wrapper':[1,False,None]}},None,{},[],False,'malformed fixture'])
def test_return_identity_arguments_and_exactly_one_invocation(tmp_path,kind,result):
    args=(object(),object(),['one']);kw={'marker':object()};seen=[]
    def original(*a,**k):seen.append((a,k));return result
    rec=VerifierRecorder(tmp_path);wrapped=rec.wrap(original,kind)
    assert wrapped(*args,**kw) is result
    assert len(seen)==1 and all(a is b for a,b in zip(seen[0][0],args)) and seen[0][1]['marker'] is kw['marker']
    assert rec.summary()['measurement_status']=='MEASURED'
    assert rec.records[0]['result']==result
    events=[json.loads(l) for l in (tmp_path/'verification-events.jsonl').read_text().splitlines()]
    assert [r['event'] for r in events]==['verifier_started','verifier_finished']
    assert events[0]['verifier_kind']==kind and rec.records[0]['host_elapsed_seconds']>=0

@pytest.mark.parametrize('kind',['targeted','full'])
@pytest.mark.parametrize('exc',[ValueError('sentinel verifier exception'),subprocess.TimeoutExpired(['sentinel'],240,output=b'partial stdout',stderr=b'partial stderr')])
def test_verifier_exception_identity_is_preserved(tmp_path,kind,exc):
    counter=[]
    def original(*a,**kw):counter.append((a,kw));raise exc
    rec=VerifierRecorder(tmp_path)
    with pytest.raises(type(exc)) as caught:rec.wrap(original,kind)('source',changed_files=['x'])
    assert caught.value is exc and str(caught.value)==str(exc) and len(counter)==1
    assert rec.records[0]['outcome']=='raised' and 'result' not in rec.records[0]
    assert rec.summary()['measurement_status']=='MEASURED'

def broken(*a,**kw):raise TypeError("event() got multiple values for argument 'kind'")

@pytest.mark.parametrize('failure_point',['event','result','capture','clock'])
@pytest.mark.parametrize('verifier_raises',[False,True])
def test_measurement_failure_never_substitutes_for_verifier(tmp_path,failure_point,verifier_raises):
    kwargs={'event_writer':broken} if failure_point=='event' else {'result_writer':broken} if failure_point=='result' else {'capture':broken} if failure_point=='capture' else {'clock':broken}
    rec=VerifierRecorder(tmp_path,**kwargs);seen=[];result={'passed':False};exc=RuntimeError('REAL VERIFIER ERROR')
    def original(*args):seen.append(args);raise_if_needed();return result
    def raise_if_needed():
        if verifier_raises:raise exc
    if verifier_raises:
        with pytest.raises(RuntimeError) as caught:rec.wrap(original,'targeted')('source')
        assert caught.value is exc
    else:assert rec.wrap(original,'targeted')('source') is result
    assert seen==[('source',)]
    summary=rec.summary();assert summary['measurement_status']=='MEASUREMENT_FAILURE' and not summary['scoring_permitted']
    assert summary['software_outcome'] is None
    assert all(e.get('classification','MEASUREMENT_FAILURE')=='MEASUREMENT_FAILURE' for e in summary['measurement_errors'])

@pytest.mark.parametrize('rows',[[{}],[{'verifier_kind':'targeted','outcome':'returned','result':{'passed':True}}],
    [{'host_elapsed_seconds':1}],['partial'],[None],[{'outcome':'raised','verifier_exception':{},'host_elapsed_seconds':float('nan')}],
    [{'outcome':'returned','result':None,'host_elapsed_seconds':True}]])
def test_partial_rows_and_missing_time_are_explicit_measurement_failures(rows):
    result=collect_records(rows)
    assert result['measurement_status']=='MEASUREMENT_FAILURE' and result['software_outcome'] is None and not result['scoring_permitted']

def test_result_writer_cannot_mutate_original_return(tmp_path):
    result={'passed':False,'nested':{'value':[1,2]}}
    def mutate(row):row['result']['passed']=True;row['result']['nested']['value'].clear()
    rec=VerifierRecorder(tmp_path,result_writer=mutate)
    assert rec.wrap(lambda:result,'full')() is result
    assert result=={'passed':False,'nested':{'value':[1,2]}}

def test_uncopyable_result_preserves_identity_and_marks_measurement_failure(tmp_path):
    class Uncopyable:
        def __deepcopy__(self,memo):raise ValueError('copy forbidden')
    result=Uncopyable();rec=VerifierRecorder(tmp_path)
    assert rec.wrap(lambda:result,'targeted')() is result
    assert rec.summary()['measurement_status']=='MEASUREMENT_FAILURE'

def test_repeated_invocations_have_independent_evidence(tmp_path):
    seen=[]
    def original(value):seen.append(value);return value
    rec=VerifierRecorder(tmp_path);wrapped=rec.wrap(original,'targeted')
    values=[{'passed':True},{'passed':False}]
    assert all(wrapped(v) is v for v in values)
    assert seen==values and [r['number'] for r in rec.records]==[1,2]
    assert rec.summary()['complete_outcome_records']==2

def test_returned_timeout_stays_a_return_not_exception(tmp_path):
    result={'passed':False,'checks':[{'name':'timeout','passed':False,'detail':{'timed_out':True,'timeout':240}}]}
    rec=VerifierRecorder(tmp_path);assert rec.wrap(lambda:result,'targeted')() is result
    assert rec.records[0]['outcome']=='returned'

def test_real_subprocess_timeout_remains_timeout(tmp_path):
    import sys
    args=[sys.executable,'-c','import time; time.sleep(1)']
    def verifier():return subprocess.run(args,capture_output=True,timeout=.05)
    rec=VerifierRecorder(tmp_path)
    with pytest.raises(subprocess.TimeoutExpired) as caught:rec.wrap(verifier,'targeted')()
    assert caught.value.cmd==args and caught.value.timeout==.05
    assert rec.records[0]['verifier_exception']['type']=='TimeoutExpired'
    assert rec.summary()['measurement_status']=='MEASURED'

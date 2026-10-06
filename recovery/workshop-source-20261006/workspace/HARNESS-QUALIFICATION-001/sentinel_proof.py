import subprocess
from qcommon import *
from recorder import VerifierRecorder
def main():
    out=HERE/'evidence/sentinels';out.mkdir(parents=True,exist_ok=False);rows=[]
    for kind in ('targeted','full'):
        for behavior in ('return','raise','timeout'):
            marker=f'underlying-{kind}-{behavior}';seen=[];arg=object();token=object();returned={'unique_marker':marker,'passed':behavior=='return'}
            exc=ValueError(marker) if behavior=='raise' else subprocess.TimeoutExpired(marker,240)
            def original(*a,**k):
                seen.append((a,k));(out/(marker+'.txt')).write_text(marker)
                if behavior!='return':raise exc
                return returned
            try:direct=original(arg,token=token);direct_exception=None
            except BaseException as e:direct_exception=e
            before=len(seen);rec=VerifierRecorder(out/marker)
            try:wrapped=rec.wrap(original,kind)(arg,token=token);wrapped_exception=None
            except BaseException as e:wrapped_exception=e
            row={'kind':kind,'behavior':behavior,'marker':marker,'marker_observed':(out/(marker+'.txt')).read_text()==marker,
                'direct_calls':before,'wrapper_underlying_call_delta':len(seen)-before,'argument_identity_preserved':seen[-1][0][0] is arg and seen[-1][1]['token'] is token,
                'return_identity_preserved':wrapped is direct is returned if behavior=='return' else None,
                'exception_identity_preserved':wrapped_exception is direct_exception is exc if behavior!='return' else None,
                'measurement':rec.summary(),'events_present':(out/marker/'verification-events.jsonl').is_file()}
            assert row['wrapper_underlying_call_delta']==1 and row['argument_identity_preserved'] and row['marker_observed'] and row['events_present']
            assert row['return_identity_preserved'] if behavior=='return' else row['exception_identity_preserved']
            rows.append(row)
    save(HERE/'evidence/sentinel-proof.json',rows);print('Six direct/wrapped sentinel equivalence probes passed.')
if __name__=='__main__':main()

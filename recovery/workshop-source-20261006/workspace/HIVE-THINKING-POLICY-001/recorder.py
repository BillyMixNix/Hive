"""Observational verifier wrappers. Measurement validity is a separate channel."""
from __future__ import annotations
import copy,functools,json,math,threading,time
from datetime import datetime,timezone
from pathlib import Path

def wall():return datetime.now(timezone.utc).isoformat()
def error_text(exc):
    try:return str(exc)
    except Exception:return '[exception message unavailable]'

def collect_records(records,failures=()):
    """Incomplete evidence invalidates measurement, never supplies a verdict."""
    issues=list(failures);seconds=0.;complete=0
    for index,row in enumerate(records):
        if not isinstance(row,dict):
            issues.append({'record':index,'stage':'collection','message':'non-object measurement row'});continue
        elapsed=row.get('host_elapsed_seconds')
        if isinstance(elapsed,bool) or not isinstance(elapsed,(int,float)) or not math.isfinite(elapsed) or elapsed<0:
            issues.append({'record':index,'stage':'collection','message':'missing/invalid host_elapsed_seconds'})
        else:seconds+=elapsed
        if row.get('outcome')=='returned' and 'result' in row:complete+=1
        elif row.get('outcome')=='raised' and isinstance(row.get('verifier_exception'),dict):complete+=1
        else:issues.append({'record':index,'stage':'collection','message':'partial verifier observation'})
    return {'measurement_status':'MEASUREMENT_FAILURE' if issues else 'MEASURED','measurement_errors':issues,
        'invocations_observed':len(records),'complete_outcome_records':complete,'known_verification_seconds':seconds,
        'timing_complete':not any('host_elapsed' in e.get('message','') for e in issues),
        'software_outcome':None,'scoring_permitted':not issues}

class VerifierRecorder:
    def __init__(self,root,*,event_writer=None,result_writer=None,clock=time.monotonic,capture=None):
        self.root=Path(root);self.records=[];self.failures=[];self.lock=threading.Lock()
        self.clock=clock;self.capture=capture
        self.event_writer=event_writer or self._event_writer
        self.result_writer=result_writer or self._result_writer

    def _event_writer(self,event_name,/,**fields):
        self.root.mkdir(parents=True,exist_ok=True)
        with self.lock:
            with (self.root/'verification-events.jsonl').open('a',encoding='utf-8') as f:
                f.write(json.dumps({'event':event_name,**fields},ensure_ascii=False)+'\n')

    def _result_writer(self,row):
        self.root.mkdir(parents=True,exist_ok=True)
        (self.root/f"{row['number']:03d}-result.json").write_text(json.dumps(row,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')

    def _observe(self,row,stage,callback):
        try:return callback()
        except Exception as exc:
            # Do not call another potentially failing sink to record this error.
            with self.lock:self.failures.append({'number':row['number'],'verifier_kind':row['verifier_kind'],
                'classification':'MEASUREMENT_FAILURE','stage':stage,'exception_type':type(exc).__name__,'message':error_text(exc)})
            return None

    def wrap(self,original,verifier_kind):
        @functools.wraps(original)
        def wrapped(*args,**kwargs):
            with self.lock:
                row={'number':len(self.records)+1,'verifier_kind':verifier_kind,'outcome':'pending','host_elapsed_seconds':None}
                self.records.append(row)
            row['started_at']=self._observe(row,'wall_clock_start',wall)
            started=self._observe(row,'clock_start',self.clock)
            self._observe(row,'event_start',lambda:self.event_writer('verifier_started',verifier_kind=verifier_kind,number=row['number'],at=row['started_at']))
            if self.capture is not None:
                self._observe(row,'candidate_capture',lambda:self.capture(self.root/str(row['number']),verifier_kind,args,kwargs))
            try:
                # The only underlying call. No verdict conversion or argument copying.
                result=original(*args,**kwargs)
            except BaseException as exc:
                row['outcome']='raised'
                row['verifier_exception']={'type':type(exc).__name__,'message':error_text(exc)}
                raise
            else:
                row['outcome']='returned'
                def capture_result():row['result']=copy.deepcopy(result)
                self._observe(row,'result_copy',capture_result)
                return result
            finally:
                def finish_clock():
                    ended=self.clock()
                    if started is None:raise ValueError('start time unavailable')
                    row['host_elapsed_seconds']=ended-started
                self._observe(row,'clock_finish',finish_clock)
                row['finished_at']=self._observe(row,'wall_clock_finish',wall)
                self._observe(row,'event_finish',lambda:self.event_writer('verifier_finished',verifier_kind=verifier_kind,number=row['number'],outcome=row['outcome'],at=row['finished_at']))
                # Sinks get copies, so a writer cannot mutate the verifier's result.
                self._observe(row,'result_write',lambda:self.result_writer(copy.deepcopy(row)))
        return wrapped

    def summary(self):return collect_records(self.records,self.failures)

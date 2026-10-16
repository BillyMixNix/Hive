"""Resume only the interrupted ninth episode, preserving the eight fixed outcomes.

The archive and original plan are externally pinned. The saved final answer is
accepted only when all preserved final messages agree. No completed case reruns.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from analysis.packet_resume_pilot import (ResumeTrace, execute, messages, audit, MODEL,
                                        SpendingGuard, RequestBudget, OpenAIMeter,
                                        load_api_key, canonical, strict_json, save_json)
from analysis.packet_comparison import sources

ARCHIVE_SHA='a8ec53eeffb4bf7f6ea49083317b24e4630c5bb42212101780c300a235273683'
ORIGINAL_PLAN_SHA='4743ae6c73154f4d5f36bf4066f9d81af7a4126399312fdc9bb33a847aa1cad9'
PRIOR_TOTAL=928159800


def restore_archive(archive, destination):
    archive=Path(archive); destination=Path(destination)
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==ARCHIVE_SHA
    destination.mkdir(exist_ok=False)
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            p=Path(name)
            assert not p.is_absolute() and '..' not in p.parts
        z.extractall(destination)
    directory=destination/'resume-evidence'
    raw=(directory/'plan.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest()==ORIGINAL_PLAN_SHA
    plan=strict_json(raw)
    report=strict_json((directory/'report.json').read_bytes())
    hashes=strict_json((directory/'checksums.json').read_bytes())
    assert hashes=={p.relative_to(directory).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in directory.rglob('*') if p.is_file() and p.name!='checksums.json'}
    assert report['status']=='INCOMPLETE' and len(report['rows'])==8
    assert report['spending']['total_upper_nano_usd']==PRIOR_TOTAL
    assert report['spending']['unresolved_reservation_nano_usd']==0
    assert [{k:r[k] for k in ('case_id','arm')} for r in report['rows']]==plan['schedule'][:8]
    entry=plan['schedule'][8]
    assert entry=={'case_id':'reverse','arm':'packet'}
    case=next(c for c in plan['cases'] if c['id']==entry['case_id'])
    trace=strict_json((directory/'reverse-packet/response-0019.json').read_bytes())
    assert trace['request']['input']==messages(case,'packet')
    finals=[m for m in trace['response']['output'] if m['type']=='message' and m.get('phase')!='commentary']
    assert finals and all(m==finals[0] for m in finals)
    answer=''.join(p['text'] for p in finals[0]['content'] if p['type']=='output_text')
    action=strict_json(answer)
    assert action=={'action':'run_tests','latest_revision_verified':False}
    return directory,plan,report,case,trace,answer


def recover(archive, destination, commitment_file, expected_commitment):
    raw=Path(commitment_file).read_bytes()
    assert hashlib.sha256(raw).hexdigest()==expected_commitment
    commitment=strict_json(raw)
    assert commitment['sources']==sources() and commitment['archive_sha256']==ARCHIVE_SHA
    directory,plan,report,case,trace,answer=restore_archive(archive,destination)
    actions=[strict_json(answer)]
    feedback=execute(case,actions)['steps'][-1]
    conversation=messages(case,'packet')+[{'role':'assistant','content':answer}, {'role':'user','content':canonical(feedback)}]
    old=dict(report['spending'])
    report['recovery']={'source_run':34366080331,'archive_sha256':ARCHIVE_SHA,
                        'commitment_sha256':expected_commitment,'commitment':commitment,
                        'saved_action_replayed':actions[0], 'prior_guard':old}
    guard=None
    class OffsetTrace(ResumeTrace):
        def __init__(self,path): self.directory=path
        def __call__(self, sequence, request, response, secret):
            return super().__call__(sequence+19,request,response,secret)
    try:
        guard=SpendingGuard(directory/'recovery-spending.jsonl',prior_upper_nano_usd=PRIOR_TOTAL)
        budget=RequestBudget(2,guard)
        key=load_api_key(); os.environ.pop('OPENAI_API_KEY',None)
        meter=OpenAIMeter(MODEL,key,2,budget,4096,observer=OffsetTrace(directory/'reverse-packet'))
        for _ in range(2):
            answer=meter(conversation)
            actions.append(strict_json(answer))
            result=execute(case,actions)
            conversation.extend([{'role':'assistant','content':answer}, {'role':'user','content':canonical(result['steps'][-1])}])
            if result['outcome']!='exhausted': break
        usage=dict(meter.usage)
        usage['calls']+=1
        usage['prompt_tokens']+=trace['response']['usage']['input_tokens']
        usage['output_tokens']+=trace['response']['usage']['output_tokens']
        report['rows'].append({'case_id':'reverse','arm':'packet','actions':actions,'result':result,'usage':usage})
        report['status']='COMPLETED'
        report.pop('error_type',None)
    except Exception as exc:
        report['error_type']=type(exc).__name__
    finally:
        os.environ.pop('OPENAI_API_KEY',None)
        if guard:
            new=guard.snapshot(); report['recovery']['new_guard']=new
            report['spending']={**new, 'prior_upper_nano_usd':old['prior_upper_nano_usd'],
                               'measured_usage_upper_nano_usd':old['measured_usage_upper_nano_usd']+new['measured_usage_upper_nano_usd'],
                               'requests_reserved':old['requests_reserved']+new['requests_reserved']}
            guard.close()
        save_json(directory/'report.json',report)
        save_json(directory/'checksums.json',{p.relative_to(directory).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in directory.rglob('*') if p.is_file() and p.name!='checksums.json'})
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('mode',choices=['freeze','run'])
    p.add_argument('path'); p.add_argument('--sha256'); p.add_argument('--archive'); p.add_argument('--output')
    a=p.parse_args()
    if a.mode=='freeze':
        with Path(a.path).open('x') as f:
            f.write(json.dumps({'sources':sources(),'archive_sha256':ARCHIVE_SHA,'original_plan_sha256':ORIGINAL_PLAN_SHA,
                               'prior_total_nano_usd':PRIOR_TOTAL,'remaining_actions':2},indent=2)+'\n')
        print(hashlib.sha256(Path(a.path).read_bytes()).hexdigest())
    else:
        r=recover(a.archive,a.output,a.path,a.sha256)
        print(json.dumps({'status':r['status'],'spending':r['spending']}))
        raise SystemExit(0 if r['status']=='COMPLETED' else 2)

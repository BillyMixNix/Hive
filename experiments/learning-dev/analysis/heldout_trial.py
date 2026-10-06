"""Frozen real-bug comparison: history, compiled capsule, ordinary prose summary."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import sys
import time
import zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from analysis.heldout_capsule import compile_history, excerpt
from analysis.packet_comparison import sources
from analysis.packet_resume_pilot import ResumeTrace
from analysis.packet_spending import SpendingGuard, MODEL, INPUT_NUSD, OUTPUT_NUSD
from analysis.state_packet import canonical
from hive_learning.evaluate import grade,strict_json
from hive_learning.lesson_study import save_json
from hive_learning.openai_adapter import OpenAIMeter,RequestBudget,load_api_key

PRIOR=928598200
ARMS=['raw','capsule','summary']
INSTRUCTION='''Resume this coding repair using the supplied context and the current public workspace.
Return exactly one JSON action per response. You have at most 6 actions.
Available actions:
{"action":"inspect","file":"path","symbol":"function or Class.method"}
{"action":"replace","file":"path","revision":"r2","old":"unique exact source text","new":"replacement source"}
{"action":"run_tests"}
{"action":"complete"}
{"action":"request_context"}
Only the authorized implementation module may be edited; never edit tests or publish.
Use the latest revision ID in replace; each successful edit increments it. A test pass
applies only to that revision. Do not claim completion without current passing tests.
On the FIRST action include "state":{"revision":"current revision ID",
"failed_attempts":["revision IDs of failed prior edits"],"may_edit":["authorized paths"],
"verified":false}. Use null for a field you cannot recover; do not invent it.
Failed baseline tests are not edit attempts. Claims and old test results are not current evidence.'''


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read_archive(path):
    with zipfile.ZipFile(path) as z: return strict_json(z.read('fixtures.json'))
def cost(usage): return usage['prompt_tokens']*INPUT_NUSD+usage['output_tokens']*OUTPUT_NUSD


def initial(context):
    return [{'role':'system','content':INSTRUCTION},{'role':'user','content':context}]


def execute(case,actions):
    files=dict(case['files']); revision=2; verified=False; feedback=[]; terminal=None
    for action in actions:
        if terminal: raise ValueError('action after termination')
        name=action.get('action')
        if name=='inspect':
            path=action.get('file'); symbol=action.get('symbol')
            try: result={'revision':f'r{revision}','file':path,'excerpt':excerpt(files[path],symbol)}
            except (KeyError,StopIteration,ValueError,TypeError): result={'error':'unknown public symbol'}
        elif name=='replace':
            path=action.get('file'); old=action.get('old'); new=action.get('new')
            if path!=case['file'] or action.get('revision')!=f'r{revision}' or not isinstance(old,str) or not old or not isinstance(new,str) or len(new.encode())>16000 or files[path].count(old)!=1:
                result={'error':'scope, revision, or exact-match check rejected edit','revision':f'r{revision}'}
            else:
                files[path]=files[path].replace(old,new,1); revision+=1;verified=False
                result={'edited':path,'revision':f'r{revision}','verified':False}
        elif name=='run_tests':
            g=grade(files,{})
            verified=g['valid'] and g['passed']
            result={'public_tests_passed':verified,'valid':g['valid'],'revision':f'r{revision}'}
        elif name=='complete':
            terminal='submitted'; result={'completion_recorded':True,'revision':f'r{revision}'}
        elif name=='request_context': terminal='requested_context';result={'stopped':'context requested'}
        else: terminal='invalid_action';result={'error':'unsupported action'}
        feedback.append(result)
    return {'files':files,'revision':f'r{revision}','verified':verified,'terminal':terminal or 'exhausted','feedback':feedback}


def assess(case,replay,actions):
    g=grade(replay['files'],case['protected_tests'])
    retention_files={p:v for p,v in replay['files'].items() if p!='test_public.py'}
    retention=grade(retention_files,case['retention_tests'])
    submitted=replay['terminal']=='submitted'
    correct=bool(submitted and replay['verified'] and g['valid'] and g['passed'] and retention['valid'] and retention['passed'])
    return {'correct':correct,'false_completion':submitted and not correct,
            'regression':not (retention['valid'] and retention['passed']),
            'lost_required_state':not actions or actions[0].get('state')!=case['required_state'],
            'evaluation_valid':g['valid'] and retention['valid'],
            'protected_passed':g['passed'],'retention_passed':retention['passed']}


def freeze(archive,path):
    suite=read_archive(archive)
    assert len(suite['cases'])==4
    sizes={}
    for c in suite['cases']:
        packet,state=compile_history(c['history'])
        assert state==c['required_state']
        raw=canonical(c['history'])
        assert len(packet.encode())<len(raw.encode())
        assert len(canonical({'input':initial(raw)}).encode())<240000
        sizes[c['id']]={'raw_bytes':len(raw.encode()),'capsule_bytes':len(packet.encode()),'summary_max_bytes':len(packet.encode())}
        assert not grade(c['files'],c['protected_tests'])['passed']
        assert grade(c['reference_files'],{**c['protected_tests'],**c['retention_tests']})['passed']
    schedule=[{'case_id':c['id'],'arm':a} for c in suite['cases'] for a in ARMS]
    random.Random(9091537).shuffle(schedule)
    plan={'schema':'hive.heldout-capsule.v1','archive_sha256':sha(archive),'sources':sources(),'sizes':sizes,
          'schedule':schedule,'prior_nano_usd':PRIOR,'model':MODEL,'actions_per_episode':6,'max_requests':76,
          'primary':'correct tasks / total metered conservative API dollars, construction included',
          'decision':'Advance only if capsule accuracy is >= both controls, correct/$ >=1.15x both, and no capsule veto or invalid comparison. Descriptive go/no-go, not statistical confirmation.',
          'vetoes':['lost_required_state','regression','false_completion'],
          'size_matching':'Identical UTF-8 byte ceiling for capsule and ordinary summary; actual lengths and token counts reported. No padding, truncation, or size retries.',
          'limitations':'Four public upstream bugs new to Hive; constructed executed interruption logs; file/symbol locators supplied in the public task; no guarantee of model novelty; CPU construction time reported separately, no dollar price assigned.'}
    with Path(path).open('x') as f:f.write(json.dumps(plan,indent=2)+'\n')
    return sha(path)


def summary_prompt(history,limit):
    return [{'role':'system','content':f'''Write an ordinary prose handoff summary of this coding session for a fresh developer.
Preserve current code details needed for repair, current revision, failed edit attempts,
permissions, verification status, and outstanding uncertainty. Distinguish superseded
state from current state. Do not solve the bug or propose a new repair. Return JSON
{{"summary":"your prose summary"}}. Summary must be no more than {limit} UTF-8 bytes.
This is the same size ceiling as the competing capsule. Use enough detail to support
resuming the task; do not pad. No access to reference repairs or hidden tests.'''},
            {'role':'user','content':canonical(history)}]


def run(archive,plan_path,commitment,out):
    assert sha(plan_path)==commitment
    plan=strict_json(Path(plan_path).read_bytes())
    assert plan['sources']==sources() and plan['archive_sha256']==sha(archive) and plan['prior_nano_usd']==PRIOR
    directory=Path(out);directory.mkdir(exist_ok=False)
    (directory/'plan.json').write_bytes(Path(plan_path).read_bytes())
    with Path(str(plan_path)+'.consumed').open('x') as f:f.write(commitment)
    cases={c['id']:c for c in read_archive(archive)['cases']}
    report={'status':'INCOMPLETE','contexts':{},'rows':[],'spending':None}
    guard=None
    try:
        guard=SpendingGuard(directory/'spending.jsonl',prior_upper_nano_usd=PRIOR)
        budget=RequestBudget(76,guard);key=load_api_key();os.environ.pop('OPENAI_API_KEY',None)
        for cid,c in cases.items():
            start=time.perf_counter(); packet,state=compile_history(c['history']); elapsed=time.perf_counter()-start
            maker=OpenAIMeter(MODEL,key,1,budget,4096,observer=ResumeTrace(directory/(cid+'-construction')))
            answer=strict_json(maker(summary_prompt(c['history'],plan['sizes'][cid]['summary_max_bytes'])))
            summary=answer.get('summary')
            if not isinstance(summary,str):raise ValueError('summary constructor returned invalid content')
            compliant=len(summary.encode())<=plan['sizes'][cid]['summary_max_bytes']
            report['contexts'][cid]={'raw':canonical(c['history']),'capsule':packet,'summary':summary,
                                      'summary_compliant':compliant,'construction_usage':maker.usage,
                                      'capsule_cpu_seconds':elapsed,'construction_answer':answer}
            save_json(directory/'report.json',report)
            if not compliant: raise ValueError('summary exceeded common size ceiling; no retry or truncation')
        for entry in plan['schedule']:
            cid,arm=entry['case_id'],entry['arm']; c=cases[cid]
            context=report['contexts'][cid][arm]
            meter=OpenAIMeter(MODEL,key,6,budget,4096,observer=ResumeTrace(directory/(cid+'-'+arm)))
            conversation=initial(context);actions=[]
            for _ in range(6):
                answer=meter(conversation);actions.append(strict_json(answer))
                replay=execute(c,actions)
                conversation.extend([{'role':'assistant','content':answer},{'role':'user','content':canonical(replay['feedback'][-1])}])
                if replay['terminal']!='exhausted':break
            row={**entry,'actions':actions,'replay':replay,'assessment':assess(c,replay,actions),'usage':meter.usage}
            report['rows'].append(row);save_json(directory/'report.json',report)
        report['status']='COMPLETED'
    except Exception as exc:report['error_type']=type(exc).__name__
    finally:
        os.environ.pop('OPENAI_API_KEY',None)
        if guard:report['spending']=guard.snapshot();guard.close()
        save_json(directory/'report.json',report)
        save_json(directory/'checksums.json',{p.relative_to(directory).as_posix():sha(p) for p in directory.rglob('*') if p.is_file() and p.name!='checksums.json'})
    return report


def trace_answer(trace):
    response=trace['response']
    assert response['model']==MODEL and response['service_tier']=='default' and response['status']=='completed'
    finals=[m for m in response['output'] if m['type']=='message' and m.get('phase')!='commentary']
    assert finals and all(m==finals[0] for m in finals)
    return ''.join(p['text'] for p in finals[0]['content'] if p['type']=='output_text')


def audit(archive,directory,commitment):
    directory=Path(directory);assert sha(directory/'plan.json')==commitment
    plan=strict_json((directory/'plan.json').read_bytes());assert sha(archive)==plan['archive_sha256']
    hashes=strict_json((directory/'checksums.json').read_bytes())
    assert hashes=={p.relative_to(directory).as_posix():sha(p) for p in directory.rglob('*') if p.is_file() and p.name!='checksums.json'}
    report=strict_json((directory/'report.json').read_bytes()); assert report['status']=='COMPLETED'
    assert [{k:r[k] for k in ('case_id','arm')} for r in report['rows']]==plan['schedule']
    cases={c['id']:c for c in read_archive(archive)['cases']}
    totals={a:{'correct':0,'false_completion':0,'lost_required_state':0,'regression':0,'nano_usd':0,'calls':0,'input_tokens':0,'output_tokens':0} for a in ARMS}
    calls=charge=0
    def check_usage(traces,usage):
        assert len(traces)==usage['calls']
        assert sum(t['response']['usage']['input_tokens'] for t in traces)==usage['prompt_tokens']
        assert sum(t['response']['usage']['output_tokens'] for t in traces)==usage['output_tokens']
    for cid,c in cases.items():
        contexts=report['contexts'][cid];packet,_=compile_history(c['history'])
        assert contexts['raw']==canonical(c['history']) and contexts['capsule']==packet
        assert contexts['summary_compliant'] and len(contexts['summary'].encode())<=len(packet.encode())
        traces=[strict_json(p.read_bytes()) for p in sorted((directory/(cid+'-construction')).glob('response-*.json'))]
        assert len(traces)==1 and traces[0]['request']['input']==summary_prompt(c['history'],len(packet.encode()))
        assert strict_json(trace_answer(traces[0]))['summary']==contexts['summary']
        usage=contexts['construction_usage'];check_usage(traces,usage)
        charge+=cost(usage);calls+=usage['calls'];totals['summary']['nano_usd']+=cost(usage)
        totals['summary']['calls']+=usage['calls'];totals['summary']['input_tokens']+=usage['prompt_tokens'];totals['summary']['output_tokens']+=usage['output_tokens']
    for row in report['rows']:
        c=cases[row['case_id']];arm=row['arm'];actions=row['actions']
        replay=execute(c,actions);assert replay==row['replay']
        assessment=assess(c,replay,actions);assert assessment==row['assessment'];assert assessment['evaluation_valid']
        conversation=initial(report['contexts'][c['id']][arm])
        traces=[strict_json(p.read_bytes()) for p in sorted((directory/(c['id']+'-'+arm)).glob('response-*.json'))]
        assert len(traces)==len(actions)
        for i,(t,action) in enumerate(zip(traces,actions)):
            assert t['request']['input']==conversation
            answer=trace_answer(t);assert strict_json(answer)==action
            conversation.extend([{'role':'assistant','content':answer},{'role':'user','content':canonical(replay['feedback'][i])}])
        usage=row['usage'];check_usage(traces,usage);charge+=cost(usage);calls+=usage['calls']
        for k in ['correct','false_completion','lost_required_state','regression']:totals[arm][k]+=int(assessment[k])
        totals[arm]['nano_usd']+=cost(usage);totals[arm]['calls']+=usage['calls']
        totals[arm]['input_tokens']+=usage['prompt_tokens'];totals[arm]['output_tokens']+=usage['output_tokens']
    spending=report['spending']
    assert spending['prior_upper_nano_usd']==PRIOR and spending['requests_reserved']==calls and spending['unresolved_reservation_nano_usd']==0
    assert spending['measured_usage_upper_nano_usd']==charge and spending['total_upper_nano_usd']==PRIOR+charge<=5_000_000_000
    journal=[strict_json(l) for l in (directory/'spending.jsonl').read_text().splitlines()]
    assert journal[-1]['total_upper_nano_usd']==spending['total_upper_nano_usd']
    for a,t in totals.items():t['correct_per_api_dollar']=t['correct']/(t['nano_usd']/1e9) if t['nano_usd'] else 0
    cap=totals['capsule']
    veto=any(cap[k] for k in plan['vetoes'])
    advance=not veto and all(cap['correct']>=totals[a]['correct'] and cap['correct_per_api_dollar']>=1.15*totals[a]['correct_per_api_dollar'] for a in ['raw','summary']) and cap['correct']>0
    return {'verdict':'REPLAY_VERIFIED_DESCRIPTIVE','decision':'ADVANCE_TO_REPLICATION' if advance else 'DO_NOT_ADVANCE',
            'capsule_veto':veto,'totals':totals,'spending':spending,
            'context_bytes':{cid:{a:len(x[a].encode()) for a in ARMS} for cid,x in report['contexts'].items()},
            'capsule_cpu_seconds':sum(x['capsule_cpu_seconds'] for x in report['contexts'].values()),
            'limits':plan['limitations'],'size_matching':plan['size_matching']}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['freeze','run','audit']);p.add_argument('archive');p.add_argument('path');p.add_argument('--sha256');p.add_argument('--output');a=p.parse_args()
    if a.mode=='freeze':print(freeze(a.archive,a.path))
    elif a.mode=='audit':print(json.dumps(audit(a.archive,a.path,a.sha256),indent=2))
    else:
        r=run(a.archive,a.path,a.sha256,a.output);print(json.dumps({'status':r['status'],'episodes':len(r['rows']),'spending':r['spending'],'error_type':r.get('error_type')}));raise SystemExit(0 if r['status']=='COMPLETED' else 2)

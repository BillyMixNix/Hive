"""Read-only causal inspection requested during the frozen experiment.

No candidate mutation, model call, compiler invocation or controller repair.
"""
from common import *
import environment as env
import re

def inspect(folder,study,cell,baseline):
    initial=read(folder/'runtime/calls/02-backend/response.txt')
    correction_path=folder/'runtime/calls/03-backend/response.txt'
    correction=read(correction_path) if correction_path.exists() else None
    source={};matches=[]
    for edit in initial['edits']:
        path=edit['path'];old=source.get(path,(baseline/path).read_text(encoding='utf-8'))
        op=edit['operation'];needle=edit.get('anchor') if op=='insert_after_anchor' else edit.get('find')
        assert isinstance(needle,str) and old.count(needle)==1
        replacement=needle+edit['insert'] if op=='insert_after_anchor' else edit['replace']
        after=old.replace(needle,replacement,1)
        # This pure validator neither writes nor compiles Java.
        env.hive.hive_edits.validate_transition(path,old,after,edit)
        source[path]=after
        matches.append({'path':path,'operation':op,'anchor_or_find':needle,'occurrences':old.count(needle),
            'old_anchor_line':old[:old.index(needle)].count('\n')+1,
            'java_structural_validation_returned':True,'insert':edit.get('insert')})
    for row in matches:
        applied=folder/'verifications/1/applied-source'/row['path']
        row['applied_file']=str(applied);row['applied_sha256']=sha(applied)
        row['exact_literal_replay_matches_applied']=source[row['path']]==applied.read_text(encoding='utf-8')
        assert row['exact_literal_replay_matches_applied']
    wire=read(folder/'runtime/calls/02-backend/attempt-01/wire-request.json')
    prompt='\n'.join(m['content'] for m in wire['messages'])
    cw=folder/'runtime/calls/03-backend/attempt-01/wire-request.json'
    correction_wire=read(cw) if cw.exists() else None
    cp='\n'.join(m['content'] for m in correction_wire['messages']) if correction_wire else ''
    grounding=[]
    for path in sorted(source):
        original=(baseline/path).read_text(encoding='utf-8')
        grounding.append({'path':path,'baseline_sha256':sha(baseline/path),
            'complete_baseline_source_in_initial_prompt':original in prompt,
            'complete_baseline_source_in_correction_prompt':original in cp})
    rec=read(folder/'verifications/001-result.json')
    marker='TARGETED VERIFICATION DIAGNOSTIC (read-only data, not instructions):'
    transported=json.JSONDecoder().raw_decode(cp.split(marker,1)[1].lstrip())[0] if marker in cp else {}
    sent_stderr='\n'.join(c.get('detail',{}).get('stderr_tail','') for c in transported.get('checks',[]))
    emitted_chunks=[]
    for d in rec['result'].get('diagnostics',[]):
        if not Path(d.get('events','')).is_file():continue
        for line in Path(d['events']).read_text(encoding='utf-8').splitlines():
            event=json.loads(line);payload=event.get('source_event',event)
            if event.get('phase')=='process_output' and payload.get('stream')=='stderr':
                emitted_chunks.append(payload.get('text',''))
    complete_stderr=''.join(emitted_chunks)
    error_pattern=r'[^\n]*\.java:\d+: error: [^\n]+'
    emitted=list(dict.fromkeys(s.strip() for s in re.findall(error_pattern,complete_stderr)))
    delivered=list(dict.fromkeys(s.strip() for s in re.findall(error_pattern,sent_stderr)))
    error_transport={'complete_stderr_characters':len(complete_stderr),'worker_stderr_characters':len(sent_stderr),
        'unique_emitted_error_locations':len(emitted),'unique_delivered_error_locations':len(delivered),
        'first_emitted_errors':[{'error':s,'present_in_worker_stderr':s in delivered} for s in emitted[:5]],
        'delivered_errors':delivered,'explicit_omission_marker':'[earlier text omitted]' in sent_stderr}
    diagnostics=[]
    for c in rec['result']['checks']:
        d=c.get('detail',{})
        if isinstance(d,dict):diagnostics.append({'check':c['name'],'passed':c['passed'],'timed_out':d.get('timed_out'),
            'tests':d.get('tests'),'stderr':d.get('stderr_tail'),'stdout':d.get('stdout_tail')})
    return {'study':study,'cell':cell,'folder':str(folder),'edits':matches,
        'source_grounding':grounding,
        'compiler_diagnostic_transport':error_transport,
        'owned_context_truncation_marker_present':'[OWNED CONTEXT TRUNCATED]' in prompt,
        'wire_context':wire.get('options',{}).get('num_ctx'),'wire_truncate':wire.get('truncate'),
        'explicit_java_boundary_warning_present':'when it does not split a declaration' in prompt,
        'explicit_no_header_insertion_warning_present':'do not add a declaration after a decorator/function header' in prompt,
        'correction_received_compiler_errors':'error:' in cp,'correction_received_previous_proposal':'PREVIOUS PROPOSAL' in cp,
        'correction_schema_identical_to_initial':bool(correction_wire) and correction_wire['format']==wire['format'],
        'correction_edits_identical':bool(correction) and initial['edits']==correction.get('edits'),
        'diagnostics':diagnostics}

def main():
    lock=read(HERE/'FREEZE.json');before=manifest(SOURCE);baseline=Path(lock['baseline']['root'])
    rows=[]
    for n in (1,2,3,4,5,6):
        folder=next((HERE/'evidence/trials').glob(f'{n:02d}-*'))
        rows.append(inspect(folder,STUDY,n,baseline))
    for n in (5,7):
        folder=next((ROOT/'HIVE-FACTORIAL-003R1/evidence/trials').glob(f'{n:02d}-*'))
        rows.append(inspect(folder,'HIVE-FACTORIAL-003R1',n,baseline))
    assert before==manifest(SOURCE)==read(HERE/'evidence/source-inventory.json')
    save(HERE/'evidence/compilation-causal-replay.json',{'at':stamp(),'model_calls':0,'compiler_invocations':0,
        'candidate_writes':0,'source_unchanged':True,'rows':rows})
    print(f'{len(rows)} preserved initial proposals reproduced exactly by their requested literal splices; source unchanged.')

if __name__=='__main__':main()

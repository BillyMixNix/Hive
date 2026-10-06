"""Read-only historical channel/timing reconstruction; never interpret reasoning text."""
from common import *
OLD=ROOT/'HIVE-FACTORIAL-003R1'
SELECTED=(3,6,8,9,12,15)

def main():
    lock=read(OLD/'FREEZE.json'); rows=[]
    for result in read(OLD/'evidence/raw-results.json'):
        if result['ordinal'] not in SELECTED: continue
        folder=Path(result['evidence']); calls=read(folder/'runtime/calls.json')
        failed=next(c for c in calls if c['role']=='backend' and c['status']=='failed')
        call_dir=folder/'runtime/calls'/f"{failed['number']:02d}-backend"
        attempt=call_dir/'attempt-01'; body=read(attempt/'wire-request.json'); trans=read(attempt/'transport.json')
        start=datetime.fromisoformat(trans['started_at']); channels={k:{'chunks':0,'characters':0,'first_seconds':None,'last_seconds':None} for k in ('thinking','content')}
        terminal=None;chunk_errors=[]
        for line in (attempt/'response.ndjson').read_text(encoding='utf-8').splitlines():
            try:chunk=json.loads(line)
            except ValueError as exc:chunk_errors.append(str(exc));continue
            t=(datetime.fromisoformat(chunk['created_at'].replace('Z','+00:00'))-start).total_seconds()
            for key,channel in channels.items():
                val=(chunk.get('message') or {}).get(key,'')
                if val:
                    channel['chunks']+=1;channel['characters']+=len(val)
                    if channel['first_seconds'] is None:channel['first_seconds']=t
                    channel['last_seconds']=t
            if chunk.get('done'):terminal=chunk
        resources=[]
        for p in sorted((folder/'runtime').glob('*.json')):
            if p.name=='calls.json':continue
            r=read(p)
            if 'host_memory' not in r:continue
            h=r.get('host_memory',{}).get('data',{}).get('host',{})
            resources.append({'file':str(p),'at':r.get('started_at'),'host':h,'gpu':r.get('gpu_memory'), 'residency':r.get('/api/ps')})
        row={'historical_cell':result['ordinal'],'task':result['task_id'],'replicate':result['replicate'],'model':result['model'],
            'model_digest':next(m['current']['digest'] for m in lock['models'] if m['current']['name']==result['model']),
            'run_id':result['run_id'],'role':'backend','call_number':failed['number'],'call_kind':'targeted correction' if result['ordinal']==15 else 'initial worker',
            'request':str(attempt/'wire-request.json'),'request_sha256':sha(attempt/'wire-request.json'),'input_token_count':None,
            'input_token_limitation':'No terminal provider accounting for interrupted stream; characters are not token counts.',
            'options':body['options'],'truncate':body.get('truncate'),'think_present':'think' in body,
            'deadline_seconds':failed['provider_settings']['total_timeout'],'http_status':trans['http_status'],
            'first_stream_seconds':(datetime.fromisoformat(trans['first_stream_bytes_at'])-start).total_seconds(),
            'channels':channels,'final_answer_complete':False,'terminal_chunk':terminal,'parse_errors':chunk_errors,
            'provider_terminal_state':failed['error'],'call_elapsed_seconds':failed['elapsed_seconds'],
            'historical_frontier':result['software_frontier'],'transitions':result['transitions'],
            'resource_observations':resources,'evidence_folder':str(folder)}
        rows.append(row)
    assert [r['historical_cell'] for r in rows]==list(SELECTED)
    save(HERE/'evidence/historical-calls.json',rows)
    md=['# Historical worker deadline reconstruction','',
        'Read-only reconstruction from immutable FACTORIAL-003R1 requests, streams, transport timestamps, logical-call records and resource snapshots. No historical outcome is rescored. Channel presence, size and timing are measured; reasoning text is not analyzed.',
        '', 'All six used HTTP 200 streaming, qwen3:8b digest `'+rows[0]['model_digest']+'`, context 12288, worker output cap 6000, temperature 0.1, `truncate:false`; `think` was omitted. The normal total generation deadline was 900 seconds. None has a completed terminal response. Input/output token accounting for these interrupted calls is unknown.',
        '', '| Cell | Task / replicate | Call | First stream s | First answer s | Thinking characters | Answer characters | Deadline result |', '|---|---|---|---:|---:|---:|---:|---|']
    for r in rows:
        c=r['channels'];a=c['content']['first_seconds']
        md.append(f"| {r['historical_cell']} | {r['task']} / {r['replicate']} | {r['call_kind']} | {r['first_stream_seconds']:.3f} | {a if a is not None else 'none'} | {c['thinking']['characters']} | {c['content']['characters']} | incomplete / generation deadline |")
    md+=['','Provider-created chunk timestamps support channel latency estimates, not exact host receipt timestamps. Counts above are characters, not tokens. Raw request hashes, provider errors, per-snapshot host/virtual/GPU memory, residency and evidence paths are in `evidence/historical-calls.json`.',
        '', '**Denominator distinction:** the selected failed calls completed 0/6. Five are initial-worker calls. Cell 15 is a correction timeout after a completed initial worker, executable edit and frozen behavioral FAIL. Historical cohort-level any-worker response and executable edit are therefore 1/6, targeted verification 1/6, frozen acceptance and full-gate success 0/6. The prospective experiment runs whole fresh cells and may follow different call paths.',
        '', '## Exact request identities']
    for r in rows:md+=['',f"- Cell {r['historical_cell']}: `{r['request_sha256']}`; [{r['run_id']}]({r['request'].replace(chr(92),'/')}); frontier `{r['historical_frontier']}`."]
    (HERE/'historical-timeout-reconstruction.md').write_text('\n'.join(md)+'\n',encoding='utf-8')
    print('Reconstructed six calls; no production edits or generation.')

if __name__=='__main__':main()

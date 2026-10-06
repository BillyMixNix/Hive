"""Read-only reviewer-history discovery. Never invokes a provider or verifier."""
import collections,hashlib,json,subprocess,sys
from pathlib import Path
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
SOURCE=HERE.parent/'HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/repaired-workshop'
ROOTS=[HERE.parent,
 Path('C:/Users/billy/Documents/Codex/2026-09-13/referenced-chatgpt-conversation-this-is-an/work'),
 Path('C:/Users/billy/Documents/Codex/2026-09-22/atm10-ai-companion-autonomous-build-mega/local-model-trial')]
def sha(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def save(p,x):
 p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,indent=2,ensure_ascii=False,default=str)+'\n',encoding='utf-8')
def main():
 assert not (HERE/'evidence/inventory.json').exists(),'Preserve original inventory'
 save(HERE/'evidence/source-before.json',{p.relative_to(SOURCE).as_posix():sha(p) for p in SOURCE.rglob('*') if p.is_file()})
 discovered=[];scans=[];objects=[];failures=[];custom=[]
 for root in ROOTS:
  args=['rg','--files','--hidden','-g','run.json','-g','result.json']
  for glob in ['.git','node_modules','approved-gradle-caches','build','stage','snapshots','external_candidates','repaired-workshop',
    '.pytest_cache','__pycache__','tooling','pytest*','tmp*']:
   args+=['-g',f'!**/{glob}/**']
  args.append(str(root));cp=subprocess.run(args,capture_output=True,text=True)
  paths=[Path(x) for x in cp.stdout.splitlines() if x and str(HERE) not in x]
  scans.append({'root':str(root),'command':args,'returncode':cp.returncode,'stderr':cp.stderr,'files':len(paths)})
  discovered.extend(paths)
 for p in sorted(set(discovered)):
  try:d=json.loads(p.read_text(encoding='utf-8-sig'))
  except Exception as e:failures.append({'path':str(p),'error':str(e)});continue
  if not isinstance(d,dict):continue
  if 'agents' in d and ('request' in d or 'review' in d):
   agents=d.get('agents') or {};rev=agents.get('reviewer') or {};review=d.get('review') or {}
   if not isinstance(rev,dict):rev={'untyped':rev}
   metadata=d.get('metadata') or {};calls=metadata.get('agent_calls') or []
   verify=d.get('verification') or {};errors=d.get('errors') or []
   raw=rev.get('raw');parsed=None
   if isinstance(raw,str):
    try:parsed=json.loads(raw)
    except ValueError:pass
   records={'path':str(p),'sha256':sha(p),'id':d.get('id') or d.get('run_id'),'status':d.get('status'),
    'request':d.get('request'),'model':d.get('local_model'),'metadata_experiment':metadata.get('experiment'),
    'metadata_keys':list(metadata),'agent_keys':list(agents),'changed_files':d.get('changed_files'),
    'verification_passed':verify.get('passed'),'verification_checks':[{k:c.get(k) for k in ('name','passed')} for c in verify.get('checks',[]) if isinstance(c,dict)],
    'full_gate_skipped':verify.get('full_gate_skipped'),'review':review,'reviewer':rev,'raw_review_parsed':parsed,
    'reviewer_calls':[c for c in calls if isinstance(c,dict) and c.get('role')=='reviewer'],
    'reviewer_traces':[{k:t.get(k) for k in ('role','status','response_text','wall_seconds','started_at','finished_at')} for t in d.get('prompt_trace',[]) if t.get('role')=='reviewer'],
    'errors':errors,'provenance':d.get('provenance')}
   objects.append(records)
  elif p.name=='result.json':
   custom.append({'path':str(p),'sha256':sha(p),'keys':list(d),'status':d.get('status'),'accepted':d.get('accepted'),
    'review_fields':{k:v for k,v in d.items() if 'review' in k.lower()}})
 grouped=collections.defaultdict(list)
 for r in objects:grouped[r['id'] or r['sha256']].append(r)
 groups=[]
 for rid,items in grouped.items():
  # Preserve all variants; prefer richest evidence for the first inspection only.
  items.sort(key=lambda r:(bool(r['reviewer'].get('raw')),bool(r['reviewer_calls']),bool(r['reviewer_traces']),len(r['metadata_keys'])),reverse=True)
  groups.append({'id':rid,'copies':len(items),'distinct_file_hashes':len({r['sha256'] for r in items}),'records':items})
 save(HERE/'evidence/inventory.json',{'scans':scans,'parse_failures':failures,'run_files':len(objects),'unique_run_ids':len(groups),'groups':groups,'other_result_files':custom})
 print(json.dumps({'scans':[{k:v for k,v in x.items() if k!='command'} for x in scans],'run_files':len(objects),'unique_run_ids':len(groups),'parse_failures':failures,
  'review_counts':dict(collections.Counter(str((g['records'][0]['verification_passed'],g['records'][0]['raw_review_parsed'].get('approve') if isinstance(g['records'][0]['raw_review_parsed'],dict) else None)) for g in groups)),
  'review_veto_or_issue_candidates':[{'id':g['id'],'copies':g['copies'],'path':g['records'][0]['path'],'verify':g['records'][0]['verification_passed'],
   'raw':g['records'][0]['reviewer'].get('raw'),'review':g['records'][0]['review']} for g in groups if g['records'][0]['reviewer'].get('raw') and (not isinstance(g['records'][0]['raw_review_parsed'],dict) or g['records'][0]['raw_review_parsed'].get('approve') is not True or g['records'][0]['raw_review_parsed'].get('issues'))]},indent=2,default=str))
if __name__=='__main__':main()

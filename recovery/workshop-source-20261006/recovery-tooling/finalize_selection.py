"""Select archival copies only. Original workspace remains read-only."""
from snapshot import *

def main():
 rows=[json.loads(s) for s in (OUT/'WORKSPACE-MANIFEST.jsonl').read_text(encoding='utf-8').splitlines()]
 assert not json.loads((OUT/'INVENTORY-ERRORS.json').read_bytes())
 decisions=json.loads((AREA/'scan-decisions.json').read_bytes())
 moves=[];changes=[]
 for r in rows:
  p=Path(r['origin']);rel=Path(r['relative_path']);reason=r['excluded_reason']
  if reason=='compiled_or_dependency_jar' and tuple(rel.parts[-3:])==('gradle','wrapper','gradle-wrapper.jar'):
   reason=None
  if 'approved-gradle-caches' in rel.parts:
   provenance_names={'provenance.json','external-build-inputs.provenance.json','external-build-inputs.manifest.json','artifacts.manifest.json'}
   if not ('.hive-priming-provenance' in rel.parts and p.name in provenance_names):
    reason='downloaded_gradle_cache_payload'
  if p.suffix.lower()=='.pyd':reason='compiled_binary_or_runtime_cache'
  for i,x in enumerate(rel.parts[:-1]):
   if x.lower() in {'data','media','self_snapshots','snapshots','workspace'} and (p.parents[len(rel.parts)-i-1]/'app.py').is_file():
    reason='application_runtime_or_user_state';break
  if r['path'] in decisions:
   decision=decisions[r['path']]
   if decision['include']:
    assert reason=='secret_scan_requires_review'
    reason=None
   else:reason='secret_or_private_state_review_exclusion'
  if reason!=r['excluded_reason']:
   changes.append({'path':r['path'],'before':r['excluded_reason'],'after':reason})
   dest=OUT/r['path']
   if reason is not None and dest.is_file():
    moves.append({'source':str(dest),'destination':str(AREA/'excluded-local-copies'/r['path'])})
   elif reason is None:
    data=p.read_bytes();assert hashlib.sha256(data).hexdigest()==r['sha256']
    dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
  r.update(excluded_reason=reason,included=reason is None)
 (AREA/'quarantine-moves.json').write_bytes(json.dumps(moves).encode('utf-8'))
 (AREA/'inventory-initial.jsonl').write_bytes((OUT/'WORKSPACE-MANIFEST.jsonl').read_bytes())
 for name,selected in [('WORKSPACE-MANIFEST.jsonl',rows),('INCLUDED-FILES.jsonl',[r for r in rows if r['included']]),('EXCLUDED-FILES.jsonl',[r for r in rows if not r['included']])]:
  with (OUT/name).open('wb') as f:
   for r in selected:f.write(canonical(r)+b'\n')
 summary=json.loads((OUT/'MANIFEST-SUMMARY.json').read_bytes())
 summary.update(manifest_sha256=digest(OUT/'WORKSPACE-MANIFEST.jsonl'),included_files=sum(r['included'] for r in rows),excluded_files=sum(not r['included'] for r in rows),excluded_reasons=dict(collections.Counter(r['excluded_reason'] for r in rows if not r['included'])),included_bytes=sum(r['bytes'] for r in rows if r['included']))
 summary['included_tree_sha256']=hashlib.sha256(canonical({r['path']:{k:r[k] for k in ('sha256','bytes','type')} for r in rows if r['included']})).hexdigest()
 write('MANIFEST-SUMMARY.json',summary);write('SELECTION-REVIEW.json',{'changes':changes,'reviewed_scan_decisions':decisions})
 # Capture status of generated nested test repositories without altering their Git config.
 nested=set()
 for r in rows:
  parts=Path(r['origin']).parts
  if '.git' in parts:nested.add(str(Path(*parts[:parts.index('.git')])))
 states=json.loads((OUT/'GIT-STATE.json').read_bytes())
 for root in sorted(nested):
  if not any(s['root']==root for s in states):states.append(git_state(Path(root)))
 write('GIT-STATE.json',states)
 print(json.dumps({'included':summary['included_files'],'bytes':summary['included_bytes'],'excluded':summary['excluded_files'],'quarantine_moves':len(moves),'changes':len(changes),'nested_git':len(nested)},indent=2))

if __name__=='__main__':main()

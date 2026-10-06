"""Existing attestation only. Harmless isolated mutations, never a policy expansion."""
from qcommon import *
def main():
    configure();forbid_models();root=HERE/'evidence/nfrt-preflight';root.mkdir(parents=True,exist_ok=False)
    doc=read(FREEZE['nfrt']['manifest']);assert sha(FREEZE['nfrt']['manifest'])==FREEZE['nfrt']['sha256']
    allowed=set(doc['independent_java_sources']);rows=[]
    for task in FREEZE['tasks']:
        stage=root/task['id'];external_root.copy_candidate_tree(Path(FREEZE['baseline']['root']),stage,root)
        for rel in task['files']:
            with (stage/rel).open('ab') as f:f.write(b'\n// Harmless isolated NFRT scope qualification sentinel.\n')
        row={'task':task['id'],'authorized_write_scope':task['files'],'attested_mutable_files':sorted(allowed),
            'static_scope_compatible':set(task['files'])<=allowed,'candidate_sha256':external_root.tree_sha256(stage)}
        try:result=attest(stage);row.update(probe_accepted=bool(result),error=None)
        except Exception as exc:row.update(probe_accepted=False,error={'type':type(exc).__name__,'message':str(exc)})
        row['compatible']=row['static_scope_compatible'] and row['probe_accepted']
        rows.append(row);print(row['task'],row['compatible'],row['error'],flush=True)
    save(root/'matrix.json',{'attestation_sha256':sha(FREEZE['nfrt']['manifest']),'policy_changed':False,'future_factorial':'READY' if all(r['compatible'] for r in rows) else 'NOT READY','tasks':rows})
    lines=['# Existing NFRT scope preflight','',f"Attestation: `{FREEZE['nfrt']['sha256']}`. No policy or attestation was changed.",'','| Task | Authorized write scope | Existing attestation compatible? |','|---|---|---|']
    lines += [f"| {r['task']} | {'; '.join(r['authorized_write_scope'])} | {'yes' if r['compatible'] else 'no'} |" for r in rows]
    lines += ['','Each row was checked against the host-attested mutable set and the actual configured_seed validator after appending a harmless comment to the task-authorized files in an isolated baseline copy. Those fixtures are not software-task candidates and were never compiled.','', '**Future J001–J004 factorial: NOT READY.** J002–J004 require a separately justified attestation policy before another study. No such repair is performed here.']
    (HERE/'nfrt-scope-matrix.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
if __name__=='__main__':main()

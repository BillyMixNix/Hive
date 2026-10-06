"""Four fresh authorized-scope compatibility probes; task IDs label evidence only."""
from common import *
def main():
    root=OUT/'scope-preflight';root.mkdir(exist_ok=False);rows=[]
    manifest=OUT/'approved-nfrt-seed-v2.json'
    for task in FREEZE['tasks']:
        candidate=root/task['id'];external_root.copy_candidate_tree(BASE,candidate,root)
        for path in task['files']:
            with (candidate/path).open('a',encoding='utf-8',newline='') as f:f.write('\n// Harmless source-class compatibility probe.\n')
        before=external_root.tree_sha256(candidate)
        row={'task':task['id'],'authorized_write_scope':task['files'],'candidate_sha256':before}
        try:
            result=attest(candidate,manifest);row.update(compatible=True,attestation_sha256=result['sha256'])
        except Exception as e:row.update(compatible=False,error={'type':type(e).__name__,'message':str(e)})
        row['candidate_unchanged']=external_root.tree_sha256(candidate)==before
        rows.append(row);save(root/'matrix.json',{'tasks':rows,'model_calls':0});print(task['id'],row['compatible'],flush=True)
    table='\n'.join(f"| {r['task']} | {'; '.join(r['authorized_write_scope'])} | {'yes' if r['compatible'] else 'no'} |" for r in rows)
    (HERE/'factorial-scope-matrix.md').write_text('# Four-task NFRT scope preflight\n\n| Task | Authorized source scope | Compatible after generalized policy? |\n|---|---|---|\n'+table+'\n\nThese fresh baseline copies contain harmless comments only. IDs label diagnostics; production authorization uses the attested main source class. This is compatibility evidence, not task success or authorization to start a factorial.\n',encoding='utf-8')
    assert all(r['compatible'] and r['candidate_unchanged'] for r in rows)
if __name__=='__main__':main()

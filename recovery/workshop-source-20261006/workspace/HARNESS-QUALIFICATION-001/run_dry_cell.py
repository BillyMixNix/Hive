"""One scripted complete cell with actual targeted verification; no model calls."""
import asyncio
from qcommon import *
from cell_harness import scripted_cell
from scripted_fixture import fixtures
from run_controls import invocation_evidence,canonical
def main():
    configure();forbid_models();assert manifest(SOURCE)==read(HERE/'evidence/production-before.json')
    output=HERE/'evidence/scripted-cell';task,plan,worker,review=fixtures()
    row,run,rec=asyncio.run(scripted_cell(output,task,plan,worker,review))
    proof=invocation_evidence(Path(row['stage_root']).parent)
    report=rec.records[0]['result'] if rec.records else None
    checks={'one_wrapped_invocation':len(rec.records)==1,'one_native_invocation':len(proof)==1,
        'normal_targeted_failure':report is not None and report.get('passed') is False,
        'stage_rolled_back':external_root.tree_sha256(Path(row['stage_root']))==FREEZE['baseline']['sha256'],
        'origin_unchanged':external_root.tree_sha256(Path(row['candidate_root']))==FREEZE['baseline']['sha256'],
        'review_recorded':row['semantic_review']=='rejected','full_gate_correctly_skipped':run['verification'].get('full_gate_skipped') is True,
        'repeated_proposal_rejected':any(e.get('targeted_correction_repeated') for e in run.get('errors',[])),
        'measurement_complete':row['measurement_status']=='MEASURED','not_applied':run.get('applied') is False,'aggregate_row_created':(output/'aggregate-row.json').is_file()}
    save(output/'qualification.json',{'checks':checks,'passed':all(checks.values()),'native_invocation_evidence':proof,
        'canonical_verifier_result':canonical(report) if report is not None else None,'model_calls':0,'software_success_trial':False})
    print(__import__('json').dumps(checks,indent=2),flush=True)
    assert all(checks.values()),checks
if __name__=='__main__':main()

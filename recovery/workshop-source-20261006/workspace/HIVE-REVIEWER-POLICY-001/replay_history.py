"""Counterfactual state projection only. Never saves, verifies or applies a historical run."""
import copy,hashlib,json,sys
from pathlib import Path
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'repaired-workshop'))
from workshop import hive_review

audit=json.loads((HERE.parent/'HIVE-REVIEWER-ANALYSIS-001/evidence/history-audit.json').read_text())
rows=[]
for item in audit['runs']:
    if item['category'] not in ('REVIEW_WITH_PROVIDER_TELEMETRY','LEGACY_REVIEW_WITHOUT_CALL_TELEMETRY','REVIEW_ATTEMPT_WITHOUT_DECISION'):
        continue
    path=Path(item['source']); before=hashlib.sha256(path.read_bytes()).hexdigest()
    original=json.loads(path.read_text(encoding='utf-8'))
    simulated=copy.deepcopy(original)
    simulated['review_policy_version']=hive_review.POLICY_VERSION
    simulated['review_policy']={'independent_review_required':False}
    simulated['promotion_authorization']='not_authorized'
    simulated['errors']=[e for e in simulated.get('errors',[]) if not isinstance(e,dict) or e.get('role')!='reviewer']
    if item['raw_decision'] is not None:
        try:
            decision=hive_review.validate_review(item['raw_decision'])
            review={'disposition':'approved' if decision['approve'] is True else 'rejected','decision':decision}
        except hive_review.ReviewProtocolError as exc:
            review={'disposition':'invalid','decision':None,'validation_error':str(exc)}
    else:
        review={'disposition':'unavailable','decision':None,'failure':copy.deepcopy(item['reviewer_calls'])}
    simulated['semantic_review']=review
    actual=hive_review.state(simulated)
    ordinary=copy.deepcopy(simulated)
    ordinary['metadata']=copy.deepcopy(ordinary.get('metadata') or {})
    ordinary['metadata'].pop('external_root',None)
    ordinary['metadata'].pop('external_root_mode',None)
    ordinary_state=hive_review.state(ordinary)
    assert simulated.get('verification')==original.get('verification')
    assert hashlib.sha256(path.read_bytes()).hexdigest()==before
    rows.append({
        'id':item['id'],'source':str(path),'source_sha256':before,'provenance':item['category'],
        'original_status':original['status'],'original_deterministic_eligibility':not item['independent_blockers'],
        'original_independent_blockers':item['independent_blockers'],
        'original_raw_model_review':item['raw_decision'],'original_host_review':item['final_review'],
        'new_review_disposition':review['disposition'],
        'counterfactual_with_original_external_restriction':actual,
        'ordinary_workshop_policy_projection':ordinary_state,
        'meaningful_change':('Verified facts preserved; unavailable review is no longer a semantic veto; external promotion remains forbidden.' if item['id']=='4574db69cea0' else
                             'Host blockers separated from raw model judgment; candidate remains blocked.' if item['independent_blockers'] else
                             'No additional model-review obstacle; external restriction and explicit authorization still apply.'),
        'promoted':False,'verification_unchanged':True,
    })
assert len(rows)==49
vetoes=[r for r in rows if (r['original_raw_model_review'] or {}).get('approve') is False]
overridden=[r for r in rows if (r['original_raw_model_review'] or {}).get('approve') is True and not r['original_deterministic_eligibility']]
assert len(vetoes)==41 and all(not r['ordinary_workshop_policy_projection']['human_review_eligible'] for r in vetoes)
assert len(overridden)==3 and all(not r['ordinary_workshop_policy_projection']['human_review_eligible'] for r in overridden)
j001=next(r for r in rows if r['id']=='4574db69cea0')
assert j001['ordinary_workshop_policy_projection']['human_review_eligible']
assert not j001['counterfactual_with_original_external_restriction']['human_review_eligible']
assert not any(r['counterfactual_with_original_external_restriction']['promotion_eligible'] for r in rows)
summary={'records':49,'completed_reviews':48,'review_unavailable':1,'independently_blocked_vetoes_still_blocked':len(vetoes),
         'independently_blocked_approvals_still_blocked':len(overridden),'model_calls':0,'apply_calls':0,'historical_records_changed':0,
         'external_policy_note':'The ordinary-Workshop projection is explicitly hypothetical; actual external diagnostic eligibility is false.'}
(HERE/'evidence/historical-replay.json').write_text(json.dumps({'summary':summary,'records':rows},indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
lines=['# Historical counterfactual replay','',
       'No historical result was changed. Presentation eligibility below means the ordinary human-approval workflow; external diagnostic restrictions are retained. The separate ordinary-policy column explicitly removes only the external restriction for comparison, never for execution.',
       '', '| Run | Original deterministic eligibility | Raw review | New review disposition | Human-review eligible, actual restrictions | Human-review eligible, ordinary-policy projection | Promotion authorized |',
       '|---|---|---|---|---|---|---|']
for r in rows:
    lines.append('| {} | {} | {} | {} | {} | {} | No |'.format(r['id'],r['original_deterministic_eligibility'],(r['original_raw_model_review'] or {}).get('approve','no decision'),r['new_review_disposition'],r['counterfactual_with_original_external_restriction']['human_review_eligible'],r['ordinary_workshop_policy_projection']['human_review_eligible']))
(HERE/'historical-replay.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
# Reconstruct only the legitimate review evidence that the host recorded. No
# hidden test source, candidate modification, or inference call is involved.
original=json.loads(Path(j001['source']).read_text())
original['errors']=[e for e in original.get('errors',[]) if e.get('role')!='reviewer']
context=hive_review.evidence(original)
(HERE/'evidence/j001-review-evidence-counterfactual.json').write_text(json.dumps(context,indent=2)+'\n',encoding='utf-8')
print(json.dumps(summary,indent=2))
print('J001 structured evidence characters:',len(json.dumps(context,ensure_ascii=False)))

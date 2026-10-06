"""Read-only historical audit and synthetic controller probes; no providers invoked."""
import asyncio
import collections
import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / 'HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/repaired-workshop'
sys.path[:0] = [str(SOURCE), str(SOURCE / 'tests')]
from workshop import hive
from test_hive_observation_loop import _source, _plan, _implementation, _review


def save(name, value):
    (HERE / 'evidence' / name).write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + '\n', encoding='utf-8')


def extracted(raw):
    try:
        result = hive._extract_json(raw)
        return result if isinstance(result, dict) else None
    except Exception:
        return None


def history():
    inv = json.loads((HERE / 'evidence/inventory.json').read_text())
    rows = []
    conflicts = []
    for group in inv['groups']:
        r = group['records'][0]
        p = r['path'].replace('\\', '/').lower()
        reviewer = r['reviewer']
        raw = reviewer.get('repair_raw') if reviewer.get('repaired') else reviewer.get('raw')
        decision = extracted(raw)
        if '/test_' in p or '/preflight-invalid-temp/' in p:
            category = 'TEST_FIXTURE'
        elif 'Single-agent host gate' in (reviewer.get('raw') or ''):
            category = 'SINGLE_AGENT_HOST_STAND_IN'
        elif 'Controlled reviewer fixture' in (reviewer.get('raw') or ''):
            category = 'CONTROLLED_REVIEWER_FIXTURE'
        elif '/dry-run-runs/' in p or '/replay-before/' in p or '/replay-after/' in p or '/expressibility-runs/' in p:
            category = 'DETERMINISTIC_PROBE_OR_REPLAY'
        elif decision and r['reviewer_calls']:
            category = 'REVIEW_WITH_PROVIDER_TELEMETRY'
        elif decision:
            category = 'LEGACY_REVIEW_WITHOUT_CALL_TELEMETRY'
        elif r['reviewer_calls']:
            category = 'REVIEW_ATTEMPT_WITHOUT_DECISION'
        else:
            category = 'NO_REVIEW_OBSERVED'
        # Stored final review may contain host vetoes. Use raw/repaired model JSON.
        prior_errors = [e for e in r['errors'] if isinstance(e, dict) and e.get('role') != 'reviewer']
        blockers = []
        if r['verification_passed'] is not True:
            blockers.append('verification_not_passed')
        if prior_errors:
            blockers.append('prior_errors')
        if not r['changed_files']:
            blockers.append('no_changed_files')
        row = dict(id=group['id'], category=category, copies=group['copies'], source=r['path'],
                   sha256=r['sha256'], verification_passed=r['verification_passed'], changed_files=r['changed_files'],
                   prior_errors=prior_errors, independent_blockers=blockers, raw_decision=decision,
                   formatting_repair=bool(reviewer.get('repaired')), final_review=r['review'],
                   reviewer_calls=r['reviewer_calls'], raw=reviewer.get('raw'), repair_raw=reviewer.get('repair_raw'))
        rows.append(row)
        for variant in group['records'][1:]:
            for key in ['reviewer', 'review', 'verification_passed', 'changed_files', 'errors']:
                if variant[key] != r[key]:
                    conflicts.append({'id':group['id'], 'field':key, 'first':r['path'], 'other':variant['path']})
    completed = [r for r in rows if r['category'] in ('REVIEW_WITH_PROVIDER_TELEMETRY','LEGACY_REVIEW_WITHOUT_CALL_TELEMETRY')]
    summary = {
        'discovered_files':sum(s['files'] for s in inv['scans']), 'hive_run_files':inv['run_files'],
        'unique_ids':len(rows), 'categories':dict(collections.Counter(r['category'] for r in rows)),
        'completed_reviews':len(completed),
        'raw_vetoes':sum(r['raw_decision'].get('approve') is False for r in completed),
        'raw_approvals':sum(r['raw_decision'].get('approve') is True for r in completed),
        'vetoes_with_other_blocker':sum(r['raw_decision'].get('approve') is False and bool(r['independent_blockers']) for r in completed),
        'vetoes_without_other_blocker':[r['id'] for r in completed if r['raw_decision'].get('approve') is False and not r['independent_blockers']],
        'approvals_despite_other_blocker':[r['id'] for r in completed if r['raw_decision'].get('approve') is True and r['independent_blockers']],
        'eligible_reviews':[r['id'] for r in completed if not r['independent_blockers']],
        'vetoes_grouped':dict(collections.Counter((r['category'] + (' / verifier failed' if r['verification_passed'] is not True else ' / verifier passed, prior/no-edit blockers')) for r in completed if r['raw_decision'].get('approve') is False)),
        'review_relevant_variant_conflicts':conflicts,
    }
    save('history-audit.json', {'method':'Deduplicate by run ID; classify fixtures separately; use repair_raw when a formatting repair occurred; never substitute host-mutated final review for model judgment.', 'summary':summary,'runs':rows})
    lines = ['# Historical review ledger', '', 'Raw approval is the model decision before controller overrides. “Other blockers” are independent of reviewer opinion. Different source versions and gates are not pooled as a reliability estimate.', '', '| Run | Provenance | Raw approval | Other blockers | Summary |', '|---|---|---|---|---|']
    for r in completed + [r for r in rows if r['category']=='REVIEW_ATTEMPT_WITHOUT_DECISION']:
        decision = r['raw_decision'] or {}
        url = r['source'].replace('\\','/')
        lines.append('| [{}](<{}>) | {} | {} | {} | {} |'.format(r['id'], url, r['category'], decision.get('approve','UNAVAILABLE'), ', '.join(r['independent_blockers']) or 'none', str(decision.get('summary','No model decision')).replace('|','/').replace('\n',' ')))
    (HERE/'historical-review-ledger.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(summary,indent=2))


def probes():
    cases = [
        ('approve', _review(), True, 'normal'),
        ('semantic_veto', json.dumps({'approve':False,'summary':'Semantic objection','issues':['Uncovered behavior'],'confidence':0.9}), True, 'normal'),
        ('unsupported_veto', json.dumps({'approve':False,'summary':'No explanation','issues':[],'confidence':0}), True, 'normal'),
        ('approve_with_issue_and_zero_confidence', json.dumps({'approve':True,'summary':'Contradictory','issues':['Major issue'],'confidence':0}), True, 'normal'),
        ('string_false', json.dumps({'approve':'false','summary':'Wrong type','issues':[],'confidence':1}), True, 'normal'),
        ('missing_approve', json.dumps({'summary':'Missing required field','issues':[],'confidence':1}), True, 'normal'),
        ('scalar_json', 'true', True, 'normal'),
        ('invalid_then_repaired', ['not json',_review()], True, 'normal'),
        ('invalid_twice', ['not json','still not json'], True, 'normal'),
        ('unavailable', RuntimeError('SYNTHETIC provider unavailable'), True, 'normal'),
        ('verification_failed', _review(), False, 'normal'),
        ('no_edit', _review(), True, 'no_edit'),
        ('worker_error', _review(), True, 'worker_error'),
    ]
    results=[]
    for name, response, verified, worker_mode in cases:
        base=HERE/'evidence/synthetic'/name
        assert not base.exists(), 'Preserve existing probe'
        root=_source(base)
        prompts=[]
        async def call(role,prompt):
            prompts.append({'role':role,'prompt':str(prompt)})
            if role=='planner':return json.dumps(_plan())
            if role=='backend':
                if worker_mode=='worker_error':raise RuntimeError('SYNTHETIC worker error')
                if worker_mode=='no_edit':return json.dumps({'status':'implemented','summary':'health summary','edits':[],'risks':[]})
                return _implementation()
            assert role=='reviewer'
            if isinstance(response,Exception):raise response
            if isinstance(response,list):return response[min(sum(p['role']=='reviewer' for p in prompts)-1,len(response)-1)]
            return response
        # Mock ONLY model responses and deterministic verifier results; execute normal
        # planner normalization, worker preflight, staging, reviewer parser and decision.
        with patch.object(hive,'targeted_verify',lambda *a:{'passed':True,'checks':[]}), patch.object(hive,'verify_tree',lambda *a:{'passed':verified,'checks':[{'name':'SYNTHETIC','passed':verified}]}):
            run=asyncio.run(hive.run_build(root,base/'runs','Implement the health summary','SYNTHETIC-NO-MODEL',call))
        (base/'prompts.json').write_text(json.dumps(prompts,indent=2),encoding='utf-8')
        results.append({'case':name,'status':run['status'],'review':run.get('review'),'errors':run.get('errors'),
                        'verification':run.get('verification'),'changed_files':run.get('changed_files'),
                        'review_calls':sum(p['role']=='reviewer' for p in prompts),'run_id':run['id']})
    save('controller-probes.json',{'synthetic':True,'provider_calls':0,'real_verifier_calls':0,'method':'Real hive.run_build with synthetic provider responses and mocked verifier decisions; private scratch sources only. No production code edits or apply calls.','results':results})
    print(json.dumps([{'case':r['case'],'status':r['status'],'review_calls':r['review_calls']} for r in results],indent=2))


if __name__=='__main__':
    history()
    probes()

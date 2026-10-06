"""Real controller/protocol/apply probes; no model, Docker or Gradle required."""
import asyncio
import copy
import json

import pytest

from workshop import hive, hive_review, chat_context
from test_hive_observation_loop import _source, _plan, _implementation, _review


def decision(approve=True, **overrides):
    return {"approve": approve, "summary": "semantic judgment", "issues": [], "confidence": 0.8, **overrides}


def execute(tmp_path, monkeypatch, review=None, *, verified=True, worker="valid", required=False):
    root = _source(tmp_path)
    prompts = []
    replies = list(review) if isinstance(review, list) else [review if review is not None else json.dumps(decision())]
    async def call(role, prompt):
        prompts.append((role, str(prompt)))
        if role == "planner": return json.dumps(_plan())
        if role == "backend":
            if worker == "error": raise RuntimeError("worker failed independently")
            if worker == "empty": return json.dumps({"status":"implemented", "summary":"health summary", "edits":[], "risks":[]})
            if worker == "unauthorized":
                payload = json.loads(_implementation());payload["edits"][0]["path"] = "tests/test_existing.py"
                return json.dumps(payload)
            return _implementation()
        assert role == "reviewer"
        reply = replies.pop(0)
        if isinstance(reply, Exception): raise reply
        return reply
    verification = {"passed": verified, "checks": [{"name":"full_gate", "passed":verified},
                                                   {"name":"source_immutability", "passed":verified}]}
    monkeypatch.setattr(hive, "targeted_verify", lambda *a: {"passed":True,"checks":[{"name":"targeted", "passed":True}]})
    monkeypatch.setattr(hive, "verify_tree", lambda *a: copy.deepcopy(verification))
    run = asyncio.run(hive.run_build(root, tmp_path/"runs", "Implement the health summary and preserve existing behavior", "synthetic", call,
                                      require_independent_review=required))
    assert run["verification"] == verification
    return root, run, prompts


@pytest.mark.parametrize("review,disposition,eligible", [
    (json.dumps(decision()), "approved", True),
    (json.dumps(decision(False,issues=["Unimplemented requirement"])), "rejected", False),
    (RuntimeError("allocation failed"), "unavailable", True),
    (TimeoutError("generation deadline"), "unavailable", True),
    (json.dumps(decision("false")), "invalid", True),
    (json.dumps(decision(1)), "invalid", True),
    (json.dumps(decision(None)), "invalid", True),
    (json.dumps({"summary":"missing", "issues":[], "confidence":0}), "invalid", True),
    ("true", "invalid", True),
    (json.dumps(decision(confidence=-0.1)), "invalid", True),
    (json.dumps(decision(confidence=1.1)), "invalid", True),
    (json.dumps(decision(confidence=True)), "invalid", True),
    (json.dumps(decision(confidence=float('nan'))), "invalid", True),
    (json.dumps(decision(confidence=10**1000)), "invalid", True),
    (json.dumps(decision(issues=[1])), "invalid", True),
    (json.dumps(decision(summary=1)), "invalid", True),
    (json.dumps(decision(issues="concern")), "invalid", True),
    (json.dumps(decision(extra="not permitted")), "invalid", True),
    (json.dumps(decision(issues=["Concern retained"],confidence=0)), "approved", True),
])
def test_independent_dimensions(tmp_path, monkeypatch, review, disposition, eligible):
    root, run, _ = execute(tmp_path, monkeypatch, review)
    assert run["verification_status"] == "passed"
    assert run["review_disposition"] == disposition
    assert run["candidate_disposition"] == "verified_review_" + disposition
    assert run["human_review_eligible"] is eligible
    assert run["promotion_authorization"] == ("not_authorized" if eligible else "blocked")
    assert run["promotion_eligible"] is False and run["applied"] is False
    assert run.get("errors", []) == []  # reviewer failures are separate
    assert run["verified_stage_sha256"]
    assert run["targeted_verifications"][0]["result"]["passed"] is True
    if disposition in ("unavailable", "invalid"):
        assert run["review"] is None and run["semantic_review"]["decision"] is None
    if disposition == "unavailable":
        assert run["semantic_review"]["failure"]["exception_message"] == str(review)
    if disposition == "approved":
        assert run["review"] == json.loads(review)
    assert "summary" not in (root/"app.py").read_text()  # no automatic apply


@pytest.mark.parametrize("review", [json.dumps(decision()), RuntimeError("allocation failed")])
def test_failed_verification_cannot_be_overridden(tmp_path, monkeypatch, review):
    _, run, _ = execute(tmp_path, monkeypatch, review, verified=False)
    assert run["verification_status"] == "failed" and not run["human_review_eligible"]
    assert run["promotion_authorization"] == "blocked"
    if isinstance(review,str): assert run["review"]["approve"] is True  # host never rewrites opinion


@pytest.mark.parametrize("worker", ["empty", "error", "unauthorized"])
def test_prior_controller_failures_remain_blockers(tmp_path, monkeypatch, worker):
    _, run, _ = execute(tmp_path, monkeypatch, worker=worker)
    assert run["review_disposition"] == "approved"
    assert not run["human_review_eligible"] and run["promotion_authorization"] == "blocked"


@pytest.mark.parametrize("repair,expected", [(json.dumps(decision()),"approved"), ("not json either","invalid"), (json.dumps(decision("false")),"invalid"), (TimeoutError("repair runtime failed"),"unavailable")])
def test_one_evidence_preserving_format_repair(tmp_path,monkeypatch,repair,expected):
    _, run, prompts = execute(tmp_path,monkeypatch,["not JSON", repair])
    reviews = [p for role,p in prompts if role=="reviewer"]
    assert len(reviews)==2 and run["review_disposition"]==expected
    evidence = json.dumps(run["review_evidence"],ensure_ascii=False)
    assert evidence in reviews[0] and evidence in reviews[1]
    assert run["request"] in evidence and "staged_manifest" in evidence
    assert "ONE JSON FORMAT REPAIR" in reviews[1]
    assert run["semantic_review"]["raw"] == "not JSON"


def test_no_contextless_repair():
    calls=[]
    async def call(*args): calls.append(args);return _review()
    result=asyncio.run(hive_review.collect({},call,hive._extract_json))
    assert result["disposition"]=="not_run" and not calls
    with pytest.raises(hive_review.ReviewEvidenceError):
        hive._json_repair_prompt("reviewer", "bad", ValueError("syntax"))


def test_malformed_review_cannot_be_repaired_after_evidence_loss():
    context=hive_review.evidence({'request':'Task','diff':'diff','verification':{'passed':True}})
    calls=[]
    async def call(*args):
        calls.append(args)
        context.clear()  # emulate a host context-loss defect, not a model instruction
        return 'malformed JSON'
    result=asyncio.run(hive_review.collect(context,call,hive._extract_json))
    assert result['disposition']=='invalid' and result['decision'] is None
    assert result['raw']=='malformed JSON' and len(calls)==1
    assert 'evidence changed' in result['validation_error']


@pytest.mark.parametrize("review", [RuntimeError("unavailable"), json.dumps(decision("false")), json.dumps(decision(False))])
def test_independent_review_obligation(tmp_path,monkeypatch,review):
    _,run,_=execute(tmp_path,monkeypatch,review,required=True)
    assert not run["human_review_eligible"]
    assert "independent_review_obligation_unmet" in run["promotion_blockers"]
    with pytest.raises(ValueError,match="independent_review_obligation"):
        hive.apply_run(tmp_path/"source",tmp_path/"runs",tmp_path/"snapshots",run["id"],human_approved=True)


def test_required_review_can_be_satisfied(tmp_path,monkeypatch):
    _,run,_=execute(tmp_path,monkeypatch,required=True)
    assert run["human_review_eligible"] and run["review_disposition"]=="approved"


def test_source_integrity_check_cannot_be_overridden(tmp_path,monkeypatch):
    _,run,_=execute(tmp_path,monkeypatch)
    run["verification"]["checks"][-1]["passed"]=False
    hive.save_run(tmp_path/"runs",run)
    assert hive_review.state(run)["verification_status"]=="failed"
    with pytest.raises(ValueError,match="verification did not pass"):
        hive.apply_run(tmp_path/"source",tmp_path/"runs",tmp_path/"snapshots",run["id"],human_approved=True)


@pytest.mark.parametrize("review", [json.dumps(decision()),RuntimeError("unavailable"),json.dumps(decision("false"))])
def test_explicit_human_apply_and_preserved_review(tmp_path,monkeypatch,review):
    root,run,_=execute(tmp_path,monkeypatch,review)
    semantic=copy.deepcopy(run["semantic_review"])
    with pytest.raises(ValueError,match="explicit human approval"):
        hive.apply_run(root,tmp_path/"runs",tmp_path/"snapshots",run["id"])
    with pytest.raises(ValueError,match="explicit human approval"):
        hive.apply_run(root,tmp_path/"runs",tmp_path/"snapshots",run["id"],human_approved=1)
    applied=hive.apply_run(root,tmp_path/"runs",tmp_path/"snapshots",run["id"],human_approved=True)
    assert applied["applied"] and applied["promotion_authorization"]=="human_approved"
    assert applied["semantic_review"]==semantic and applied["review"]==run["review"]
    assert applied["promotion_decision"]["model_review_substituted"] == (run["review_disposition"]!="approved")
    assert "summary" in (root/"app.py").read_text()


def test_semantic_rejection_has_no_human_override(tmp_path,monkeypatch):
    root,run,_=execute(tmp_path,monkeypatch,json.dumps(decision(False)))
    with pytest.raises(ValueError,match="semantic_review_rejected"):
        hive.apply_run(root,tmp_path/"runs",tmp_path/"snapshots",run["id"],human_approved=True)


@pytest.mark.parametrize("target",["source","stage","unlisted_stage"])
def test_tampered_candidate_not_overridden(tmp_path,monkeypatch,target):
    root,run,_=execute(tmp_path,monkeypatch,RuntimeError("unavailable"))
    path = root/"app.py" if target=="source" else tmp_path/"runs"/run["id"]/"stage"/("workshop/core.py" if target=="unlisted_stage" else "app.py")
    path.write_text("tampered\n")
    with pytest.raises(hive.StaleBaseError):
        hive.apply_run(root,tmp_path/"runs",tmp_path/"snapshots",run["id"],human_approved=True)
    assert not (tmp_path/"snapshots"/run["id"]).exists()


def test_apply_rechecks_ownership(tmp_path,monkeypatch):
    root,run,_=execute(tmp_path,monkeypatch)
    run["plan"]["worker_files"]["tests"]=["app.py"]
    hive.save_run(tmp_path/"runs",run)
    with pytest.raises(ValueError,match="ownership"):
        hive.apply_run(root,tmp_path/"runs",tmp_path/"snapshots",run["id"],human_approved=True)


def test_post_apply_failure_rolls_back(tmp_path,monkeypatch):
    root,run,_=execute(tmp_path,monkeypatch,RuntimeError("unavailable"))
    original=(root/"app.py").read_bytes()
    monkeypatch.setattr(hive,"verify_tree",lambda *a:{"passed":False,"checks":[]})
    with pytest.raises(RuntimeError,match="post-apply verification failed"):
        hive.apply_run(root,tmp_path/"runs",tmp_path/"snapshots",run["id"],human_approved=True)
    assert (root/"app.py").read_bytes()==original
    saved=hive.load_run(tmp_path/"runs",run["id"])
    assert saved["promotion_authorization"]=="blocked" and not saved["applied"]
    assert saved["verification"]==run["verification"]  # pre-apply fact is retained
    assert saved["post_apply_verification"]["passed"] is False


def test_external_candidate_remains_nonpromotable(tmp_path,monkeypatch):
    root,run,_=execute(tmp_path,monkeypatch,RuntimeError("unavailable"))
    run["metadata"]["external_root"]={"external_root_mode":"candidate_only"}
    hive.hive_review.refresh(run);hive.save_run(tmp_path/"runs",run)
    assert run["candidate_disposition"]=="verified_review_unavailable"
    assert not run["human_review_eligible"] and "external_candidate_only" in run["promotion_blockers"]
    with pytest.raises(ValueError,match="candidate/evaluation only"):
        hive.apply_run(root,tmp_path/"runs",tmp_path/"snapshots",run["id"],human_approved=True)


def test_evidence_prioritizes_complete_host_facts(tmp_path,monkeypatch):
    _,run,_=execute(tmp_path,monkeypatch)
    run["diff"]="D"*70001
    run["verification"]={"passed":True,"checks":[
        {"name":"frozen_junit_acceptance","passed":True,"detail":{"stdout_tail":"LOG"*20000,"tests":[{"tests":3,"failures":0,"errors":0,"skipped":0}]}},
        {"name":"full_gradle_check","passed":True,"detail":{"tests":[{"tests":154,"failures":0,"errors":0,"skipped":0}]}},
        {"name":"source_immutability","passed":True}]}
    evidence=hive_review.evidence(run)
    encoded=json.dumps(evidence)
    assert json.loads(encoded)==evidence and len(encoded)<=hive_review.MAX_EVIDENCE_CHARS
    assert evidence["diff"]["omitted_characters"]==54001 and not evidence["diff"]["complete"]
    checks=evidence["final_verification"]["checks"]
    assert checks[-1]=={"name":"source_immutability","passed":True}
    assert checks[0]["test_counts"]["tests"]==3 and checks[1]["test_counts"]["tests"]==154
    assert checks[0]["omitted_logs_characters"]["stdout_tail"]==60000
    assert evidence["request"]==run["request"] and evidence["artifact_identity"]["staged_manifest"]==run["staged_manifest"]
    run["request"]="A"*40000
    with pytest.raises(hive_review.ReviewEvidenceError,match="bounded input budget"):
        hive_review.evidence(run)


def test_not_run_not_required_and_invalid_policy_are_not_bypasses(tmp_path,monkeypatch):
    _,run,_=execute(tmp_path,monkeypatch)
    for disposition in ("not_run","not_required"):
        run["semantic_review"]={"disposition":disposition,"decision":None}
        assert not hive_review.state(run)["human_review_eligible"]
    run["review_policy"]["independent_review_required"]="false"
    assert "invalid_review_policy" in hive_review.state(run)["promotion_blockers"]


def test_chat_summary_preserves_unavailability(tmp_path,monkeypatch):
    _,run,_=execute(tmp_path,monkeypatch,RuntimeError("allocation failed"))
    summary=chat_context._run_summary(run)
    assert summary["verification_passed"] is True and summary["review_approved"] is None
    assert summary["review_disposition"]=="unavailable"
    assert "unavailable" in chat_context._latest_run_digest([summary])


def test_apply_endpoint_requires_and_transmits_exact_boolean(monkeypatch):
    import app
    from fastapi.testclient import TestClient
    called=[]
    def apply(*args,**kwargs):
        called.append(kwargs)
        return {"id":"a"*12,"changed_files":["app.py"],"applied":True}
    monkeypatch.setattr(app,"require_mode_for_code",lambda:None)
    monkeypatch.setattr(app.hive,"apply_run",apply)
    monkeypatch.setattr(app.db,"add_ledger",lambda *a,**k:None)
    client=TestClient(app.app)
    for value in ("true",1,None):
        assert client.post('/api/hive/apply',json={'run_id':'a'*12,'approved':value}).status_code==422
    assert client.post('/api/hive/apply',json={'run_id':'a'*12}).status_code==409
    assert not called
    assert client.post('/api/hive/apply',json={'run_id':'a'*12,'approved':True}).status_code==200
    assert called==[{'human_approved':True}]


def test_build_api_propagates_explicit_review_obligation(monkeypatch):
    import app,time
    from fastapi.testclient import TestClient
    seen=[]
    async def build(*args,**kwargs):
        seen.append(kwargs['require_independent_review'])
        return {'id':'a'*12,'status':'verified','changed_files':['app.py'],
                'verification':{'passed':True},'review':None,'review_disposition':'unavailable',
                'candidate_disposition':'verified_review_unavailable','human_review_eligible':False,
                'promotion_authorization':'blocked','metadata':{}}
    monkeypatch.setattr(app.hive,'run_build',build)
    monkeypatch.setattr(app.hive,'save_run',lambda *a:None)
    monkeypatch.setattr(app,'require_mode_for_code',lambda:None)
    monkeypatch.setattr(app.db,'add_ledger',lambda *a,**k:None)
    with TestClient(app.app) as client:
        assert client.post('/api/hive/build',json={'request':'Task','require_independent_review':'true'}).status_code==422
        response=client.post('/api/hive/build',json={'request':'Task requires independent semantic review','require_independent_review':True})
        for _ in range(100):
            job=client.get('/api/jobs/'+response.json()['job_id']).json()
            if job['state'] in ('completed','failed'):break
            time.sleep(.01)
        assert job['state']=='completed' and seen==[True]
        assert job['result']['promotion_authorization']=='blocked'


def test_ui_renders_review_availability_separately_and_controls_apply():
    import shutil,subprocess
    from pathlib import Path
    node=shutil.which('node')
    if not node:pytest.skip('node unavailable')
    html=(Path(__file__).resolve().parents[1]/'static/index.html').read_text(encoding='utf-8')
    renderer=html[html.index('function renderHiveRun('):html.index('async function runHiveBuild()')]
    script="""const assert=require('assert');
const nodes={}; const $=id=>nodes[id]??=( {textContent:'',style:{},replaceChildren(){},appendChild(){}} );
const document={createElement:()=>({style:{}})}; let currentHiveRun;
"""+renderer+"""
const run={id:'example',status:'ready',candidate_disposition:'verified_review_unavailable',verification_status:'passed',review_disposition:'unavailable',human_review_eligible:true,promotion_authorization:'not_authorized',verification:{passed:true,checks:[]},semantic_review:{disposition:'unavailable',decision:null}};
renderHiveRun(run);
assert.equal($('hiveapply').disabled,false);
assert($('hivestatus').textContent.includes('SEMANTIC REVIEW UNAVAILABLE'));
assert($('hivestatus').textContent.includes('AWAITING HUMAN DECISION'));
renderHiveRun({...run,human_review_eligible:false,promotion_authorization:'blocked'});
assert.equal($('hiveapply').disabled,true);
renderHiveRun({...run,verification_status:'failed',human_review_eligible:false});
assert.equal($('hiveapply').disabled,true);
"""
    result=subprocess.run([node,'-e',script],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert 'model has not approved this candidate' in html
    assert 'require_independent_review' in html

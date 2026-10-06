import asyncio, json
from pathlib import Path
from workshop import hive

def plan_response(ui_goal="make change"):
    return json.dumps({"summary":"worker failure fixture", "ui_goal":ui_goal,
        "backend_goal":"no change needed", "tests_goal":"no change needed",
        "worker_files":{"ui":[] if ui_goal=="no change needed" else ["static/index.html"],"backend":[],"tests":[]},
        "acceptance":["The scoped UI task succeeds"],
        "worker_acceptance":{"ui":[] if ui_goal=="no change needed" else ["The scoped UI task succeeds"],"backend":[],"tests":[]}})

def run_build(tmp_path, responses):
    root=tmp_path/"source"; root.mkdir(); (root/"app.py").write_text("x=1\n"); (root/"static").mkdir(); (root/"static/index.html").write_text("x"); (root/"tests").mkdir(); (root/"tests/test_x.py").write_text("")
    async def call(role, prompt):
        value=responses[role]
        return value() if callable(value) else value
    return asyncio.run(hive.run_build(root,tmp_path/"runs","request","local",call))

def test_invalid_worker_json_is_structured(tmp_path):
    plan=plan_response()
    run=run_build(tmp_path,{"planner":plan,"ui":"not json","reviewer":'{"approve":false}'})
    failure=run["agents"]["ui"]["failure"]
    assert failure["role"]=="ui" and failure["stage"]=="json_parse"
    assert failure["exception_type"] and failure["raw_excerpt"]=="not json"
    assert any(e["stage"]=="json_parse" for e in run["errors"])

def test_invalid_worker_json_gets_one_same_role_repair(tmp_path):
    plan=plan_response()
    payload=json.dumps({"summary":"repaired edit","edits":[],"risks":[]})
    calls=[]
    async def call(role,prompt):
        calls.append(role)
        if role=="planner": return plan
        if role=="ui": return "not json" if calls.count("ui")==1 else payload
        return '{"approve":false}'
    root=tmp_path/"source"; root.mkdir(); (root/"app.py").write_text("x=1\n")
    run=asyncio.run(hive.run_build(root,tmp_path/"runs","request","local",call))
    assert calls==["planner","ui","ui","reviewer"]
    assert run["agents"]["ui"]["repaired"] is True
    assert run["agents"]["ui"]["parsed"]["summary"]=="repaired edit"

def test_no_change_worker_is_skipped(tmp_path):
    plan=plan_response("no change needed")
    calls=[]
    async def call(role,prompt): calls.append(role); return plan if role=="planner" else '{"approve":false}'
    root=tmp_path/"source"; root.mkdir(); (root/"app.py").write_text("x=1\n")
    run=asyncio.run(hive.run_build(root,tmp_path/"runs","request","local",call))
    assert calls==["planner","reviewer"]
    assert run["agents"]["ui"]["status"]=="skipped"

def test_edit_apply_failure_includes_payload(tmp_path):
    plan=plan_response()
    payload=json.dumps({"summary":"bad edit","edits":[{"path":"static/index.html","operation":"replace","find":"missing","replace":"x"}]})
    run=run_build(tmp_path,{"planner":plan,"ui":payload,"reviewer":'{"approve":false}'})
    failure=run["agents"]["ui"]["failure"]
    assert failure["stage"]=="edit_validation" and failure["parsed_payload"]["summary"]=="bad edit"
    assert failure["edit_repair_repeated"] is True
    diagnostic = run["edit_repairs"][0]["diagnostic"]
    assert diagnostic["structural"]["code"] == "anchor_resolution"
    assert "find text" in diagnostic["exception_message"]

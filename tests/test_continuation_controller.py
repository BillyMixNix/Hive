import json
from hive.continuation_controller import ChildTask, ContinuationState, Disposition, apply_event, consume_events, decide, pilot_gate

def state(children=None):
    return ContinuationState(parent_goal="Develop Endless Fusion",completion_cues=["playable milestone validated"],children=children or [])

def test_child_success_does_not_complete_parent():
    s=state([ChildTask("harness","Build web harness")]);apply_event(s,{"kind":"child_completed","child_id":"harness","evidence":["PASS"]})
    assert decide(s)==(Disposition.CONTINUE,"derive_next_child")

def test_ready_child_continues_without_pilot():assert decide(state([ChildTask("resume-game","Resume Endless Fusion")]))==(Disposition.CONTINUE,"resume-game")

def test_external_dependency_suspends_not_escalates():
    s=state();apply_event(s,{"kind":"dependency_started","dependency":{"kind":"github_actions","run_id":123}});assert decide(s)[0]==Disposition.SUSPEND
    apply_event(s,{"kind":"dependency_resolved","result":"success","evidence":{"run_id":123}});assert decide(s)[0]==Disposition.CONTINUE

def test_nonpilot_blocker_creates_recovery_work():
    c=ChildTask("observe","Observe candidate",status="blocked",blocker={"kind":"browser_missing","requires_pilot":False})
    assert decide(state([c]))==(Disposition.CONTINUE,"resolve:observe:browser_missing")

def test_only_judgment_blocker_escalates():
    c=ChildTask("direction","Choose multiplayer direction",status="blocked",blocker={"kind":"product_direction","requires_pilot":True,"question":"Should the game become multiplayer?"})
    assert decide(state([c]))==(Disposition.PILOT,"Should the game become multiplayer?")

def test_parent_completion_is_explicit():
    s=state();apply_event(s,{"kind":"parent_completed"});assert decide(s)[0]==Disposition.COMPLETE

def test_watcher_queue_wakes_controller(tmp_path):
    s=state([ChildTask("resume-game","Resume Endless Fusion")]);s.waiting_on={"kind":"github_actions","run_id":123}
    q=tmp_path/"events.jsonl";q.write_text(json.dumps({"kind":"dependency_resolved","result":"success","evidence":{"run_id":123}})+"\n")
    assert consume_events(s,q)==1;assert s.waiting_on is None;assert decide(s)==(Disposition.CONTINUE,"resume-game");assert q.read_text()==""

def test_pilot_gate_hides_internal_continuation():
    visible,_=pilot_gate(state([ChildTask("work","Keep working")]))
    assert visible is False

def test_pilot_gate_hides_waiting():
    s=state();s.waiting_on={"kind":"github_actions","run_id":1};assert pilot_gate(s)[0] is False

def test_pilot_gate_allows_real_judgment():
    s=state();s.pilot_question="Choose direction";assert pilot_gate(s)==(True,"Choose direction")

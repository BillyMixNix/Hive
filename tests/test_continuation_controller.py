from hive.continuation_controller import ChildTask, ContinuationState, Disposition, apply_event, decide


def state(children=None):
    return ContinuationState(
        parent_goal="Develop Endless Fusion",
        completion_cues=["playable milestone validated"],
        children=children or [],
    )


def test_child_success_does_not_complete_parent():
    s = state([ChildTask("harness", "Build web harness")])
    apply_event(s, {"kind": "child_completed", "child_id": "harness", "evidence": ["PASS"]})
    disposition, reason = decide(s)
    assert disposition == Disposition.CONTINUE
    assert reason == "derive_next_child"


def test_ready_child_continues_without_pilot():
    s = state([ChildTask("resume-game", "Resume Endless Fusion")])
    assert decide(s) == (Disposition.CONTINUE, "resume-game")


def test_external_dependency_suspends_not_escalates():
    s = state()
    apply_event(s, {"kind": "dependency_started", "dependency": {"kind": "github_actions", "run_id": 123}})
    disposition, _ = decide(s)
    assert disposition == Disposition.SUSPEND
    apply_event(s, {"kind": "dependency_resolved"})
    assert decide(s)[0] == Disposition.CONTINUE


def test_nonpilot_blocker_creates_recovery_work():
    c = ChildTask("observe", "Observe candidate", status="blocked", blocker={"kind": "browser_missing", "requires_pilot": False})
    disposition, reason = decide(state([c]))
    assert disposition == Disposition.CONTINUE
    assert reason == "resolve:observe:browser_missing"


def test_only_judgment_blocker_escalates():
    c = ChildTask("direction", "Choose multiplayer direction", status="blocked", blocker={"kind": "product_direction", "requires_pilot": True, "question": "Should the game become multiplayer?"})
    assert decide(state([c])) == (Disposition.PILOT, "Should the game become multiplayer?")


def test_parent_completion_is_explicit():
    s = state()
    apply_event(s, {"kind": "parent_completed"})
    assert decide(s)[0] == Disposition.COMPLETE

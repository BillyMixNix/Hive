from workshop import hive

def test_insert_after_anchor_inserts_once(tmp_path):
    (tmp_path/"app.py").write_text("one\nANCHOR\ntwo\n",encoding="utf-8")
    changed=hive.apply_agent_edits(tmp_path,"backend",{"edits":[{"path":"app.py","operation":"insert_after_anchor","anchor":"ANCHOR","insert":"\nINSERTED"}]})
    assert changed==["app.py"]
    assert (tmp_path/"app.py").read_text(encoding="utf-8")=="one\nANCHOR\nINSERTED\ntwo\n"

def test_insert_after_anchor_requires_unique_anchor(tmp_path):
    (tmp_path/"app.py").write_text("ANCHOR\nANCHOR\n",encoding="utf-8")
    try:
        hive.apply_agent_edits(tmp_path,"backend",{"edits":[{"path":"app.py","operation":"insert_after_anchor","anchor":"ANCHOR","insert":"x"}]})
    except ValueError as exc:
        assert "anchor must occur exactly once" in str(exc)
    else:
        raise AssertionError("ambiguous anchor should be rejected")

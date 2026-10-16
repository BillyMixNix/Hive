from __future__ import annotations

from pathlib import Path

import scripts.grow0 as grow0_cli


def test_prior_hive_suite_runs_on_candidate_overlay(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    candidate = tmp_path / "candidate"
    (repo / "grow" / "workshop").mkdir(parents=True)
    (repo / "tests").mkdir(parents=True)
    (repo / "scripts").mkdir(parents=True)
    (repo / "grow" / "workshop" / "repair_packet.py").write_text("ancestor", encoding="utf-8")
    (candidate / "grow" / "workshop").mkdir(parents=True)
    (candidate / "grow" / "workshop" / "repair_packet.py").write_text("descendant", encoding="utf-8")

    seen = []

    def fake_run(command, cwd):
        seen.append({
            "command": command,
            "workshop": (cwd / "grow" / "workshop" / "repair_packet.py").read_text(encoding="utf-8"),
        })
        return {"command": command, "passed": True, "returncode": 0, "stdout_tail": "", "stderr_tail": ""}

    monkeypatch.setattr(grow0_cli, "_run", fake_run)
    result = grow0_cli.run_prior_hive_suite_on_candidate(
        repo, candidate, ("grow/workshop/repair_packet.py",)
    )

    assert result["passed"] is True
    assert len(seen) == 2
    assert all(item["workshop"] == "descendant" for item in seen)
    assert any("--ignore-glob=tests/test_grow0*.py" in item["command"] for item in seen)
    assert any("scripts.ci_gate" in item["command"] for item in seen)

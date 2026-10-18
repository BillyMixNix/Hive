from pathlib import Path

from HiveStateManager import HiveStateManager
from coder import CoderAgent
from planner import PlannerAgent
from repo_map import RepoMap


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _state(tmp_path):
    _write(tmp_path / "hive_compressor" / "keygen.py", "def main():\n    return 'key'\n")
    _write(tmp_path / "hive_compressor" / "server.py", "class Handler:\n    pass\n")
    _write(tmp_path / "play.py", "class TerminalPlayer:\n    def handle(self):\n        return None\n")
    _write(tmp_path / "builder.py", "def build_pilot_context():\n    return []\n")
    _write(
        tmp_path / "tests" / "test_pilot_intent_loop.py",
        "def test_merge_pilot_context_keeps_recent_history():\n    pass\n",
    )

    state = HiveStateManager(
        snapshot_path=tmp_path / "state.json",
        repo_root=tmp_path,
    )
    state.set_repo_map(RepoMap(root=tmp_path).build())
    return state


def test_repo_map_preserves_nested_relative_paths(tmp_path):
    state = _state(tmp_path)
    known = set(state.get_known_files())

    assert "hive_compressor/keygen.py" in known
    assert "hive_compressor/server.py" in known
    assert "tests/test_pilot_intent_loop.py" in known
    assert "keygen.py" not in known
    assert state.get_symbols_for_file("hive_compressor/keygen.py") == ["main"]


def test_planner_does_not_redirect_explicit_file_to_global_symbol(tmp_path):
    state = _state(tmp_path)
    planner = PlannerAgent(state_manager=state)
    task = {
        "id": 1,
        "note": (
            "In hive_compressor/keygen.py, make the API key prefix configurable "
            "while preserving the default."
        ),
        "metadata": {
            "target_file": "hive_compressor/keygen.py",
            "target_symbol": None,
            "work_mode": "repair",
            "anchor": {
                "target_file": "hive_compressor/keygen.py",
                "target_symbol": None,
                "scope": "single_file",
                "anchor_level": "file",
                "anchor_source": "user_input",
            },
        },
    }
    plan = {
        "goal": "Configure the key prefix and keep handle behavior unchanged.",
        "next_action": "Update handle if needed.",
        "task_type": "bugfix",
        "work_mode": "repair",
    }

    anchor = planner._build_anchor_from_plan(task, plan)

    assert anchor["target_file"] == "hive_compressor/keygen.py"
    assert anchor["target_symbol"] is None


def test_file_parent_anchor_clears_hallucinated_child_symbol(tmp_path):
    state = _state(tmp_path)
    planner = PlannerAgent(state_manager=state)
    child = {
        "task_id": "task-1-1",
        "title": "Update keygen",
        "description": "Update keygen",
        "target_file": "play.py",
        "target_symbol": "handle",
        "metadata": {
            "target_file": "play.py",
            "target_symbol": "handle",
            "target_symbol_id": "play.py::TerminalPlayer.handle",
            "lineno": 2,
            "end_lineno": 3,
            "anchor": {
                "target_file": "play.py",
                "target_symbol": "handle",
                "anchor_level": "symbol",
                "anchor_source": "planner_normalized",
                "target_symbol_id": "play.py::TerminalPlayer.handle",
                "lineno": 2,
                "end_lineno": 3,
            },
        },
    }

    planner._apply_anchor_to_child_tasks(
        [child],
        {
            "target_file": "hive_compressor/keygen.py",
            "target_symbol": None,
            "scope": "single_file",
            "anchor_level": "file",
            "anchor_source": "user_input",
        },
    )

    assert child["target_file"] == "hive_compressor/keygen.py"
    assert child["target_symbol"] is None
    assert child["metadata"]["anchor"]["target_symbol"] is None
    assert "target_symbol_id" not in child
    assert "target_symbol_id" not in child["metadata"]


def test_coder_accepts_canonical_file_level_modify_anchor():
    coder = CoderAgent()
    task = {
        "work_mode": "modify",
        "metadata": {
            "anchor": {
                "target_file": "hive_compressor/server.py",
                "target_symbol": None,
                "anchor_level": "file",
                "anchor_source": "user_input",
            }
        },
    }

    assert coder._allows_file_level_work(task, {}) is True

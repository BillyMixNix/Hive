import json
import subprocess

import pytest

from workshop import hive_verifier


class Result:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def source_tree(tmp_path):
    root = tmp_path / "source"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_ok.py").write_text("def test_ok(): assert True\n", encoding="utf-8")
    (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "requirements.txt").write_text("pytest>=8\n", encoding="utf-8")
    return root


def test_missing_docker_fails_closed_without_host_pytest(tmp_path, monkeypatch):
    root = source_tree(tmp_path)
    calls = []
    monkeypatch.setattr(hive_verifier.shutil, "which", lambda name: None)
    monkeypatch.setattr(hive_verifier.subprocess, "run", lambda *a, **k: calls.append(a) or Result())

    result = hive_verifier.targeted_verify_isolated(root, ["tests/test_ok.py"])

    assert result["passed"] is False
    assert result["isolation"]["available"] is False
    assert calls == []


def test_container_command_enforces_isolation_contract(tmp_path, monkeypatch):
    root = source_tree(tmp_path)
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[1:3] == ["image", "inspect"]:
            return Result(stdout="sha256:image-id\n")
        return Result(stdout=json.dumps({"passed": True, "checks": [{"name": "pytest", "passed": True, "detail": "ok"}]}))

    monkeypatch.setattr(hive_verifier.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(hive_verifier.subprocess, "run", fake_run)
    result = hive_verifier.verify_tree_isolated(root)

    command = commands[1]
    assert result["passed"] is True
    assert ["--network", "none"] == command[command.index("--network"):command.index("--network") + 2]
    assert "--read-only" in command
    assert ["--cap-drop", "ALL"] == command[command.index("--cap-drop"):command.index("--cap-drop") + 2]
    assert ["--security-opt", "no-new-privileges"] == command[command.index("--security-opt"):command.index("--security-opt") + 2]
    assert ["--pids-limit", "128"] == command[command.index("--pids-limit"):command.index("--pids-limit") + 2]
    mount = command[command.index("--mount") + 1]
    assert "target=/source,readonly" in mount
    assert "OPENAI_API_KEY" not in " ".join(command)
    assert result["isolation"]["image_id"] == "sha256:image-id"


def test_timeout_force_removes_exact_container(tmp_path, monkeypatch):
    root = source_tree(tmp_path)
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[1:3] == ["image", "inspect"]:
            return Result(stdout="sha256:image-id\n")
        if command[1] == "run":
            raise subprocess.TimeoutExpired(command, 1)
        return Result()

    monkeypatch.setattr(hive_verifier.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(hive_verifier.subprocess, "run", fake_run)
    result = hive_verifier.verify_tree_isolated(root)

    run_command = commands[1]
    name = run_command[run_command.index("--name") + 1]
    assert commands[-2] == ["/usr/bin/docker", "rm", "-f", name]
    assert commands[-1] == ["/usr/bin/docker", "inspect", "--format", "{{json .State}}", name]
    assert result["passed"] is False


def test_targeted_paths_cannot_escape(tmp_path, monkeypatch):
    root = source_tree(tmp_path)
    monkeypatch.setattr(hive_verifier.shutil, "which", lambda name: "/usr/bin/docker")
    calls = []
    monkeypatch.setattr(hive_verifier.subprocess, "run", lambda *a, **k: calls.append(a) or Result())

    for path in ("../test_bad.py", "/tmp/test_bad.py", "C:/test_bad.py", "app.py"):
        result = hive_verifier.targeted_verify_isolated(root, [path])
        assert result["passed"] is False
    assert calls == []


def test_sanitized_copy_rejects_symlinks(tmp_path, monkeypatch):
    root = source_tree(tmp_path)
    secret = tmp_path / "secret.txt"
    secret.write_text("do-not-copy", encoding="utf-8")
    try:
        (root / "tests" / "leak.py").symlink_to(secret)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation is unavailable on this platform: {exc}")
    monkeypatch.setattr(hive_verifier.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(hive_verifier.subprocess, "run", lambda command, **kwargs: Result(stdout="sha256:image-id\n"))

    result = hive_verifier.verify_tree_isolated(root)

    assert result["passed"] is False
    assert "symlink" in result["checks"][0]["detail"].lower()
    assert "do-not-copy" not in json.dumps(result)

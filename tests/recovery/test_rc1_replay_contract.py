"""Contract rejection probes; no model or verifier invocation."""

import asyncio
import importlib.util
import json
import os
from types import SimpleNamespace
from pathlib import Path

import pytest

from hive_canonical.replay import run_host_bound_j001
from hive_canonical import replay
from hive_canonical.legacy.workshop import hive_verifier


def _contract_module():
    source = Path(__file__).resolve().parents[2] / "recovery/rc1-replay/verify_replay.py"
    spec = importlib.util.spec_from_file_location("test_rc1c_contract", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_wrong_commit_fails_before_environment_or_model(tmp_path):
    module = _contract_module()
    with pytest.raises(ValueError, match="exact commit"):
        module.verify(tmp_path, expected_commit="0" * 40)


def test_replay_entrypoint_rejects_wrong_commit_without_model_call(tmp_path):
    calls = []
    async def model(role, prompt):
        calls.append((role, prompt))
        raise AssertionError("model must not be called")
    with pytest.raises(ValueError, match="exact commit"):
        asyncio.run(run_host_bound_j001(
            expected_commit="0" * 40, environment_root=tmp_path,
            runs_root=tmp_path / "runs", local_model="no-model", agent_call=model))
    assert calls == []


def test_replay_launch_uses_immutable_image_id_and_restores_process_state(monkeypatch, tmp_path):
    image_id = "sha256:" + "a" * 64
    freeze = tmp_path / "FREEZE.json"
    freeze.write_text(json.dumps({"tasks": [{"id": "J001", "request": "synthetic",
                                           "test_filename": "Hidden.java", "test_path": "src/test/java/Hidden.java",
                                           "test_class": "Hidden", "test_cases": 1}],
                                  "nfrt": {"sha256": "b" * 64}}), encoding="utf-8")
    (tmp_path / "Hidden.java").write_text("class Hidden {}", encoding="utf-8")
    (tmp_path / "baseline").mkdir()
    (tmp_path / "runs").mkdir()
    fake = SimpleNamespace(
        verify=lambda *_args, **_kwargs: {"scope": ["src/main/java/Widget.java"],
            "approved_runs_root": str(tmp_path / "runs"),
            "environment": {"cache_root": str(tmp_path / "cache"),
                            "seed_manifest": str(tmp_path / "seed.json"), "image_id": image_id}},
        FREEZE=freeze, HIDDEN=tmp_path, BASELINE=tmp_path / "baseline")
    loader = SimpleNamespace(exec_module=lambda module: None)
    monkeypatch.setattr(replay.importlib.util, "spec_from_file_location", lambda *_: SimpleNamespace(loader=loader))
    monkeypatch.setattr(replay.importlib.util, "module_from_spec", lambda *_: fake)
    before_image = hive_verifier.DEFAULT_IMAGE
    before_env = {key: os.environ.get(key) for key in
                  ("GRADLE_USER_HOME", "HIVE_NFRT_SEED_MANIFEST", "HIVE_NFRT_SEED_SHA256", "NIX_HIVE_VERIFIER_IMAGE")}
    async def fake_candidate(spec, agent_call):
        assert hive_verifier.DEFAULT_IMAGE == image_id
        assert os.environ["NIX_HIVE_VERIFIER_IMAGE"] == image_id
        assert os.environ["HIVE_NFRT_SEED_SHA256"] == "b" * 64
        return "model-free sentinel result"
    monkeypatch.setattr(replay, "produce_candidate", fake_candidate)
    assert asyncio.run(run_host_bound_j001(expected_commit="c" * 40, environment_root=tmp_path,
                                           runs_root=tmp_path / "runs", local_model="scripted",
                                           agent_call=None)) == "model-free sentinel result"
    assert hive_verifier.DEFAULT_IMAGE == before_image
    assert {key: os.environ.get(key) for key in before_env} == before_env
    assert (tmp_path / "runs/.rc1c-host-bound-replay-claim.json").is_file()
    with pytest.raises(FileExistsError):
        asyncio.run(run_host_bound_j001(expected_commit="c" * 40, environment_root=tmp_path,
                                        runs_root=tmp_path / "runs", local_model="scripted",
                                        agent_call=None))


def test_extra_unsealed_gradle_init_file_rejected(tmp_path):
    module = _contract_module()
    cache = tmp_path / "hive_runs/approved-gradle-caches/run1"
    sibling = tmp_path / "hive_runs/run1"
    selected = cache / "caches/modules-2/example.jar"
    selected.parent.mkdir(parents=True)
    selected.write_bytes(b"approved")
    meta = cache / ".hive-priming-provenance/run1"
    meta.mkdir(parents=True)
    names = ("artifacts.manifest.json", "provenance.json", "external-build-inputs.manifest.json",
             "external-build-inputs.provenance.json")
    for name in names:
        (meta / name).write_text("{}", encoding="utf-8")
    sibling.mkdir(parents=True)
    for name in names:
        if name.startswith("external-build-inputs."):
            (sibling / name).write_text("{}", encoding="utf-8")
    (tmp_path / "approved-nfrt-seed-v2.json").write_text("{}", encoding="utf-8")
    fake = SimpleNamespace(RUN_ID="run1", PROVENANCE=names,
                           paths=lambda root: (cache, sibling),
                           _source_manifest=lambda *_: (b"", [{"path": "caches/modules-2/example.jar"}]))
    assert module.verify_exact_relocation_layout(tmp_path, fake, {}) == 8
    (cache / "init.d").mkdir()
    (cache / "init.d/forgery.gradle").write_text("// unsealed", encoding="utf-8")
    with pytest.raises(ValueError, match="unexpected or missing"):
        module.verify_exact_relocation_layout(tmp_path, fake, {})


def test_host_python_runtime_mismatch_fails_closed(monkeypatch):
    source = Path(__file__).resolve().parents[2] / "recovery/rc1-replay/python_runtime.py"
    spec = importlib.util.spec_from_file_location("test_rc1c_python", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "build", lambda: {"python_version": "tampered"})
    with pytest.raises(ValueError, match="host Python runtime differs"):
        module.verify()


def test_unattested_python_import_path_fails_closed(monkeypatch, tmp_path):
    source = Path(__file__).resolve().parents[2] / "recovery/rc1-replay/python_runtime.py"
    spec = importlib.util.spec_from_file_location("test_rc1c_python_path", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.sys, "path", [*module.sys.path, str(tmp_path)])
    with pytest.raises(ValueError, match="host Python runtime differs"):
        module.verify()

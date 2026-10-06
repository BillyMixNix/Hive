import time
from pathlib import Path

import pytest
from workshop.runtime import JobManager, State, parse_json, retrieve

def test_background_job_progress_and_cancel():
    jobs=JobManager()
    def worker(job):
        job.update(State.PLANNING,25,"Planning")
        while not job.cancel_event.wait(.01): pass
    job=jobs.start(worker); time.sleep(.03)
    assert jobs.cancel(job.id); assert job.state is State.CANCELLED

def test_cancelled_job_is_not_overwritten_by_provider_abort_error():
    jobs=JobManager()
    def worker(job):
        job.update(State.PLANNING,10,"Planning")
        job.cancel_event.wait(1)
        raise RuntimeError("provider stream closed after cancellation")
    job=jobs.start(worker); time.sleep(.03)
    assert jobs.cancel(job.id)
    assert job.done.wait(1)
    assert job.state is State.CANCELLED
    assert job.error is None

def test_malformed_json_repair():
    value=parse_json("bad output",required=("outcome",),repair=lambda _: '{"outcome":"completed"}')
    assert value["outcome"]=="completed"

def test_context_is_bounded(tmp_path):
    (tmp_path/"settings.py").write_text("settings label\n"*100,encoding="utf-8")
    hits=retrieve(tmp_path,"settings label",max_chars=20)
    assert hits and len(hits[0]["content"])<=20

def test_retrieve_allows_source_beneath_external_hive_runs_ancestor(tmp_path):
    root=tmp_path/"hive_runs"/"run-1"/"basetemp"/"test_context"
    root.mkdir(parents=True)
    (root/"settings.py").write_text("settings label\n",encoding="utf-8")

    hits=retrieve(root,"settings label")

    assert [item["path"] for item in hits]==["settings.py"]

def test_retrieve_excludes_hive_runs_inside_logical_root(tmp_path):
    (tmp_path/"safe.py").write_text("settings label safe\n",encoding="utf-8")
    (tmp_path/"hive_runs").mkdir()
    (tmp_path/"hive_runs"/"secret.py").write_text("settings label secret\n",encoding="utf-8")

    hits=retrieve(tmp_path,"settings label")

    assert [item["path"] for item in hits]==["safe.py"]

def test_retrieve_blocks_symlink_alias_outside_root(tmp_path):
    root=tmp_path/"source"
    root.mkdir()
    outside=tmp_path/"outside.py"
    outside.write_text("settings label outside\n",encoding="utf-8")
    alias=root/"alias.py"
    try:
        alias.symlink_to(outside)
    except (OSError,NotImplementedError):
        pytest.skip("symlink creation is unavailable on this host")

    assert retrieve(root,"settings label")==[]

def test_terminal_job_state_ignores_late_stale_updates():
    jobs=JobManager()
    job=jobs.start(lambda current: current.update(State.FAILED,70,"verification failed"))
    assert job.done.wait(1)

    assert job.state is State.FAILED
    assert job.update(State.REVIEW,90,"late reviewer callback") is False
    assert job.state is State.FAILED
    assert job.message=="verification failed"

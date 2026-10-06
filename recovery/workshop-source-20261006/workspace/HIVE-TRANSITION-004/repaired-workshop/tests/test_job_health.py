from workshop.runtime import JobManager, State

def test_health_after_completed_job():
    jobs=JobManager(max_jobs=10)
    job=jobs.start(lambda j: j.update(State.COMPLETED,100,"done"))
    assert job.done.wait(1)
    health=jobs.health()
    assert health["jobs"] == 1
    assert health["last_completed_at"] is not None

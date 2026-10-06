import app
from workshop import hive_verifier


def test_health_identifies_loaded_local_verifier_policy():
    health = app.health()
    assert health["apparatus"] == {
        "study": "HIVE-LOCAL-001",
        "jvm_verifier_pids": 448,
        "jvm_verifier_image": hive_verifier.DEFAULT_IMAGE,
    }
    assert health["ok"] is True
    assert health["jobs"]["active_jobs"] >= 0

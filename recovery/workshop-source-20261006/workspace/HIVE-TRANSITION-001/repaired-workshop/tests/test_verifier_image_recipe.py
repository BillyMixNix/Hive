from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_verifier_image_installs_python_dependencies_in_an_isolated_venv():
    dockerfile = (ROOT / "verification" / "Dockerfile").read_text(encoding="utf-8")

    assert "python3-venv" in dockerfile
    assert "python3 -m venv /opt/verifier-venv" in dockerfile
    assert (
        "/opt/verifier-venv/bin/python -m pip install --no-cache-dir "
        "-r /opt/verifier/requirements.txt"
    ) in dockerfile
    assert 'ENV PATH="/opt/verifier-venv/bin:${PATH}"' in dockerfile
    assert "--break-system-packages" not in dockerfile


def test_verifier_requirement_specifications_are_unchanged():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert requirements.splitlines() == [
        "fastapi>=0.115",
        "uvicorn[standard]>=0.30",
        "httpx>=0.27",
        "python-multipart>=0.0.9",
        "pydantic>=2.8",
        "",
        "pytest>=8.0",
    ]

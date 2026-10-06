
import re
import shutil
import subprocess
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "static" / "index.html"

def test_frontend_javascript_syntax():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    html = INDEX.read_text(encoding="utf-8")
    m = re.search(r"<script>(.*?)</script>", html, re.S | re.I)
    assert m, "inline script block not found"
    cp = subprocess.run([node, "--check"], input=m.group(1), text=True, capture_output=True)
    assert cp.returncode == 0, cp.stderr

def test_structured_hive_errors_render_as_json():
    html = INDEX.read_text(encoding="utf-8")
    assert "typeof error==='string'?error:JSON.stringify(error,null,2)" in html
    assert "run.errors.join('\\n')" not in html
    assert "[object Object]" not in html

def test_hive_job_polling_displays_truthful_stage_message():
    html = INDEX.read_text(encoding="utf-8")
    assert "job.message||('Hive job '+job.state)" in html
    assert "`Hive job ${job.state} · ${job.progress}%`" not in html

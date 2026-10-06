import io
import json
from pathlib import Path
import urllib.error
import urllib.request

import pytest

from analysis.cloud_http400 import CaptureHTTP, read_plan


def test_error_capture_redacts_secret_and_does_not_retry(tmp_path):
    secret = "sk-example-private-12345678901234567890"
    class Reject:
        calls = 0
        def open(self, request, timeout):
            self.calls += 1
            raise urllib.error.HTTPError(request.full_url, 400, secret, {},
                io.BytesIO(json.dumps({"error": {"message": "bad request " + secret,
                    "code": "invalid_request", "param": "input"}}).encode()))
    opener = Reject()
    capture = CaptureHTTP(opener, tmp_path, secret)
    request = urllib.request.Request("https://api.openai.com/v1/responses",
        data=json.dumps({"input": secret}).encode(), headers={"Authorization": "Bearer " + secret})
    with pytest.raises(urllib.error.HTTPError) as exc:
        capture.open(request, timeout=1)
    exc.value.close()
    assert opener.calls == 1
    assert all(secret not in p.read_text() for p in tmp_path.glob("*.json"))
    saved = json.loads((tmp_path / "http-error.json").read_text())
    assert saved["http_status"] == 400 and saved["error"]["param"] == "input"


def test_diagnostic_keeps_entire_interrupted_request_reservation():
    plan, inputs = read_plan()
    spending = inputs["prior_report"]["spending"]
    assert spending["total_upper_nano_usd"] == 1019005900
    assert spending["total_upper_nano_usd"] == sum(spending[k] for k in
        ("prior_upper_nano_usd", "measured_usage_upper_nano_usd", "unresolved_reservation_nano_usd"))
    assert plan["max_requests"] == 1

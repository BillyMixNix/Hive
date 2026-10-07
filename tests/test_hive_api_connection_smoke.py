"""Offline contract checks; these tests never use a real credential or network."""

from datetime import date
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import hive_api_connection_smoke as smoke


class FakeResponse:
    def __init__(self, payload=None, *, status=200, raw=None):
        self.status = status
        self.payload = payload if payload is not None else {
            "model": smoke.MODEL, "service_tier": "default",
            "status": "completed",
            "usage": {"input_tokens": 22, "output_tokens": 5, "total_tokens": 27},
        }
        self.raw = raw

    def read(self, limit):
        assert limit == 65_537
        return self.raw if self.raw is not None else json.dumps(self.payload).encode()


class FakeConnection:
    calls = []
    response = FakeResponse()

    def __init__(self, host, timeout):
        assert (host, timeout) == ("api.openai.com", 60)
        self.calls.append(self)
        self.requests = []

    def request(self, method, path, body, headers):
        self.requests.append((method, path, json.loads(body), headers))

    def getresponse(self):
        return self.response

    def close(self):
        pass


class SmokeContractTests(unittest.TestCase):
    def setUp(self):
        FakeConnection.calls = []
        FakeConnection.response = FakeResponse()

    def test_one_fixed_generation_and_safe_result(self):
        result = smoke.run_smoke("sk-test-only", connection_factory=FakeConnection,
                                 today=date(2026, 10, 7))
        self.assertEqual(len(FakeConnection.calls), 1)
        requests = FakeConnection.calls[0].requests
        self.assertEqual(len(requests), 1)
        method, path, body, headers = requests[0]
        self.assertEqual((method, path), ("POST", "/v1/responses"))
        self.assertEqual(body["model"], smoke.MODEL)
        self.assertEqual(body["input"], smoke.PROMPT)
        self.assertEqual(body["max_output_tokens"], 16)
        self.assertEqual(body["reasoning"], {"effort": "none"})
        self.assertEqual(body["service_tier"], "default")
        self.assertEqual(body["tools"], [])
        self.assertFalse(body["store"])
        self.assertIn("sk-test-only", headers["Authorization"])
        self.assertNotIn("sk-test-only", json.dumps(result))
        self.assertEqual(result["classification"], "CONNECTIVITY_PASS")
        self.assertEqual(smoke.planned_cost_usd(), smoke.Decimal("0.0086064"))

    def test_missing_key_and_expired_price_fail_before_connection(self):
        for key, when, reason in [
            ("", date(2026, 10, 7), "API_KEY_UNAVAILABLE"),
            ("sk-test-only", date(2026, 10, 15), "PRICE_REVIEW_EXPIRED"),
        ]:
            with self.subTest(reason=reason):
                with self.assertRaises(smoke.SmokeFailure) as caught:
                    smoke.run_smoke(key, connection_factory=FakeConnection, today=when)
                self.assertEqual(caught.exception.classification, reason)
                self.assertEqual(FakeConnection.calls, [])

    def test_bad_response_fails_without_retry(self):
        for change, reason in [
            ({"model": "unexpected"}, "RESPONSE_UNEXPECTED"),
            ({"usage": {"input_tokens": 4097, "output_tokens": 1,
                        "total_tokens": 4098}}, "USAGE_EXCEEDED_ENVELOPE"),
        ]:
            with self.subTest(reason=reason):
                payload = dict(FakeResponse().payload)
                payload.update(change)
                FakeConnection.response = FakeResponse(payload)
                FakeConnection.calls = []
                with self.assertRaises(smoke.SmokeFailure) as caught:
                    smoke.run_smoke("sk-test-only", connection_factory=FakeConnection,
                                    today=date(2026, 10, 7))
                self.assertEqual(caught.exception.classification, reason)
                self.assertEqual(len(FakeConnection.calls), 1)
                self.assertEqual(len(FakeConnection.calls[0].requests), 1)

    def test_allowlisted_http_diagnostics_only(self):
        FakeConnection.response = FakeResponse({"error": {
            "code": "credit_balance_exhausted", "type": "insufficient_quota",
            "param": "service_tier", "message": "private sk-test-only"}}, status=429)
        with self.assertRaises(smoke.SmokeFailure) as caught:
            smoke.run_smoke("sk-test-only", connection_factory=FakeConnection,
                            today=date(2026, 10, 7))
        self.assertEqual(caught.exception.classification, "API_HTTP_ERROR")
        self.assertEqual(caught.exception.details, {
            "http_status": 429, "error_code": "credit_balance_exhausted",
            "error_type": "insufficient_quota", "error_param": "service_tier",
        })
        self.assertEqual(len(FakeConnection.calls[0].requests), 1)

    def test_malformed_unknown_and_secret_fields_cannot_leak(self):
        cases = [
            FakeResponse(status=400, raw=b"{bad JSON sk-test-only"),
            FakeResponse({"error": ["sk-test-only"]}, status=401),
            FakeResponse({"error": {
                "code": "sk-test-only", "type": "secret-type",
                "param": "Bearer sk-test-only", "message": "sk-test-only",
                "extra": "sk-test-only"}}, status=403),
        ]
        for response in cases:
            with self.subTest(status=response.status):
                FakeConnection.response = response
                FakeConnection.calls = []
                with self.assertRaises(smoke.SmokeFailure) as caught:
                    smoke.run_smoke("sk-test-only", connection_factory=FakeConnection,
                                    today=date(2026, 10, 7))
                self.assertEqual(caught.exception.details,
                                 {"http_status": response.status})
                self.assertNotIn("sk-test-only", repr(caught.exception.details))
                self.assertEqual(len(FakeConnection.calls[0].requests), 1)

    def test_artifact_contains_only_safe_diagnostics(self):
        FakeConnection.response = FakeResponse({"error": {
            "code": "model_not_found", "type": "invalid_request_error",
            "param": "model", "message": "secret sk-test-only"}}, status=404)
        with tempfile.TemporaryDirectory() as directory:
            original_run = smoke.run_smoke

            def offline_run(key):
                return original_run(key, connection_factory=FakeConnection,
                                    today=date(2026, 10, 7))

            with (patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-only"}),
                  patch.object(smoke, "run_smoke", side_effect=offline_run),
                  patch("sys.argv", ["smoke", "--output-root", directory])):
                self.assertEqual(smoke.main(), 2)
            artifact = Path(directory, "HIVE_API_CONNECTION_SMOKE.json").read_text()
            self.assertIn('"http_status": 404', artifact)
            self.assertIn('"error_code": "model_not_found"', artifact)
            self.assertNotIn("sk-test-only", artifact)
            self.assertNotIn("message", artifact)


if __name__ == "__main__":
    unittest.main()

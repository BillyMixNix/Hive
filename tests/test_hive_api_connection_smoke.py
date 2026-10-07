"""Offline contract checks; these tests never use a real credential or network."""

from datetime import date
import json
import unittest

from scripts import hive_api_connection_smoke as smoke


class FakeResponse:
    status = 200

    def __init__(self, payload=None):
        self.payload = payload or {
            "model": smoke.MODEL, "service_tier": "default",
            "status": "completed",
            "usage": {"input_tokens": 22, "output_tokens": 5, "total_tokens": 27},
        }

    def read(self, limit):
        assert limit == 65_537
        return json.dumps(self.payload).encode()


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


if __name__ == "__main__":
    unittest.main()

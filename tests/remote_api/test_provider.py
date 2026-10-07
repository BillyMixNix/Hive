"""Adversarial provider/budget tests: no live model, paid call, or candidate code."""
import asyncio
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from hive_remote.providers import Budget, Limits, MockProvider, OpenAIProvider, ProviderFailure, encode, sha
from hive_remote.qualification import QualificationFailure, require_remote_qualification
from hive_remote.runner import smoke

KEY = "synthetic-test-credential-never-real"


def response(text="HIVE_API_OK", *, incoming=25, outgoing=4):
    return {"id": "resp_test", "model": "configured-model-snapshot", "status": "completed",
            "usage": {"input_tokens": incoming, "output_tokens": outgoing, "total_tokens": incoming + outgoing},
            "output": [{"type": "message", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": text}]}]}


class FakeTransport:
    def __init__(self, result=None, count=25, status=200, failure=None):
        self.result = response() if result is None else result
        self.count, self.status, self.failure = count, status, failure
        self.calls = []

    def __call__(self, endpoint, body, headers, timeout):
        self.calls.append((endpoint, body, headers, timeout))
        if endpoint.endswith("input_tokens"):
            return 200, {"x-request-id": "count_test"}, encode({"input_tokens": self.count})
        if self.failure:
            raise self.failure
        return self.status, {"x-request-id": "request_test"}, encode(self.result)


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"OPENAI_API_KEY": KEY})
        self.env.start()
        self.addCleanup(self.env.stop)

    def provider(self, transport=None, **kwargs):
        budget = Budget(Limits(**kwargs), self.root / "provider")
        return OpenAIProvider(model="configured-model", budget=budget, transport=transport or FakeTransport()), budget

    def call(self, provider, prompt="public prompt", role="planner"):
        return asyncio.run(provider(role, prompt))

    def fails(self, provider, kind, **kwargs):
        with self.assertRaises(ProviderFailure) as result:
            self.call(provider, **kwargs)
        self.assertEqual(result.exception.classification, kind)

    def test_exact_payload_response_and_safe_metadata(self):
        transport = FakeTransport()
        provider, budget = self.provider(transport)
        prompt = "Public UTF-8 prompt — café"
        self.assertEqual(self.call(provider, prompt), "HIVE_API_OK")
        self.assertNotIn("OPENAI_API_KEY", os.environ)
        self.assertEqual(len(transport.calls), 2)
        count = json.loads(transport.calls[0][1])
        request = json.loads(transport.calls[1][1])
        self.assertEqual(request["input"], prompt)
        self.assertFalse(request["store"])
        self.assertEqual(request["tools"], [])
        self.assertEqual(request["max_output_tokens"], 32)
        for field in ("model", "input", "instructions", "tools"):
            self.assertEqual(count[field], request[field])
        self.assertEqual(transport.calls[1][2]["Authorization"], "Bearer " + KEY)
        folder = budget.output / "call-0001"
        self.assertEqual((folder / "generation.request.json").read_bytes(), transport.calls[1][1])
        self.assertEqual((folder / "generation.response.json").read_bytes(), encode(transport.result))
        meta = json.loads((folder / "call.json").read_bytes())
        self.assertEqual(meta["prompt_sha256"], sha(prompt.encode()))
        self.assertEqual(meta["returned_model"], "configured-model-snapshot")
        self.assertEqual(budget.calls, 1)
        self.assertEqual(budget.api_requests, 2)
        self.assertEqual(budget.summary()["total_tokens"], 29)
        for file in self.root.rglob("*"):
            if file.is_file():
                self.assertNotIn(KEY.encode(), file.read_bytes())

    def test_call_cap_blocks_before_even_count_request(self):
        transport = FakeTransport()
        provider, budget = self.provider(transport)
        self.call(provider)
        self.fails(provider, "MAX_MODEL_CALLS")
        self.assertEqual(len(transport.calls), 2)
        self.assertEqual(budget.calls, 1)

    def test_total_token_reservation_blocks_generation(self):
        transport = FakeTransport()
        provider, budget = self.provider(transport, max_total_tokens=56)
        self.fails(provider, "MAX_TOTAL_TOKENS")
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(budget.calls, 0)

    def test_input_limit_blocks_generation(self):
        transport = FakeTransport(count=513)
        provider, budget = self.provider(transport)
        self.fails(provider, "MAX_INPUT_TOKENS")
        self.assertEqual(budget.calls, 0)

    def test_invalid_counts_fail_closed(self):
        for count in (True, -1, "25", None):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as temp:
                os.environ["OPENAI_API_KEY"] = KEY
                budget = Budget(Limits(), Path(temp) / "provider")
                transport = FakeTransport(count=count)
                provider = OpenAIProvider(model="m", budget=budget, transport=transport)
                self.fails(provider, "INVALID_INPUT_COUNT")
                self.assertEqual(budget.calls, 0)

    def test_dollar_reservation_blocks_generation(self):
        transport = FakeTransport()
        provider, budget = self.provider(transport, max_cost_usd="0.000001", input_usd_per_million="100", output_usd_per_million="100")
        self.fails(provider, "MAX_EXPERIMENT_COST")
        self.assertEqual(budget.calls, 0)

    def test_rates_missing_negative_nan_fail_closed(self):
        for rates in ({"max_cost_usd": "1"}, {"max_cost_usd": "NaN", "input_usd_per_million": "1", "output_usd_per_million": "1"},
                      {"max_cost_usd": "1", "input_usd_per_million": "-1", "output_usd_per_million": "1"}):
            with self.subTest(rates=rates), self.assertRaises(ProviderFailure):
                Limits(**rates)

    def test_missing_usage_retains_unknown_charge_and_no_retry(self):
        result = response()
        result.pop("usage")
        transport = FakeTransport(result)
        provider, budget = self.provider(transport, max_model_calls=3)
        self.fails(provider, "USAGE_UNAVAILABLE")
        self.fails(provider, "USAGE_UNAVAILABLE")
        self.assertEqual(len(transport.calls), 2)
        self.assertEqual(budget.reserved_tokens, 57)

    def test_reported_usage_exceeding_reservation_halts(self):
        provider, budget = self.provider(FakeTransport(response(outgoing=33)))
        self.fails(provider, "PROVIDER_EXCEEDED_RESERVATION")
        self.assertEqual(budget.output_tokens, 33)

    def test_incomplete_response_usage_is_still_charged(self):
        result = response()
        result["status"] = "incomplete"
        provider, budget = self.provider(FakeTransport(result))
        self.fails(provider, "INCOMPLETE_OR_FAILED_RESPONSE")
        self.assertEqual(budget.summary()["total_tokens"], 29)

    def test_raw_exception_with_secret_is_never_recorded(self):
        provider, budget = self.provider(FakeTransport(failure=OSError("secret=" + KEY)))
        self.fails(provider, "PROVIDER_TRANSPORT_FAILURE_CHARGE_UNKNOWN")
        for file in self.root.rglob("*"):
            if file.is_file():
                self.assertNotIn(KEY.encode(), file.read_bytes())
        self.assertEqual(budget.reserved_tokens, 57)

    def test_secret_in_prompt_blocked_before_transport(self):
        transport = FakeTransport()
        provider, budget = self.provider(transport)
        self.fails(provider, "SECRET_CONTAMINATION", prompt="echo " + KEY)
        self.assertEqual(transport.calls, [])
        self.assertEqual(budget.calls, 0)

    def test_secret_in_response_is_not_saved_or_returned(self):
        provider, budget = self.provider(FakeTransport(response(KEY)))
        self.fails(provider, "SECRET_CONTAMINATION")
        self.assertFalse((budget.output / "call-0001/generation.response.json").exists())
        for file in self.root.rglob("*"):
            if file.is_file():
                self.assertNotIn(KEY.encode(), file.read_bytes())

    def test_no_fallback_or_retry_on_auth_quota_server_error(self):
        for status, kind in ((401, "AUTHENTICATION_FAILURE"), (429, "RATE_LIMIT_OR_QUOTA"), (503, "PROVIDER_SERVER_ERROR")):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as temp:
                os.environ["OPENAI_API_KEY"] = KEY
                budget = Budget(Limits(), Path(temp) / "provider")
                transport = FakeTransport(status=status)
                provider = OpenAIProvider(model="m", budget=budget, transport=transport)
                self.fails(provider, kind)
                self.assertEqual(len(transport.calls), 2)

    def test_restart_cannot_reset_ledger(self):
        provider, budget = self.provider()
        self.call(provider)
        with self.assertRaises(FileExistsError):
            Budget(Limits(), budget.output)

    def test_parallel_calls_cannot_overspend_single_call_limit(self):
        provider, budget = self.provider()
        async def concurrent():
            return await asyncio.gather(provider("planner", "p"), provider("backend", "b"), return_exceptions=True)
        results = asyncio.run(concurrent())
        self.assertEqual(sum(isinstance(x, str) for x in results), 1)
        self.assertEqual(budget.calls, 1)

    def test_cancellation_latches_before_generation(self):
        entered, released = threading.Event(), threading.Event()
        transport = FakeTransport()
        def paused(*args):
            entered.set()
            released.wait(3)
            return transport(*args)
        provider, budget = self.provider(paused, max_model_calls=2)
        async def cancelled():
            call = asyncio.create_task(provider("planner", "p"))
            await asyncio.to_thread(entered.wait, 2)
            call.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await call
            released.set()
        asyncio.run(cancelled())
        self.assertEqual(budget.calls, 0)
        self.fails(provider, "CANCELLED_CHARGE_UNKNOWN")

    def test_model_config_and_reasoning_explicit(self):
        budget = Budget(Limits(), self.root / "provider")
        transport = FakeTransport()
        provider = OpenAIProvider(model="snapshot", budget=budget, reasoning_effort="low", transport=transport)
        self.call(provider)
        self.assertEqual(json.loads(transport.calls[1][1])["reasoning"], {"effort": "low"})

    def test_tools_refused(self):
        result = response()
        result["output"].append({"type": "function_call", "name": "shell"})
        provider, _ = self.provider(FakeTransport(result))
        self.fails(provider, "UNEXPECTED_TOOL_OR_OUTPUT")

    def test_smoke_only_infrastructure(self):
        self.root.mkdir(exist_ok=True)
        report = asyncio.run(smoke(self.root, model="m", reasoning_effort=None, limits=Limits(), transport=FakeTransport()))
        self.assertEqual(report["status"], "PASS")
        self.assertFalse(report["software_generation_success"])
        self.assertFalse(report["candidate_execution"])
        self.assertEqual(report["accounting"]["model_call_count"], 1)

    def test_missing_key_records_zero_calls(self):
        os.environ.pop("OPENAI_API_KEY")
        report = asyncio.run(smoke(self.root, model="m", reasoning_effort=None, limits=Limits()))
        self.assertEqual(report["status"], "UNAVAILABLE")
        self.assertEqual(report["accounting"]["model_call_count"], 0)

    def test_forged_qualification_json_never_authorizes_cloud_run(self):
        with self.assertRaises(QualificationFailure):
            require_remote_qualification({"remote_verifier_qualified": True, "ready_for_model_backed_task": True})

    def test_mock_implements_same_callable_without_paid_inference(self):
        mock = MockProvider("answer")
        self.assertEqual(self.call(mock), "answer")
        self.assertEqual(mock.calls, [("planner", "public prompt")])


if __name__ == "__main__":
    unittest.main()

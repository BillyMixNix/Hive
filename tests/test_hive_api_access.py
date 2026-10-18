"""Verify the exact inline workflow script using offline HTTP fixtures."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import textwrap
import unittest
from unittest.mock import patch
import urllib.error


WORKFLOW = Path(__file__).resolve().parents[1] / '.github/workflows/hive-api-access.yml'
FAKE_KEY = 'fixture_credential_not_a_real_api_key'


class HiveApiAccessTests(unittest.TestCase):
    def test_access_check_never_generates_or_logs_credentials(self):
        text = WORKFLOW.read_text(encoding='utf-8')
        source = textwrap.dedent(text.split("python3 - <<'PY'\n", 1)[1].rsplit('\n          PY', 1)[0])
        compiled = compile(source, str(WORKFLOW), 'exec')
        cases = [
            ('missing', '', None, 2, 'KEY_REQUIRED'),
            ('invalid', FAKE_KEY + '\n', None, 2, 'INVALID_KEY_FORMAT'),
            ('success', FAKE_KEY, b'{"object":"list","data":[{"id":"fixture-model"}]}', 0, 'AUTHENTICATED'),
            ('malformed', FAKE_KEY, b'not JSON', 1, 'INVALID_RESPONSE'),
            ('wrong_shape', FAKE_KEY, b'{"object":"list","data":null}', 1, 'INVALID_RESPONSE'),
            ('http', FAKE_KEY, urllib.error.HTTPError('https://api.openai.com/v1/models', 401,
                                                     FAKE_KEY, {}, io.BytesIO(FAKE_KEY.encode())), 1, 'HTTP_REJECTED'),
            ('network', FAKE_KEY, urllib.error.URLError(FAKE_KEY), 1, 'TRANSPORT_ERROR'),
        ]
        for name, credential, response, expected_exit, status in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                summary = Path(directory) / 'summary.md'
                calls, output, errors = [], io.StringIO(), io.StringIO()
                outer = self

                class Opener:
                    def open(self, request, timeout):
                        outer.assertEqual(request.get_method(), 'GET')
                        outer.assertEqual(request.full_url, 'https://api.openai.com/v1/models')
                        outer.assertIsNone(request.data)
                        outer.assertEqual(request.get_header('Authorization'), 'Bearer ' + FAKE_KEY)
                        outer.assertNotIn('HIVE_OPENAI_API_KEY', os.environ)
                        calls.append(request)
                        if isinstance(response, Exception):
                            raise response
                        return io.BytesIO(response)

                namespace = {'__name__': '__main__'}
                with patch.dict(os.environ, {'HIVE_OPENAI_API_KEY': credential,
                                             'GITHUB_STEP_SUMMARY': str(summary)}, clear=True), \
                        patch('urllib.request.build_opener', return_value=Opener()), \
                        contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                    with self.assertRaises(SystemExit) as stopped:
                        exec(compiled, namespace)
                self.assertEqual(stopped.exception.code, expected_exit)
                report = json.loads(output.getvalue())
                self.assertEqual(report['status'], status)
                self.assertEqual(report['model_requests'], 0)
                self.assertEqual(len(calls), 0 if response is None else 1)
                self.assertNotIn(FAKE_KEY, output.getvalue() + errors.getvalue() + summary.read_text())
                self.assertIsNone(namespace['NoRedirect']().redirect_request(
                    None, None, 302, 'Moved', {}, 'https://example.invalid/receive'))


if __name__ == '__main__':
    unittest.main()

"""One diagnostic request, with the interrupted study's full cost carried forward."""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hive_learning.cloud_trial import allowed_launch
from hive_learning.evaluate import strict_json
from hive_learning.ledger import digest
from hive_learning.lesson_study import save_json
from hive_learning.openai_adapter import OpenAIHive, load_api_key
from hive_learning.response_trace import ResponseTrace
from hive_learning.spending import LIMIT_NUSD, MODEL, SpendingGuard


def clean(value, secret):
    if isinstance(value, str):
        return re.sub(r'sk-[A-Za-z0-9_-]{12,}', '[REDACTED]', value.replace(secret, '[REDACTED]'))
    if isinstance(value, list):
        return [clean(item, secret) for item in value]
    if isinstance(value, dict):
        return {clean(key, secret): clean(item, secret) for key, item in value.items()}
    return value


class CaptureHTTP:
    def __init__(self, opener, output, secret):
        self.opener, self.output, self.secret = opener, output, secret

    def open(self, request, timeout):
        save_json(self.output/'request.json', clean(strict_json(request.data), self.secret))
        try:
            return self.opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            raw = exc.read(65537)
            try:
                body = strict_json(raw)
                detail = body.get('error', {})
                detail = {key: detail[key] for key in ('message', 'type', 'code', 'param') if key in detail}
            except Exception:
                detail = {'body_format': 'unparseable; not retained'}
            safe = clean({'http_status': exc.code, 'error': detail}, self.secret)
            save_json(self.output/'http-error.json', safe)
            status, headers = exc.code, exc.headers
            exc.close()
            # Existing transport still fails closed; no retry or action execution.
            raise urllib.error.HTTPError(request.full_url, status, 'captured HTTP error', headers, io.BytesIO(raw)) from None


def read_plan():
    plan = strict_json((ROOT/'http400-plan.json').read_bytes())
    if (plan['max_requests'] != 1 or plan['launch_message'] != 'Run authorized Hive HTTP 400 diagnostic'
            or not re.fullmatch(r'[a-f0-9]{40}', plan['launch_parent'])):
        raise ValueError('invalid diagnostic commitment')
    inputs = {}
    for key in ('prior_report', 'packet'):
        name = plan[key]
        if '..' in Path(name).parts or Path(name).is_absolute():
            raise ValueError('invalid diagnostic input path')
        raw = (ROOT/name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != plan[key+'_sha256']:
            raise ValueError('diagnostic input commitment changed')
        inputs[key] = strict_json(raw)
    prior = inputs['prior_report']
    spent = prior['spending']['total_upper_nano_usd']
    if (type(spent) is not int or not 0 <= spent <= LIMIT_NUSD
            or prior['episode_id'] != plan['prior_episode_id']
            or plan['carry_forward_policy'] != 'Retain every prior measured charge and the entire unresolved reservation as permanent worst-case spending; no refund claimed'):
        raise ValueError('invalid cumulative spending carry')
    return plan, inputs


def main():
    plan, inputs = read_plan()
    event = strict_json(Path(os.environ['GITHUB_EVENT_PATH']).read_bytes())
    if not allowed_launch({**os.environ,'HIVE_LAUNCH_PARENT':plan['launch_parent']}, event, plan['launch_message']):
        os.environ.pop('OPENAI_API_KEY', None)
        return 2
    if sys.argv[1:] == ['--check']:
        print(json.dumps({'status':'COMMITMENT_VERIFIED','prior_upper_nano_usd':inputs['prior_report']['spending']['total_upper_nano_usd']}))
        return 0
    output = Path(sys.argv[1]);output.mkdir(parents=True,exist_ok=False)
    manifest = {'scope':'diagnostic_only','plan':plan,'run_id':os.environ['GITHUB_RUN_ID'],
                'commit':os.environ['GITHUB_SHA'],'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    save_json(output/'manifest.json',manifest)
    report = {'episode_id':digest(manifest),'scope':'diagnostic_only','continued_after':inputs['prior_report']['episode_id'],
              'status':'FAILED','interpretation':'One reconstructed request; no Hive action executed and no lesson/evaluation outcome produced. Prior unresolved charge is retained in full.'}
    guard = adapter = None
    try:
        key = load_api_key()
        guard = SpendingGuard(output/'spending.jsonl',prior_upper_nano_usd=inputs['prior_report']['spending']['total_upper_nano_usd'])
        adapter = OpenAIHive(MODEL,key,max_requests=1,spending=guard,observer=ResponseTrace(output/'responses'))
        meter = adapter._new_meter(1,deadline=120)
        meter.opener = CaptureHTTP(meter.opener,output,key)
        del key
        action = meter.worker(inputs['packet']['messages'])
        save_json(output/'unexecuted-action.json',strict_json(action))
        report['status'] = 'REQUEST_ACCEPTED'
    except Exception as exc:
        report['error_type'] = type(exc).__name__
    finally:
        os.environ.pop('OPENAI_API_KEY',None)
        if adapter:
            report['transport_usage'] = adapter.observed_usage()
        if guard:
            report['spending'] = guard.snapshot();guard.close()
    if (output/'http-error.json').exists():
        report['http_error'] = strict_json((output/'http-error.json').read_bytes())
    save_json(output/'report.json',report)
    save_json(output/'checksums.json',{p.relative_to(output).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output.rglob('*')) if p.is_file()})
    print('HIVE_DIAGNOSTIC_REPORT '+json.dumps(report,sort_keys=True),flush=True)
    return 0 if report['status']=='REQUEST_ACCEPTED' else 2


if __name__ == '__main__':
    raise SystemExit(main())

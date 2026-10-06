"""Read-only reconstruction of the preserved factorial; writes only this study."""
import collections
import hashlib
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
PRIOR = Path(r'C:\Users\billy\Documents\Codex\2026-09-13\referenced-chatgpt-conversation-this-is-an\work\HIVE-FACTORIAL-002')
os.environ.pop('OPENAI_API_KEY', None)
sys.dont_write_bytecode = True
sys.path.insert(0, str(PRIOR / 'workshop'))
from workshop import hive, external_root

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def save(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

def textfile(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(value.encode('utf-8'))

def evaluate(raw, scope):
    tokens = [(hive._ACTIVE_AGENT_SCOPES, hive._ACTIVE_AGENT_SCOPES.set(hive.EXTERNAL_AGENT_SCOPES)),
              (hive._EXTERNAL_ROOT_MODE, hive._EXTERNAL_ROOT_MODE.set(True)),
              (hive._HOST_WRITE_SCOPE, hive._HOST_WRITE_SCOPE.set(tuple(scope)))]
    result = {}
    try:
        try:
            p = hive._extract_json(raw)
            result['parser'] = 'accepted'
            result['parsed'] = p
        except Exception as e:
            return {'parser': 'rejected', 'error': str(e)}
        try:
            p, _ = hive._normalize_plan(p)
            result['normalizer'] = 'accepted'
        except Exception as e:
            result.update(normalizer='rejected', error_type=type(e).__name__, error=str(e))
        # Independently inspect the known host boundary, even if historical flow never reached it.
        try:
            hive._validate_host_write_scope(p)
            result['independent_host_scope_check'] = 'accepted'
        except Exception as e:
            result.update(independent_host_scope_check='rejected', host_scope_error=str(e))
        return result
    finally:
        for var, token in reversed(tokens):
            var.reset(token)

def main():
    freeze = json.loads((PRIOR / 'FREEZE.json').read_text())
    assert sha(PRIOR / 'FREEZE.json') == (PRIOR / 'LOCK.sha256').read_text().strip()
    rs = json.loads((PRIOR / 'evidence/raw_results.json').read_text())
    rows = []
    for r in rs:
        if r['controller'] != 'hive':
            continue
        path = next((PRIOR / 'evidence').glob(f"{r['ordinal']:02d}-*/run.json"))
        run = json.loads(path.read_text())
        calls = run['metadata']['agent_calls']
        attempts = []
        for a in run['plan_attempts']:
            ev = evaluate(a['raw'], run['metadata']['host_write_scope'])
            attempts.append({'attempt': a['attempt'], 'recorded_status': a['status'],
                             'recorded_failure': a.get('failure', {}).get('exception_message'), **ev})
        first_error = attempts[0].get('error', '')
        if attempts[0]['recorded_status'] == 'accepted':
            category = 'worker_edit_anchor_mismatch'
            stage = 'edit execution preflight'
        elif 'active goal' in first_error:
            category = 'planner_inactive_role_representation_mismatch'
            stage = 'plan validation'
        else:
            category = 'planner_missing_contract_masks_host_scope_violation'
            stage = 'plan validation'
        rows.append({
            'ordinal': r['ordinal'], 'task': r['task_id'], 'replicate': r['replicate'],
            'model': r['model'], 'run_id': r['run_id'], 'earliest_failed_transition': stage,
            'category': category, 'run_artifact': str(path), 'run_sha256': sha(path),
            'attempts': attempts,
            'worker_calls': sum(c['role'] in hive.AGENT_SCOPES for c in calls),
            'model_calls': len(calls), 'changed_files': run['changed_files'],
            'terminal_errors': [{k: e[k] for k in ('role', 'stage', 'exception_type', 'exception_message') if k in e}
                                for e in run.get('errors', [])],
            'full_verification': run['verification'],
            'candidate_sha256': r['candidate_sha256'],
            'telemetry': [{k: c.get(k) for k in ('role', 'prompt_bytes', 'input_tokens', 'output_tokens', 'runtime')}
                          for c in calls],
        })
    counts = dict(collections.Counter(r['category'] for r in rows))
    taxonomy = {'study': 'HIVE-TRANSITION-001', 'source_study': str(PRIOR),
                'source_lock_sha256': sha(PRIOR / 'FREEZE.json'), 'counts': counts,
                'counts_note': 'Primary categories count each trial once; independent boundary violations can overlap.',
                'trials': rows}
    save(HERE / 'failure-taxonomy.json', taxonomy)
    table = '\n'.join(f"| {r['ordinal']} | {r['task']} / r{r['replicate']} | {r['model']} | `{r['run_id']}` | {r['category']} | {r['worker_calls']} |" for r in rows)
    textfile(HERE / 'failure-taxonomy.md', f'''# HIVE-TRANSITION-001: failure taxonomy

Source: `{PRIOR}/evidence/raw_results.json`, all 16 Hive trial `run.json` files and raw prompt traces. Every preserved plan parses as JSON. Classification records the earliest observable rejected transition; it does not infer hidden reasoning. Machine-readable per-attempt parse results, latent scope violations, errors, paths and hashes are in [failure-taxonomy.json](failure-taxonomy.json).

| Earliest failure class | Trials |
|---|---:|
| Missing role contract masks an already-present host scope violation | 8 |
| Inactive-role prose fails the recognized no-change contract | 6 |
| Worker edit anchor absent from source | 2 |

| Ordinal | Task / replicate | Model | Run | Primary class | Worker calls |
|---:|---|---|---|---|---:|
{table}

All eight qwen2.5-coder:14b trials have the same first rejection and then fail host scope after adding a contract. All six qwen3 planner failures have an inactive-role mismatch: e.g. `No UI changes required` is outside `_no_change_goal`'s accepted prefixes. Some also omit a required contract; one already supplies a contract. Three of these six initially propose unauthorized paths; all six do after correction. Thus 11/14 initial rejected plans and 14/14 corrected rejected plans violate host scope. The two initial plans that pass stay inside host scope. These are overlapping observations, not additional trial counts.

Fourteen trials terminate in planner correction exhaustion. Ordinals 6 and 26 reach backend workers and one structural repair each, then reject unresolved anchors. They record a failed `external_full_gate_prerequisite` sentinel, not execution of frozen JUnit or full Gradle. No Hive trial produces changed files, reaches frozen acceptance, or runs the full gate. No Hive provider call is recorded as a local runtime failure; this does not establish adequate model context. All candidates retain the baseline hash. No evidence here supports diagnosing a parser incompatibility or a deterministic acceptance failure.

All correction calls report 2,050 input tokens at runtime context length 4,096 despite prompts of 20,478–21,145 characters. Both workers also report 2,050. This is evidence of a possible context-delivery bottleneck, not proof of which instructions the model actually retained. Provider code sends full text and no explicit `num_ctx`; effective token sequence is not preserved.
''')
    runpath = next((PRIOR / 'evidence').glob('03-*/run.json'))
    run = json.loads(runpath.read_text())
    out = HERE / 'evidence/ordinal-03'
    save(out / 'run.json', run)
    checks = []
    tok = hive._HOST_WRITE_SCOPE.set(tuple(run['metadata']['host_write_scope']))
    scopes = hive._ACTIVE_AGENT_SCOPES.set(hive.EXTERNAL_AGENT_SCOPES)
    ext = hive._EXTERNAL_ROOT_MODE.set(True)
    try:
        for i, trace in enumerate(run['prompt_trace'], 1):
            prompt, raw = trace['prompt_text'], trace['response_text']
            assert hashlib.sha256(prompt.encode()).hexdigest() == trace['prompt_sha256']
            assert hashlib.sha256(raw.encode()).hexdigest() == trace['response_sha256']
            assert raw == run['plan_attempts'][i-1]['raw']
            if i == 1:
                rebuilt = hive._planner_prompt(run['request'], run['repository_map'], run['repository_facts'], run['intent_envelope'], external_mode=True)
            else:
                err = hive.PlanValidationError([run['plan_attempts'][0]['failure']['exception_message']])
                rebuilt = hive._plan_correction_prompt(run['request'], run['repository_map'], run['plan_attempts'][0]['raw'], err, run['repository_facts'], run['intent_envelope'], external_mode=True)
            assert str(rebuilt) == prompt
            textfile(out / f'planner-{i}.prompt.txt', prompt)
            textfile(out / f'planner-{i}.response.txt', raw)
            save(out / f'planner-{i}.schema.json', hive.response_schema_for_prompt('planner', rebuilt))
            checks.append({'attempt': i, 'prompt_sha256': trace['prompt_sha256'],
                           'response_sha256': trace['response_sha256'], 'prompt_exact_rebuild': True,
                           **evaluate(raw, run['metadata']['host_write_scope'])})
    finally:
        hive._HOST_WRITE_SCOPE.reset(tok)
        hive._ACTIVE_AGENT_SCOPES.reset(scopes)
        hive._EXTERNAL_ROOT_MODE.reset(ext)
    identities = {name: external_root.tree_sha256(root) for name, root in {
        'baseline': Path(freeze['baseline']['root']),
        'candidate': Path(run['metadata']['external_root']['candidate_root']),
        'stage': PRIOR / 'evidence/runs/cace24ea0b5e/stage',
    }.items()}
    save(out / 'before-replay.json', {'attempts': checks, 'tree_hashes': identities})
    textfile(HERE / 'reconstruction.md', f'''# Ordinal 3 reconstruction — cace24ea0b5e

This reconstruction was completed before modifying production source. Source root: `{PRIOR}/workshop`. Frozen task J001, replicate 2, qwen2.5-coder:14b, Hive. Source run: `{runpath}`. Freeze SHA-256: `{sha(PRIOR / 'FREEZE.json')}`. The source study is read-only throughout this investigation.

1. **Exact planner prompt:** [planner-1.prompt.txt](evidence/ordinal-03/planner-1.prompt.txt), SHA-256 `1d11a59f4c974ca9ebcea5c0dd5103fbe3b1a810b1a6ab92dc7dc19622d729ea`. All 17,180 characters are preserved in `run.json.prompt_trace[0]`; the generated prompt matches byte-for-byte. `runner.py:253–255` supplies it as the user message, alongside system text `You are the bounded planner agent inside Nix Workshop Hive Build Mode. Follow the role contract exactly.` The recorded 18,180 prompt_bytes includes the harness's artificial 1,000-byte budget reservation, not 1,000 more actual prompt bytes.
2. **Raw first response:** [planner-1.response.txt](evidence/ordinal-03/planner-1.response.txt), SHA-256 `12ddb25fd0494eab31749cc97a354c1e082fce6ca78cadd9dbce9c615ddba93f`. It identifies surrogate-preserving truncation, assigns the authorized Java class to backend and an unauthorized existing test file to tests, and returns `interface_contracts: []`.
3. **Expected contract:** [planner-1.schema.json](evidence/ordinal-03/planner-1.schema.json), reconstructed from `hive_protocol.py:36–45,130–167` and the frozen source. This schema requires role goals, worker files, acceptance and contracts, but `worker_files.*.items` is any nonempty string. Textual host scope forbids test writes. `_normalize_plan` additionally enforces active-goal/file/criteria consistency and a linking contract for multiple active roles. Planner cannot inspect through an observation loop and cannot submit edits; worker contracts separately permit bounded observations and exact supported edits. Optional `provider_changes` omission is legal.
4. **Parser result:** `_extract_json` (`hive.py:736`) returns a complete dict, exactly the raw JSON. The historical path reached semantic validation; deterministic replay confirms parsing succeeds. No syntax repair or parser incompatibility occurred.
5. **Validator result:** `_normalize_plan` (`hive.py:387–562`) raises `PlanValidationError: multi-role plan requires at least one interface contract`. `No changes needed for UI.` is recognized as inactive; backend and tests are active. The host check at line 1938 is never reached on this attempt.
6. **Why correction:** the `except` in `_run_build_impl` (`1933–1952`) records the failure and consumes the one allowed correction. The unauthorized test assignment is already present, but `_validate_host_write_scope` runs only after successful normalization, so it is absent from the first diagnostic.
7. **Exact correction prompt:** [planner-2.prompt.txt](evidence/ordinal-03/planner-2.prompt.txt), SHA-256 `b603b26921e3eb74ba455ef0c403e7d69c0c8369d50d1963528f462284890b2c`. It repeats the entire planner prompt, gives the missing-contract diagnostic and a backend/tests contract example, repeats the rejected response, and says there is ONE correction. `_plan_correction_prompt` (`1501–1577`) sets `interface_contracts.minItems=1` because this is a multi-role rejection not typed as `HostWriteScopeError`; [planner-2.schema.json](evidence/ordinal-03/planner-2.schema.json) preserves it. The paths remain unconstrained in the schema. This subtly steers repair toward preserving an unauthorized tests role.
8. **Raw corrected response:** [planner-2.response.txt](evidence/ordinal-03/planner-2.response.txt), SHA-256 `64cba174e37cea552725dd23d0389c45f0d9f57653f4e2ee586cda537960478e`. It supplies a valid backend-to-tests contract and retains the exact same test-file assignment.
9. **Corrected parse/validation:** JSON parsing and `_normalize_plan` succeed. `_validate_host_write_scope` (`607–619`) then raises `HostWriteScopeError`: `worker_files.tests proposes 'src/test/java/dev/atmcompanion/state/SnapshotFormatterTest.java' outside host-authorized task write files ['src/main/java/dev/atmcompanion/state/SnapshotFormatter.java']`. This is correct rejection of an invalid plan, not a valid plan lost by parsing.
10. **Termination:** `MAX_PLAN_CORRECTIONS=1` (line 29). On attempt 2, `_run_build_impl:1945–1948` marks planner failed and raises `PlanValidationError('Planner correction budget exhausted; ...')`; the outer catch (`2584–2586`) sets run.status=`failed`. Harness classification is `MODEL_TASK_FAILURE`. Two completed planner calls consumed 270.465 model seconds; no provider failure is recorded.
11. **Why no worker:** assignment of `run['plan']` and worker-loop eligibility occur only after validated planning (`1953` onward). The exception exits before `run_worker` can be invoked. `prompt_trace` and agent-call telemetry contain exactly two planner calls. No worker action generation, parser or edit executor ran.
12. **Why no edit:** the host created isolated copies before planning (`_run_build_impl:1832–1843` and `runner.run_one:194–225`); it did not create a modified candidate. `changed_files=[]`, `diff=''`, verification/review null, applied=false. Fresh read-only hashes for baseline, candidate and stage are all `{identities['baseline']}`. No acceptance or Gradle gate ran. A copied candidate directory is distinct from an edited candidate.

The earliest **observed failure** is plan validation. The scope mistake is visible in the first serialized plan, earlier than the terminal host-scope rejection. The supported host defect is incomplete contract/feedback propagation: authority appears in prose but not the schema, and scope feedback is masked by a prerequisite validation failure. Task misunderstanding is not established by these artifacts: the response captures the requested behavior, but never supplies code whose correctness can be tested.

The planner sees a repository map and implementation facts (`run.repository_facts`), not the actual `boundLine` body. The immutable intent envelope is empty. Workers would receive owned source and bounded observations, but this run never reaches them. The 4,096-token runtime and 2,050-token corrected input count raise a context-truncation hypothesis; exact effective input tokens and Ollama truncation logs were not preserved. Do not equate a correct host prompt hash with proof that the model attended to the whole prompt.

Replay details and hash checks: [before-replay.json](evidence/ordinal-03/before-replay.json). Full observable run including stage events and errors: [run.json](evidence/ordinal-03/run.json). Schema files are source-reconstructed, not separately captured historical HTTP requests; prompt bytes are directly preserved and hash-verified.
''')
    print(json.dumps({'counts': counts, 'tree_hashes': identities, 'exact_prompts_verified': 2}))

if __name__ == '__main__':
    main()

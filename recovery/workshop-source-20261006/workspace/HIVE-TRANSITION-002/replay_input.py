"""Replay preserved provider arguments and planner outputs; no network or models."""
import asyncio, hashlib, json, sys
from pathlib import Path
from diagnostic_capture import save
HERE=Path(__file__).resolve().parent
sys.dont_write_bytecode=True
sys.path.insert(0,str(HERE/'repaired-workshop'))
from workshop import hive, providers
from workshop.hive_protocol import LOCAL_CONTEXT_WINDOW

async def main():
    fixtures=HERE/'evidence/planner-input-fixtures'
    run=json.loads((fixtures/'run.json').read_text())
    rows=[]
    scope=hive._HOST_WRITE_SCOPE.set(('src/main/java/dev/atmcompanion/state/SnapshotFormatter.java',))
    roles=hive._ACTIVE_AGENT_SCOPES.set(hive.EXTERNAL_AGENT_SCOPES)
    external=hive._EXTERNAL_ROOT_MODE.set(True)
    try:
        for index in (1,2):
            args=json.loads((fixtures/f'{index:02d}/request.json').read_text())
            before=json.loads((HERE/f'evidence/measurements/historical-planner-{index}/reconstructed-wire.json').read_bytes())
            sent=[]
            async def sender(body,**kwargs):
                sent.append(body);return {'text':'','input_tokens':0,'output_tokens':0}
            providers._ollama_chat_once=sender
            await providers.ollama_chat(args['model'],args['messages'],args['instructions'],
                                       **args['options'],context_window=LOCAL_CONTEXT_WINDOW)
            after=sent[0]
            assert after=={**before,'options':{**before['options'],'num_ctx':12288},'truncate':False}
            raw=run['plan_attempts'][index-1]['raw']
            parsed=hive._extract_json(raw)
            try:
                hive._normalize_plan(parsed)
                rejection=None
            except hive.HostWriteScopeError as exc: rejection=str(exc)
            assert rejection==run['plan_attempts'][index-1]['failure']['exception_message']
            save(HERE/f'evidence/historical-replay/{index:02d}/repaired-body.json',after)
            rows.append({'attempt':index,'prompt_sha256':hashlib.sha256(after['messages'][-1]['content'].encode()).hexdigest(),
              'messages_unchanged':after['messages']==before['messages'],'schema_unchanged':after['format']==before['format'],
              'only_changes':{'options.num_ctx':12288,'truncate':False},'parser':'JSON object',
              'validator_before':run['plan_attempts'][index-1]['failure']['exception_message'],
              'validator_after':rejection,'accepted':False,'model_calls':0})
    finally:
        hive._EXTERNAL_ROOT_MODE.reset(external); hive._ACTIVE_AGENT_SCOPES.reset(roles);hive._HOST_WRITE_SCOPE.reset(scope)
    save(HERE/'evidence/historical-input-replay.json',rows)
    print('Both historical inputs serialized unchanged; both outputs remain rejected; zero model calls.')

if __name__=='__main__':asyncio.run(main())

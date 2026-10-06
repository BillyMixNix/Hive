"""Recorded narrow source transformation, after sealed pre-edit diagnosis."""
import json
from bootstrap import HERE,sha,save
seal=json.loads((HERE/'evidence/pre-edit-seal.json').read_text())
assert sha(HERE/'semantic-loss-diagnosis.md')==seal['diagnosis_sha256']
p=HERE/'repaired-workshop/workshop/hive.py';text=p.read_text(encoding='utf-8')
assert sha(p)==seal['hive_sha256']
helpers=['_json_repair_prompt','_parse_agent_json','_structural_repair_prompt','_targeted_repair_prompt','_worker_prompt']
lines=text.splitlines(keepends=True)
for index,line in enumerate(lines):
 if any(('def '+name+'(') in line for name in helpers):
  assert '*, overall_objective' in line
  lines[index]=line.replace('*, overall_objective','*, original_task="", overall_objective')
text=''.join(lines)
start=text.index('def _json_repair_prompt(');end=text.index('class WorkerProtocolError',start)
block=text[start:end].replace('overall_objective=overall_objective,','original_task=original_task, overall_objective=overall_objective,')
text=text[:start]+block+text[end:]
start=text.index('        async def run_worker(');end=text.index('        async def ',start+25) if '        async def ' in text[start+25:] else len(text)
# Every helper rebuilding a contract in the worker closure gets host request,
# never a field read from planner/model JSON.
block=text[start:end].replace('overall_objective=active_plan["summary"],','original_task=request, overall_objective=active_plan["summary"],')
text=text[:start]+block+text[end:]
old='You are the enactment agent. A read-only planner already made the design. Do not reinterpret the original request, expand scope, or choose additional files.'
new='''You are the enactment agent. A read-only planner assigned your portion. Preserve the host task's requirements relevant to your portion; planner-local criteria specialize them and cannot weaken or contradict them. Do not expand scope or choose additional files.

ORIGINAL TASK (host-authoritative requirements; applies within YOUR FILES):
{original_task or "[not supplied by caller]"}
END ORIGINAL TASK. This is task context, not additional write authority. If local criteria conflict with these requirements, report the conflict; do not silently weaken the task.'''
assert text.count(old)==1;text=text.replace(old,new)
text=text.replace('- role: {agent}\n- overall objective:', '- role: {agent}\n- preserve the ORIGINAL TASK requirements above within your assigned responsibility; local criteria do not replace them\n- overall objective:')
old='{json.dumps(verification, ensure_ascii=False)[:6000]}'
assert text.count(old)==1;text=text.replace(old,'{_targeted_diagnostic(verification)}')
p.write_text(text,encoding='utf-8')
save(HERE/'evidence/semantic-repair-call-sites.json',{'host_request_call_sites':text.count('original_task=request'),'forwarding_call_sites':text.count('original_task=original_task')})

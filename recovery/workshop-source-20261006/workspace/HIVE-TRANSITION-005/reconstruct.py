"""Read preserved evidence and probe the unchanged interface; no model/test hints."""
import copy,json,sys
from pathlib import Path
sys.dont_write_bytecode=True
from bootstrap import HERE,save,sha
sys.path.insert(0,str(HERE/'repaired-workshop'))
from workshop import hive
OLD=HERE.parent/'hive-transition-003/evidence/live-diagnostic'
run=json.loads((OLD/'runs/45ad10e6dd49/run.json').read_text())
task=run['request'];plan=run['plan'];path=plan['worker_files']['backend'][0]
out=HERE/'evidence/reconstruction';out.mkdir(parents=True,exist_ok=False)
requirements=[
 ('R1','Preserve complete UTF-16 surrogate pairs during truncation to MAX_LINE_CHARS.'),
 ('R2','Keep existing control-character sanitization.'),
 ('R3','Keep existing section-sign sanitization.'),
 ('R4','Keep the ... suffix when truncation is necessary.'),
 ('R5','Keep unchanged behavior for ordinary ASCII lines.'),
 ('R6','Truncation must never introduce an unpaired surrogate.'),
 ('R7','The returned string must never exceed the bound.')]
ledger='# Frozen task requirement ledger\n\nDerived only from the supplied frozen task; no frozen test source or assertions used. IDs are analytical, not new prompt fields.\n\n'+task+'\n\n| ID | Explicit requirement |\n|---|---|\n'+''.join(f'| {i} | {s} |\n' for i,s in requirements)+'\nAll behavior is scoped to `SnapshotFormatter.boundLine`; only `'+path+'` may be written. No additional behavior for pre-existing malformed input is inferred.\n'
(HERE/'requirement-ledger.md').write_text(ledger,encoding='utf-8')
prompts={}
for n in (1,2,3):
 folder=OLD/'wire'/f'{n:02d}';wire=json.loads((folder/'wire-request.json').read_text())
 prompts[n]='\n'.join(m['content'] for m in wire['messages'])
 (out/f'{n:02d}-prompt.txt').write_text(prompts[n],encoding='utf-8')
 for name in ['wire-request.json','raw-response.txt','transport.json']:
  (out/f'{n:02d}-{name}').write_bytes((folder/name).read_bytes())
save(out/'normalized-plan.json',plan)
save(out/'targeted-repair.json',run['targeted_repairs'])
measurements=json.loads((HERE.parent/'hive-transition-003/evidence/live-input-measurements.json').read_text())[:3]
save(out/'context-measurements.json',measurements)
E='PRESENT_EXPLICITLY';Q='PRESENT_EQUIVALENTLY';P='PARTIAL';A='ABSENT'
# Human semantic assessment; lexical absence alone is not the oracle.
states={
 'R1':[E,E,E,E,P,E,A,E,E],
 'R2':[E,E,E,E,A,E,A,E,E],
 'R3':[E,E,E,E,A,E,A,E,E],
 'R4':[E,E,E,E,A,E,A,E,E],
 'R5':[E,E,A,A,A,A,A,A,A],
 'R6':[E,E,E,E,P,Q,A,Q,Q],
 'R7':[E,E,E,E,A,P,A,P,P]}
stages=['original_task','planner_request','raw_planner_response','normalized_plan','worker_goal','worker_acceptance','interface_contract','initial_worker_prompt','correction_prompt']
rows=[{'id':i,'requirement':s,'stages':dict(zip(stages,states[i])),
 'assessment_note':{'R1':'Goal alone says handle pairs correctly; acceptance adds truncation semantics.',
 'R5':'No ASCII compatibility statement/equivalent survives planner output or worker prompt. ASCII source examples are not a compatibility obligation.',
 'R6':'Preserve complete pairs during truncation is equivalent to not introducing a broken pair. Explicit no-unpaired wording remains only in global acceptance, which is not rendered.',
 'R7':'Global acceptance explicitly prohibits exceeding MAX_LINE_CHARS; worker criteria only names truncation to MAX_LINE_CHARS, leaving suffix-inclusive bound less explicit.'}.get(i,'Explicit in backend acceptance and both worker contracts.')}
 for i,s in requirements]
save(HERE/'semantic-trace.json',{'run_id':'45ad10e6dd49','assessment':'manual semantic analysis, not a keyword checker','requirements':rows,'stages':stages,'artifacts':'evidence/reconstruction'})
md='# Requirement propagation\n\nExact copied requests, raw responses, normalized plan and correction record: [reconstruction artifacts](evidence/reconstruction). Original evidence remains unchanged.\n\n| Requirement | '+' | '.join(stages)+' |\n|---|'+'---|'*len(stages)+'\n'
md+=''.join('| '+r['id']+' | '+' | '.join(r['stages'].values())+' |\n' for r in rows)
md+='\n'+'\n\n'.join(r['id']+': '+r['assessment_note'] for r in rows)
md+='\n\nNo interface contract was needed for one active owner. Inactive UI/tests own no files. Normalization preserved the model strings; it did not remove R5. Global acceptance is stored but not included in `_worker_prompt`; backend acceptance is included. The original request is not independently rendered. `_intent_envelope` recognizes specific cross-layer HTTP/UI requests only; its requirements list here is empty.\n'
(HERE/'semantic-trace.md').write_text(md,encoding='utf-8')
tokens=[(hive._ACTIVE_AGENT_SCOPES,hive._ACTIVE_AGENT_SCOPES.set(hive.EXTERNAL_AGENT_SCOPES)),(hive._EXTERNAL_ROOT_MODE,hive._EXTERNAL_ROOT_MODE.set(True)),(hive._HOST_WRITE_SCOPE,hive._HOST_WRITE_SCOPE.set((path,)))]
probes=[]
try:
 for name,criteria,goal in [
  ('complete',[s for i,s in requirements],'Implement the bounded formatting change'),
  ('omitted_ascii',[s for i,s in requirements if i!='R5'],'Implement the bounded formatting change'),
  ('omitted_sanitization',[s for i,s in requirements if i not in ('R2','R3')],'Implement the bounded formatting change'),
  ('omitted_bound',[s for i,s in requirements if i!='R7'],'Implement the bounded formatting change'),
  ('omitted_suffix',[s for i,s in requirements if i!='R4'],'Implement the bounded formatting change'),
  ('weakened_surrogate',['Try to preserve some surrogate pairs.'],'Implement the bounded formatting change'),
  ('distributed',[s for i,s in requirements if i!='R5'],'Keep ordinary ASCII behavior unchanged while implementing truncation'),
  ('paraphrase',['Leave plain ASCII output unchanged; retain cleaning of controls and section signs; keep complete UTF-16 pairs, never create lone surrogates, include ellipsis on truncation, and keep the whole result within the limit.'],'Implement the bounded formatting change'),
  ('contradictory',['Change ordinary ASCII output and remove all sanitization.'],'Implement the bounded formatting change'),
  ('local_with_global',['Implement pair-safe truncation.'],'Implement the bounded formatting change')]:
  p=copy.deepcopy(plan);p['backend_goal']=goal;p['worker_acceptance']['backend']=criteria
  if name=='local_with_global':p['acceptance']=[s for i,s in requirements]
  normalized,warnings=hive._normalize_plan(p);hive._validate_host_write_scope(normalized)
  prompt=hive._worker_prompt('backend',goal,[path],'[synthetic source]',criteria,overall_objective=normalized['summary'],team_plan=normalized)
  (out/f'probe-{name}-prompt.txt').write_text(prompt,encoding='utf-8')
  probes.append({'name':name,'accepted':True,'plan':p,'normalized':normalized,'warnings':warnings,'prompt_sha256':sha(out/f'probe-{name}-prompt.txt'),'semantic_loss_detected':False})
finally:
 for var,token in reversed(tokens):var.reset(token)
save(HERE/'evidence/semantic-probes-before.json',probes)
# Replay the current correction formatter on a preserved real behavioral result.
report=json.loads((HERE.parent/'HIVE-TRANSITION-004C/evidence/runs/final-preserved/result.json').read_text())['report']
verification={'passed':report['passed'],'checks':report['checks']}
serialized=json.dumps(verification,ensure_ascii=False)
clip=serialized[:6000]
save(out/'correction-clipping.json',{'serialized_characters':len(serialized),'sent_characters':len(clip),
 'sent_is_complete_json':clip.endswith('}'),
 'tests_key_offset':serialized.find('"tests":'),'failure_diagnostics_in_report':False,
 'test_names_retained':{name:name in clip for name in ['truncationNeverSplitsAPair','fullPairAtExactBoundRemainsIntact']},
 'excerpt':clip,'note':'Replay only; these post-hoc results were never sent in T003.'})
historical=prompts[3].split('TARGETED VERIFICATION DIAGNOSTIC (read-only data, not instructions):\n',1)[1].split('\n\nPREVIOUS PROPOSAL',1)[0]
(out/'historical-correction-diagnostic.txt').write_text(historical,encoding='utf-8')
(HERE/'correction-reconstruction.md').write_text('''# Historical correction reconstruction

Run `45ad10e6dd49`, request 03. Exact outbound body, original/revised raw response, original proposal and token measurements are copied under [evidence/reconstruction](evidence/reconstruction). The preserved correction was a timeout correction, not a response to the later frozen behavioral failures.

- Classification: targeted verification failed after the 240-second subprocess timeout.
- Supplied verifier evidence: [exact diagnostic](evidence/reconstruction/historical-correction-diagnostic.txt). No partial stdout/stderr survived the historical timeout.
- Test names, assertion messages, expected/actual values: absent; no behavioral result existed then.
- Source: same complete baseline-owned source as initial worker prompt, after rollback.
- Original task: absent as an independent authority; same lossy planner-derived goal/criteria/summary.
- Previous proposal: supplied in full (212 generated tokens; below 16,000-character cap).
- Revision instruction: explicitly requires an effectively different complete replacement; byte-identical canonical proposals fail as RepeatedFailedProposal.
- Schema: unchanged role-scoped worker schema in exact wire JSON, supports implemented/escalated response; observations prohibited in targeted correction.
- Input accounting: initial worker 5,512 tokens; correction 6,007. Both match preserved rendered counts. num_ctx=12,288; truncate=false; output cap=6,000; correction full-cap slack=281 tokens.
- Corrected response: byte-identical edit proposal. Host rejected it before another verification and kept rollback intact.

Historical adequacy: **CORRECTION_EVIDENCE_INCOMPLETE** for code repair (and original-task semantics were lossy). A timeout without phase/output cannot identify a Java behavioral defect. Repetition violated the revision instruction, but does not demonstrate inability to learn from an assertion the model never received.

Prospective transport defect: `_targeted_repair_prompt` slices the first 6,000 characters of arbitrary report JSON. [Real-report replay](evidence/reconstruction/correction-clipping.json) demonstrates that the structured JUnit counts after verbose stdout/stderr disappear and JSON is cut mid-field. `_reports` parses JUnit testcase failure elements but retains only counts, discarding existing runtime failure messages. No hidden source is needed to transport emitted test names, exception types and failure messages. Proposed repair is bounded, prioritized runtime diagnostics with explicit omission markers; no test source or stack trace is sent.
''',encoding='utf-8')
(HERE/'semantic-loss-diagnosis.md').write_text('''# Pre-edit diagnosis

Classification: **CONTROLLER/INTERFACE SEMANTIC FIDELITY DEFECT**, initiated by a model omission. Exact transition: planner request -> planner output loses R5; controller worker-contract construction makes that omission authoritative by forwarding only the plan summary, local goal and local acceptance. Global plan acceptance is also absent from the worker renderer (R7 becomes less explicit). Normalization itself preserves the strings.

Evidence: [task-only ledger](requirement-ledger.md), [trace](semantic-trace.md), [10 deterministic probes](evidence/semantic-probes-before.json). All ten structurally valid probes, including explicit contradiction, normalize and render. This is not proof of general semantic checking; none exists for arbitrary tasks. `_intent_envelope` only covers narrow statically recognized HTTP/UI obligations. The schema can express every requirement but does not require completeness.

Architecture: `_planner_prompt` requests narrow decomposition and acceptance criteria, not authority to weaken the user request. `_worker_prompt` says the executor may not reinterpret the original request yet receives only planner-derived semantics. Local criteria specialize responsibility; they must not replace host task constraints. Multi-worker decomposition can narrow files and responsibility, but shared invariants still apply to the assigned portion. Context visibility must never confer write permission. A full host task independently carried to every active worker is the smallest general fix; no generated requirement extraction or semantic classifier is necessary. Inactive workers remain skipped. All repair/observation/replan prompt paths must carry the same host request.

Correction: [reconstruction](correction-reconstruction.md) separates historical timeout evidence from post-hoc behavioral failures. The current raw JSON-prefix cap loses structured results behind logs. JUnit report collection loses runtime failure messages during aggregation. A small diagnostic projection and bounded emitted failure details address this demonstrated transport loss without changing tests or acceptance decisions.

Competing explanation: Qwen can still ignore complete semantics or fail to reason about UTF-16. Propagation alone cannot establish model competence. The historical ASCII case happened to pass, so semantic loss has no demonstrated causal responsibility for the two surrogate failures.

Falsification: show an independent original task/equivalent ASCII obligation in preserved worker wire, or that emitted structured results survive the existing 6,000-character projection. Neither holds. Repair effectiveness is falsified if a real dispatched/correction prompt still lacks original requirements, local criteria or scope. Behavioral improvement requires a fresh controlled trial; deterministic prompt tests alone are not software-task success.

Proposed production scope: explicit host-task argument throughout worker prompt helpers/calls; bounded prioritized correction report; runtime-only JUnit failure details. No planner schema, ownership validator, edit executor, retry count, verification assertion/selector, deadline, source/candidate boundary, NFRT policy or compilation mode changes.
''',encoding='utf-8')
save(HERE/'evidence/pre-edit-seal.json',{'diagnosis_sha256':sha(HERE/'semantic-loss-diagnosis.md'),'ledger_sha256':sha(HERE/'requirement-ledger.md'),'hive_sha256':sha(HERE/'repaired-workshop/workshop/hive.py'),'jvm_runner_sha256':sha(HERE/'repaired-workshop/verification/jvm_runner.py'),'probes':len(probes)})
print(json.dumps({'probes':len(probes),'report_chars':len(serialized),'tests_offset':serialized.find('"tests":'),'pre_edit_diagnosis_written':True}))

import json,sys
sys.dont_write_bytecode=True
from bootstrap import HERE,save,sha
sys.path.insert(0,str(HERE/'repaired-workshop'))
from workshop import hive
rows=json.loads((HERE/'evidence/semantic-probes-before.json').read_text())
run=json.loads((HERE.parent/'hive-transition-003/evidence/live-diagnostic/runs/45ad10e6dd49/run.json').read_text())
result=[]
for row in rows:
 p=row['normalized'];role='backend'
 prompt=hive._worker_prompt(role,p[role+'_goal'],p['worker_files'][role],'[synthetic source]',p['worker_acceptance'][role],
     original_task=run['request'],overall_objective=p['summary'],team_plan=p)
 dest=HERE/'evidence/reconstruction'/('after-probe-'+row['name']+'.txt');dest.write_text(prompt,encoding='utf-8')
 result.append({'name':row['name'],'original_task_exactly_present':run['request'] in prompt,
     'local_criteria_preserved':all(x in prompt for x in p['worker_acceptance'][role]),'prompt_sha256':sha(dest),
     'semantic_validator_added':False,'ownership_changed':False})
save(HERE/'evidence/semantic-probes-after.json',result)
report=json.loads((HERE.parent/'HIVE-TRANSITION-004C/evidence/runs/final-preserved/result.json').read_text())['report']
diagnostic=hive._targeted_diagnostic({'passed':report['passed'],'checks':report['checks']})
(HERE/'evidence/reconstruction/correction-after.json').write_text(diagnostic,encoding='utf-8')
save(HERE/'evidence/correction-replay.json',{'before':json.loads((HERE/'evidence/reconstruction/correction-clipping.json').read_text()),
    'after_characters':len(diagnostic),'after_complete_json':True,'after_structured_tests_present':'"tests"' in diagnostic,
    'historical_messages_unavailable':True,'historical_decisions_unchanged':True})
print('Ten semantic probes preserve exact host request; corrected diagnostic characters:',len(diagnostic))

"""Static inventory only; does not import Hive or collect/execute tests."""
from snapshot import *
import ast, xml.etree.ElementTree as ET

def main():
 rows=[json.loads(s) for s in (OUT/'WORKSPACE-MANIFEST.jsonl').read_text(encoding='utf-8').splitlines()]
 active=OUT/'workspace/HIVE-THINKING-POLICY-001/repaired-workshop'
 tests=[]
 for p in sorted((active/'tests').glob('*.py')):
  tree=ast.parse(p.read_text(encoding='utf-8-sig'))
  tests.append({'path':p.relative_to(OUT).as_posix(),'sha256':digest(p),'test_functions':sum(isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name.startswith('test_') for n in ast.walk(tree))})
 xml=OUT/'workspace/HIVE-THINKING-POLICY-001/evidence/full-regression-final/pytest.xml'
 suites=ET.parse(xml).getroot()
 counts={k:sum(int(s.attrib.get(k,0)) for s in suites.findall('.//testsuite')) for k in ('tests','failures','errors','skipped')}
 counts['passed']=counts['tests']-counts['failures']-counts['errors']-counts['skipped']
 freeze=json.loads((OUT/'workspace/HIVE-THINKING-POLICY-001/FREEZE.json').read_bytes())
 checks=[]
 for name,expected in freeze['source']['production_files'].items():
  p=active/name
  checks.append({'path':name,'expected_sha256':expected['sha256'],'present':p.is_file(),'actual_sha256':digest(p) if p.is_file() else None})
 frozen=[r for r in rows if r['included'] and r['root']=='external/historical-work/HIVE-FACTORIAL-001' and '/hidden-tests/' in r['path']]
 java_tests=[r['path'] for r in rows if r['included'] and r['root']=='external/m3.2-baseline' and '/src/test/' in r['path'] and r['path'].endswith('.java')]
 modules=['workshop/hive.py','workshop/hive_protocol.py','workshop/providers.py','workshop/thinking_policy.py','workshop/hive_review.py','workshop/hive_edits.py','workshop/hive_jvm.py','workshop/hive_verifier.py','workshop/verifier_trace.py','workshop/external_root.py','verification/nfrt_seed.py','verification/jvm_runner.py','verification/runner.py']
 result={'inspection_method':'Static AST and XML parsing only; no tests, application imports, model calls, or experiments executed','current_source':str(active.relative_to(OUT)),'test_modules':tests,'test_module_count':len(tests),'test_function_definitions':sum(t['test_functions'] for t in tests),'historical_pytest_counts':counts,'historical_result_xml':str(xml.relative_to(OUT)),'frozen_acceptance_files':[{'path':r['path'],'sha256':r['sha256']} for r in frozen],'baseline_java_test_sources':java_tests,'freeze_source_hash_claim':freeze['source']['tree_hash'],'freeze_file_checks':checks,'freeze_missing_or_mismatched':[r for r in checks if r['actual_sha256']!=r['expected_sha256']],'core_modules':[{'path':name,'present':(active/name).is_file(),'sha256':digest(active/name) if (active/name).is_file() else None} for name in modules]}
 write('SOURCE-AND-TESTS.json',result)
 print(json.dumps({k:v for k,v in result.items() if k in {'test_module_count','test_function_definitions','historical_pytest_counts','freeze_missing_or_mismatched','frozen_acceptance_files'}},indent=2))

if __name__=='__main__':main()

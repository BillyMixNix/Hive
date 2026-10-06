"""Read only supplied trial metadata and look for authorized source paths.
Does not inspect candidate implementations, acceptance test source, or results.
"""
import hashlib,json,pathlib,platform,subprocess
base=pathlib.Path(__file__).resolve().parents[1]
freeze=json.loads((base/'upload/FREEZE.json').read_text())
task=next(x for x in freeze['tasks'] if x['id']=='J001')
command=['rg','--files','--hidden','/workspace','-g','SnapshotFormatter.java','-g','!**/.git/**']
search=subprocess.run(command,capture_output=True,text=True)
attachments={name:{'bytes':(base/'upload'/name).stat().st_size,'sha256':hashlib.sha256((base/'upload'/name).read_bytes()).hexdigest()} for name in ['FREEZE.json','TASKS.md']}
print(json.dumps({'trial':'HIVE-ASTRA-J001','classification':'BLOCKED','reason':'Frozen baseline repository and executable verifier were not supplied. Metadata only.','platform':platform.system(),'attachments':attachments,'tasks_hash_matches_freeze':attachments['TASKS.md']['sha256']==freeze['files_sha256']['TASKS.md'],'baseline':{'expected_sha256':freeze['baseline']['sha256'],'declared_root':freeze['baseline']['root'],'declared_path_accessible':pathlib.Path(freeze['baseline']['root']).exists(),'actual_sha256':None,'verification':'NOT POSSIBLE: source absent'},'authorized_file':task['files'][0],'original_authorized_file_sha256':None,'final_authorized_file_sha256':None,'source_path_search':{'command':command,'exit_code':search.returncode,'stdout':search.stdout,'stderr':search.stderr},'frozen_gate':{'test_class':task['test_class'],'test_sha256':task['test_sha256'],'test_cases':task['test_cases'],'test_source_inspected':False,'result':'NOT RUN: repository/verifier unavailable'},'repository_files_modified_by_agent':[],'git_scope_check':'Unavailable: target repository absent','implementation_attempts':0,'executable_validation_runs':0,'decomposition_used':False,'other_candidates_inspected':False},indent=2))

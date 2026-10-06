"""Known-failing archived candidate for qualification only, never a model input."""
from qcommon import *
def fixtures():
    task=FREEZE['tasks'][0]
    preserved=ROOT/'HIVE-TRANSITION-004/evidence/transition-003/applied-stage/first-applied-SnapshotFormatter.java'
    assert sha(preserved)=='a3219f4e0b65847123f6cebc150dbe1a026690bf9887062c25c2941747fef242'
    base=Path(FREEZE['baseline']['root'])/task['files'][0]
    plan={'summary':task['request'],'ui_goal':'no change needed','backend_goal':task['request'],'tests_goal':'no change needed',
        'worker_files':{'ui':[],'backend':task['files'],'tests':[]},'interface_contracts':[],'provider_changes':[],
        'acceptance':[task['request']],'worker_acceptance':{'ui':[],'backend':[task['request']],'tests':[]}}
    worker={'status':'implemented','summary':'Replay of an archived failing fixture for harness qualification only.',
        'edits':[{'path':task['files'][0],'operation':'replace','find':base.read_text(encoding='utf-8'),'replace':preserved.read_text(encoding='utf-8')}],'risks':[]}
    review={'approve':False,'summary':'Scripted qualification review; no promotion authorization.','issues':['Qualification fixture only.'],'confidence':1.0}
    return task,plan,worker,review

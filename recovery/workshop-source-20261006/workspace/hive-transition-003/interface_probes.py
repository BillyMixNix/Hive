"""Deterministic probes of untouched T002 semantics. Never supplies live answers."""
import asyncio,copy,itertools,json,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.dont_write_bytecode=True
sys.path.insert(0,str(HERE/'tooling/python'))
sys.path.insert(0,str(HERE/'repaired-workshop'))
from jsonschema import Draft202012Validator
from workshop import hive,external_root,hive_context
from setup_study import save
P='src/main/java/dev/atmcompanion/state/SnapshotFormatter.java'
TEST='src/test/java/example/ConsumerTest.java'
OTHER='src/main/java/example/Support.java'
ROLES=('ui','backend','tests')

def plan():
    return {'summary':'Preserve complete surrogate pairs in bounded lines',
      'ui_goal':'no change needed','backend_goal':'Modify SnapshotFormatter.boundLine within the requested behavior constraints',
      'tests_goal':'no change needed','worker_files':{'ui':[],'backend':[P],'tests':[]},
      'acceptance':['Preserve surrogate pairs, sanitization, ellipsis, ASCII behavior, and the maximum line bound'],
      'worker_acceptance':{'ui':[],'backend':['Implement the requested bounded-line behavior in the authorized file'],'tests':[]},
      'interface_contracts':[]}

def active(p,role,paths,goal='Implement assigned work'):
    p[role+'_goal']=goal;p['worker_files'][role]=paths;p['worker_acceptance'][role]=['Assigned behavior is implemented']

def inactive(p,role):
    p[role+'_goal']='no change needed';p['worker_files'][role]=[];p['worker_acceptance'][role]=[]

def contract(p):
    p['interface_contracts']=[{'name':'bounded_line','owner':'backend','consumer_roles':['tests'],
       'contract':'Consumer tests inspect the bounded-line API supplied by backend'}]

def contexts(scope):
    return [(hive._HOST_WRITE_SCOPE,hive._HOST_WRITE_SCOPE.set(tuple(scope))),
      (hive._ACTIVE_AGENT_SCOPES,hive._ACTIVE_AGENT_SCOPES.set(hive.EXTERNAL_AGENT_SCOPES)),
      (hive._EXTERNAL_ROOT_MODE,hive._EXTERNAL_ROOT_MODE.set(True))]

def reset(tokens):
    for var,token in reversed(tokens):var.reset(token)

def inspect(label,p,scope):
    tokens=contexts(scope)
    try:
        schema=hive._planner_response_schema();Draft202012Validator.check_schema(schema)
        errors=[e.message for e in Draft202012Validator(schema).iter_errors(p)]
        row={'id':label,'plan':p,'host_scope':scope,'schema_valid':not errors,'schema_errors':errors,
             'claims':{path:[r for r in ROLES if path in p['worker_files'][r]] for path in scope}}
        try:
            normalized,_=hive._normalize_plan(copy.deepcopy(p))
            hive._validate_host_write_scope(normalized)
            hive._validate_intent_coverage(normalized,{'version':1,'requirements':[]})
            row.update(accepted=True,normalized_plan=normalized,dispatch_eligible=[r for r in ROLES
                if normalized['worker_files'][r] and not hive._no_change_goal(normalized[r+'_goal'])])
        except Exception as exc:
            row.update(accepted=False,normalized_plan=None,error_type=type(exc).__name__,error=str(exc),dispatch_eligible=[])
        return row
    finally:reset(tokens)

async def dispatch_probe(minimal):
    freeze=json.loads((HERE.parent/'HIVE-TRANSITION-002/FREEZE.json').read_text())
    baseline=Path(freeze['baseline']['root'])
    runs=HERE/'evidence/expressibility-runs';runs.mkdir(exist_ok=False)
    run_id='e00300000001'
    descriptor=external_root.prepare_candidate(str(baseline),runs/'external_candidates'/run_id,HERE/'repaired-workshop',runs)
    roles=[]
    async def call(role,prompt):
        roles.append(role)
        if role=='planner':return json.dumps(minimal)
        raise RuntimeError('Deterministic dispatch sentinel: no worker generation or candidate edits authorized in this probe')
    result=await hive.run_build(Path(descriptor['candidate_root']),runs,
        json.loads((HERE/'evidence/transition-002/run.json').read_text())['request'],
        'model-free-interface-probe',call,metadata={'external_root':descriptor},run_id=run_id,
        external_root_mode=True,allowed_write_files=[P])
    save(HERE/'evidence/expressibility-dispatch.json',{'calls':roles,'planner_accepted':result['plan_attempts'][0]['status']=='accepted',
        'worker_reached':'backend' in roles,'status':result['status'],'changed_files':result['changed_files'],
        'verification':result['verification'],'model_calls':0,'run_id':run_id,'note':'Deliberately stopped at worker callback; no software-task success.'})
    assert roles[:2]==['planner','backend']

def main():
    cases=[]
    def add(label,p,scope=None):cases.append(inspect(label,p,scope or [P]))
    p=plan();add('01_single_owner',p)
    p=plan();active(p,'tests',[P],'Add regression tests');contract(p);add('02_duplicate_writers',p)
    p=plan();active(p,'tests',[],'Read application source without editing');contract(p);add('03_active_read_only_role',p)
    p=plan();inactive(p,'tests');add('04_one_active_canonical_inactive',p)
    p=plan();add('05_two_inactive_roles',p)
    p=plan();p['worker_files']['backend']=[OTHER];add('06_unauthorized',p)
    p=plan();active(p,'tests',[P]);add('07_overlap_plus_missing_contract',p)
    p=plan();active(p,'tests',[TEST],'Add regression tests using application source as context');contract(p);add('08_disjoint_multi_role_with_contract',p,[P,TEST])
    p=plan();add('09_single_no_contract_required',p)
    p=plan();p['worker_files']['tests']=[P];add('10_inactive_with_write',p)
    p=plan();active(p,'tests',[TEST]);add('11_disjoint_multi_role_missing_contract',p,[P,TEST])
    p=plan();inactive(p,'backend');add('12_all_inactive',p)
    subsets=[]
    for bits in itertools.product((False,True),repeat=3):
        p=plan()
        for r,bit in zip(ROLES,bits):
            if bit:active(p,r,[P])
            else:inactive(p,r)
        live=[r for r,b in zip(ROLES,bits) if b]
        if len(live)>1:p['interface_contracts']=[{'name':'dependency','owner':live[0],'consumer_roles':live[1:],'contract':'Shared behavior'}]
        subsets.append(inspect('owners:'+','.join(live),p,[P]))
    save(HERE/'evidence/counterfactual-probes-before.json',{'cases':cases,'owner_subsets':subsets})
    save(HERE/'evidence/manual-valid-plan.json',plan())
    t=contexts([P])
    try:save(HERE/'evidence/planner-schema-before.json',hive._planner_response_schema())
    finally:reset(t)
    run=json.loads((HERE/'evidence/transition-002/run.json').read_text())
    save(HERE/'evidence/historical-plans-before.json',[inspect('t002-'+str(a['attempt']),json.loads(a['raw']),[P]) for a in run['plan_attempts']])
    root=HERE/'evidence/read-context-fixture';(root/Path(P).parent).mkdir(parents=True,exist_ok=False)
    (root/P).write_text('class SnapshotFormatter { static int value() { return 1; } }')
    observed=hive_context.observe(root,'read_file_excerpt',{'path':P})
    t=contexts([P,TEST])
    try:
        edit_ok,reason=hive.validate_edit('tests',{'path':P,'operation':'replace','find':'return 1;','replace':'return 2;'},[TEST])
    finally:reset(t)
    save(HERE/'evidence/read-versus-write.json',{'read_result':observed,'read_requires_write_assignment':False,'test_role_edit_allowed':edit_ok,'edit_rejection':reason})
    assert not edit_ok
    asyncio.run(dispatch_probe(plan()))
    print(json.dumps({'cases':[(r['id'],r['schema_valid'],r['accepted']) for r in cases],
      'ownership_subsets_schema_valid':sum(r['schema_valid'] for r in subsets),
      'ownership_subsets_validator_valid':sum(r['accepted'] for r in subsets)},indent=2))

if __name__=='__main__':main()

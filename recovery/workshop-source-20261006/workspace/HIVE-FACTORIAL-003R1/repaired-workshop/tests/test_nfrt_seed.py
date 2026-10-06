import copy,hashlib,json,zipfile
from pathlib import Path
import pytest
from verification import nfrt_seed as seed
from workshop import external_root

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value))
    return seed.digest(path)

@pytest.fixture
def setup_seed(tmp_path,monkeypatch):
    tree=tmp_path/'candidate';tree.mkdir()
    (tree/'build.gradle').write_text('pinned build')
    app=tree/'src/main/java/example/App.java';app.parent.mkdir(parents=True);app.write_text('package example; class App {}')
    test=tree/'src/test/java/example/AppTest.java';test.parent.mkdir(parents=True);test.write_text('package example; class AppTest {}')
    cache=tmp_path/'approved-gradle-caches/abcdef123456';native=cache/seed.PREFIX
    native.mkdir(parents=True)
    key=hashlib.sha1(b'input: dependency').hexdigest();stem='dependency_'+key
    write(native/(stem+'.txt'),{'type':'dependency','hashValue':key,'components':{'input':{'value':'dependency'}}})
    with zipfile.ZipFile(native/(stem+'_output.jar'),'w') as jar:jar.writestr('dependency/Runtime.class',b'dependency bytes')
    module=cache/'caches/modules-2/files-2.1/tool.jar';module.parent.mkdir(parents=True);module.write_bytes(b'tool')
    rows=[{'path':p.relative_to(cache).as_posix(),'size':p.stat().st_size,'sha256':seed.digest(p)} for p in cache.rglob('*') if p.is_file()]
    proof=cache/'.hive-priming-provenance'/cache.name
    invhash=write(proof/'artifacts.manifest.json',{'artifacts':rows})
    provhash=write(proof/'provenance.json',{'candidate_sha256':'baseline','cache_priming_succeeded':True,'artifact_manifest_sha256':invhash})
    entries=[{**r,'path':Path(r['path']).name} for r in rows if r['path'].startswith(seed.PREFIX)]
    doc={'schema':'hive-nfrt-seed-v1','kind':'dependency-intermediates','entries':entries,'forbidden_packages':['example/'],
        'identity':{'baseline_sha256':'baseline','image_id':'image','jvm_profile':{'version':'9'},
            'downloaded_manifest_sha256':'downloaded','artifacts.manifest.json':invhash,'provenance.json':provhash},
        'source_inventory':[{'path':r.as_posix(),'sha256':seed.digest(p)} for p,r,_ in external_root._inventory(tree)],
        'independent_java_sources':['src/main/java/example/App.java'],
        'reconstruction_inputs':{'inputProperties':{'dependency':'immutable'},'inputFiles':['tool.jar']}}
    manifest=tmp_path/'attestation.json'
    expected=write(manifest,doc)
    monkeypatch.setenv('HIVE_NFRT_SEED_MANIFEST',str(manifest));monkeypatch.setenv('HIVE_NFRT_SEED_SHA256',expected)
    def call(**changes):
        args=dict(tree=tree,cache=cache,profile={'version':'9'},baseline_sha256='baseline',image_id='image',downloaded_manifest_sha256='downloaded')
        args.update(changes);return seed.configured_seed(**args)
    return locals()

def test_valid_attested_private_copy_and_shared_mutation_prevention(setup_seed,tmp_path):
    s=setup_seed;assert s['call']()
    original={p.name:p.read_bytes() for p in s['native'].iterdir()}
    private=tmp_path/'private/intermediate_results'
    result=seed.private_copy(s['native'],private,s['manifest'],s['expected'])
    assert result['private_copy'] and result['files']==2
    (private/next(iter(original))).write_bytes(b'NFRT private update')
    assert {p.name:p.read_bytes() for p in s['native'].iterdir()}==original
    with pytest.raises(ValueError,match='fresh'):seed.private_copy(s['native'],private,s['manifest'],s['expected'])

@pytest.mark.parametrize('mutation',['corrupt','missing','extra','incorrect_hash'])
def test_invalid_seed_is_fail_closed(setup_seed,mutation,monkeypatch):
    s=setup_seed;p=next(s['native'].glob('*.jar'))
    if mutation=='corrupt':p.write_bytes(b'corrupted')
    if mutation=='missing':p.unlink()
    if mutation=='extra':(s['native']/'extra.txt').write_text('extra')
    if mutation=='incorrect_hash':
        s['doc']['entries'][0]['sha256']='0'*64
        monkeypatch.setenv('HIVE_NFRT_SEED_SHA256',write(s['manifest'],s['doc']))
    with pytest.raises(ValueError):s['call']()

@pytest.mark.parametrize('field,value',[('image_id','other-image'),('baseline_sha256','other-baseline'),('profile',{'version':'other'}),('downloaded_manifest_sha256','other-downloads')])
def test_build_tool_identity_invalidation(setup_seed,field,value):
    with pytest.raises(ValueError,match='identity'):setup_seed['call'](**{field:value})

@pytest.mark.parametrize('mutation',['build','new_source','deleted_source','tool','test'])
def test_incompatible_reconstruction_or_scope_invalidates(setup_seed,mutation):
    s=setup_seed
    if mutation=='build':(s['tree']/'build.gradle').write_text('other configuration')
    if mutation=='new_source':(s['app'].parent/'New.java').write_text('class New{}')
    if mutation=='deleted_source':s['app'].unlink()
    if mutation=='tool':s['module'].write_bytes(b'changed tool')
    if mutation=='test':s['test'].write_text('changed tests')
    with pytest.raises(ValueError):s['call']()

def test_only_attested_source_bytes_may_change(setup_seed):
    s=setup_seed;s['app'].write_text('package example; class App {int changed;}')
    assert s['call']()

@pytest.mark.parametrize('entry',['example/App.class','example/AppTest.class','example/generated/Output.class'])
def test_candidate_classes_and_tests_never_seeded(setup_seed,entry,tmp_path):
    s=setup_seed;p=next(s['native'].glob('*.jar'))
    with zipfile.ZipFile(p,'w') as jar:jar.writestr(entry,b'candidate')
    doc=copy.deepcopy(s['doc'])
    row=next(r for r in doc['entries'] if r['path']==p.name);row.update(size=p.stat().st_size,sha256=seed.digest(p))
    expected=write(s['manifest'],doc)
    with pytest.raises(ValueError,match='candidate'):seed.private_copy(s['native'],tmp_path/'private',s['manifest'],expected)

@pytest.mark.parametrize('name',['App.class','Test.class','TEST-result.xml','result.json','build/output.jar','.gradle/history.bin','candidate.java'])
def test_reports_results_history_and_classes_forbidden_even_if_attested(setup_seed,name):
    s=setup_seed;doc=copy.deepcopy(s['doc']);doc['entries'].append({'path':name,'size':0,'sha256':'0'*64})
    expected=write(s['manifest'],doc)
    with pytest.raises(ValueError):seed.load_attestation(s['manifest'],expected)

def test_no_seed_policy_is_explicit_and_partial_configuration_fails(setup_seed,monkeypatch):
    s=setup_seed;monkeypatch.delenv('HIVE_NFRT_SEED_MANIFEST');monkeypatch.delenv('HIVE_NFRT_SEED_SHA256')
    assert s['call']() is None
    monkeypatch.setenv('HIVE_NFRT_SEED_MANIFEST',str(s['manifest']))
    with pytest.raises(ValueError,match='incomplete'):s['call']()

def test_missing_configured_attestation_cannot_fallback(setup_seed):
    s=setup_seed;s['manifest'].unlink()
    with pytest.raises(OSError):s['call']()

def test_wrong_attestation_pin_or_provenance_is_rejected(setup_seed,monkeypatch):
    s=setup_seed;monkeypatch.setenv('HIVE_NFRT_SEED_SHA256','0'*64)
    with pytest.raises(ValueError,match='attestation'):s['call']()
    monkeypatch.setenv('HIVE_NFRT_SEED_SHA256',s['expected'])
    (s['proof']/'provenance.json').write_text('{}')
    with pytest.raises(ValueError,match='provenance'):s['call']()

def test_private_copy_failure_cleans_up(setup_seed,tmp_path,monkeypatch):
    s=setup_seed;private=tmp_path/'private'
    def fail(*a,**k):raise OSError('copy failed')
    monkeypatch.setattr(seed.shutil,'copyfileobj',fail)
    with pytest.raises(OSError):seed.private_copy(s['native'],private,s['manifest'],s['expected'])
    assert not private.exists()
    assert seed.verify_seed(s['native'],s['doc'])==2

def test_production_seed_mounts_are_readonly_and_payload_is_pinned(tmp_path,monkeypatch,setup_seed):
    import test_hive_jvm_profile as fixtures
    from workshop import hive_jvm,hive_verifier
    root,_,specs=fixtures._project(tmp_path)
    profile=fixtures._neoform_profile(root)
    cache,_,_,baseline,image=fixtures._neoform_approved_cache(tmp_path,profile)
    frozen=hive_jvm.store_frozen_junit_tests(specs,tmp_path/'hive_runs/123456789abc')
    s=setup_seed
    monkeypatch.setenv('GRADLE_USER_HOME',str(cache))
    monkeypatch.setattr(seed,'configured_seed',lambda *a,**k:{'source':s['native'],'manifest':s['manifest'],'sha256':s['expected'],'document':s['doc']})
    commands=[]
    from subprocess import CompletedProcess
    def run(argv,**kw):
        commands.append(argv)
        return CompletedProcess(argv,0,image+'\n' if argv[1:3]==['image','inspect'] else json.dumps({'passed':True,'checks':[]}),'')
    monkeypatch.setattr(hive_verifier.shutil,'which',lambda _: 'docker')
    monkeypatch.setattr(hive_verifier.subprocess,'run',run)
    result=hive_verifier.run_isolated(root,'targeted',timeout=240,external_root=True,frozen_junit_tests=frozen,
         expected_jvm_profile=profile,expected_external_baseline_sha256=baseline)
    assert result['passed'],result
    command=next(c for c in commands if c[1]=='run')
    mounts=[command[i+1] for i,v in enumerate(command) if v=='--mount']
    assert len(mounts)==10 and all(m.endswith(',readonly') for m in mounts)
    assert any('target=/approved-nfrt-intermediates,readonly' in m for m in mounts)
    payload=json.loads(command[-1]);assert payload['nfrt_seed_sha256']==s['expected']
    assert payload['targeted_timeout']==240 and payload['frozen_tests'][0]['sha256']==specs[0]['sha256']

"""Source-class authorization, with no benchmark identifiers in policy predicates."""
import copy,zipfile
import pytest
from verification import nfrt_seed as seed
from test_nfrt_seed import setup_seed,write

@pytest.fixture
def reviewed(setup_seed,monkeypatch):
    s=setup_seed;doc=s['doc'];doc['schema']='hive-nfrt-seed-v2';del doc['independent_java_sources']
    doc['independent_source_policy']={'kind':'reviewed-main-java-v1','roots':['src/main/java'],
        'review_sha256':'a'*64,'dependency_model_sha256':'b'*64}
    doc['reconstruction_inputs']={'project':'$PROJECT','taskClass':'net.neoforged.nfrtgradle.CreateMinecraftArtifacts_Decorated',
        'graph':[{'path':':createMinecraftArtifacts','dependencies':[]}],
        'inputProperties':{'dependency':'immutable'},'inputFiles':[{'path':'/approved/tool.jar','sha256':'c'*64}],
        'javaSourceSets':[{'name':'main','javaRoots':['$PROJECT/src/main/java']}],
        'optionalInputs':{'accessTransformers':[],'validatedAccessTransformers':[],'interfaceInjection':[],'parchment':[]}}
    def pin():
        s['expected']=write(s['manifest'],doc);monkeypatch.setenv('HIVE_NFRT_SEED_SHA256',s['expected'])
    s['pin']=pin;pin();assert s['call']();return s

@pytest.mark.parametrize('mutation',['existing','unrelated','multiple','new_package','removed','invalid_java'])
def test_reviewed_main_source_variation_is_compatible(reviewed,mutation):
    s=reviewed
    if mutation in ('existing','multiple'):s['app'].write_text('package example; class App { int changed; }')
    if mutation in ('unrelated','multiple','new_package'):
        p=s['tree']/'src/main/java/other/packagepath/New.java';p.parent.mkdir(parents=True);p.write_text('package other.packagepath; class New {}')
    if mutation=='removed':s['app'].unlink()
    if mutation=='invalid_java':s['app'].write_text('not valid Java; compilation still required')
    assert s['call']()

@pytest.mark.parametrize('path',[
    'build.gradle','gradle.properties','settings.gradle','gradle/libs.versions.toml',
    'src/main/resources/META-INF/accesstransformer.cfg','src/main/resources/META-INF/interface-injection.json',
    'mappings/official.tsrg','parchment/data.zip','src/main/resources/assets/ordinary.json',
    'src/test/java/example/AppTest.java','src/gametest/java/New.java','buildSrc/src/main/java/Plugin.java',
    'src/main/java/config.json','src/main/java/build.gradle','src/main/java-other/New.java'])
def test_nonqualifying_source_config_and_unknown_inputs_fail_closed(reviewed,path):
    p=reviewed['tree']/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('changed input')
    with pytest.raises(ValueError,match='NFRT (source inventory|reconstruction input) changed'):reviewed['call']()

@pytest.mark.parametrize('identity',['NeoForge','ModDevGradle','NFRT','Java','Gradle','mappings','dependency'])
def test_attested_tool_and_artifact_identity_cannot_change(reviewed,identity):
    # Module/download inventories bind actual bytes, regardless of displayed version.
    reviewed['module'].write_bytes(('different '+identity+' bytes').encode())
    with pytest.raises(ValueError,match='tool/dependency hash mismatch'):reviewed['call']()

@pytest.mark.parametrize('field,value',[
    ('image_id','different-Java-image'),('profile',{'version':'9','neoForge':'changed'}),
    ('profile',{'version':'9','modDevGradle':'changed'}),('profile',{'version':'9','neoformRuntime':'changed'}),
    ('downloaded_manifest_sha256','different-downloads')])
def test_profile_image_and_download_identity_rejected(reviewed,field,value):
    with pytest.raises(ValueError,match='identity mismatch'):reviewed['call'](**{field:value})

@pytest.mark.parametrize('section',['inputFiles','inputProperties','optionalInputs'])
def test_java_named_reconstruction_input_is_not_independent(reviewed,section):
    s=reviewed;file={'path':'$PROJECT/src/main/java/example/App.java','sha256':'c'*64}
    m=s['doc']['reconstruction_inputs']
    if section=='inputFiles':m[section].append(file)
    elif section=='inputProperties':m[section]['data']=file
    else:m[section]['accessTransformers']=[file]
    s['pin']()
    with pytest.raises(ValueError,match='overlaps independent source root'):s['call']()

@pytest.mark.parametrize('mutation',['no_review','no_model','wrong_root','unsafe_root','empty_roots','duplicate_root','mixed_policy',
    'compilation_prerequisite','no_optional_inputs','wrong_task','wrong_project','no_main'])
def test_missing_or_contradictory_independence_evidence_rejected(reviewed,mutation):
    s=reviewed;p=s['doc']['independent_source_policy'];m=s['doc']['reconstruction_inputs']
    if mutation=='no_review':p.pop('review_sha256')
    if mutation=='no_model':p.pop('dependency_model_sha256')
    if mutation=='wrong_root':p['roots']=['src/test/java']
    if mutation=='unsafe_root':p['roots']=['src/../buildSrc']
    if mutation=='empty_roots':p['roots']=[]
    if mutation=='duplicate_root':p['roots']*=2
    if mutation=='mixed_policy':s['doc']['independent_java_sources']=['src/main/java/example/App.java']
    if mutation=='compilation_prerequisite':m['graph'][0]['dependencies']=[':compileJava']
    if mutation=='no_optional_inputs':m.pop('optionalInputs')
    if mutation=='wrong_task':m['taskClass']='other.Task'
    if mutation=='wrong_project':m['project']='/unreviewed'
    if mutation=='no_main':m['javaSourceSets']=[]
    s['pin']()
    with pytest.raises(ValueError):s['call']()

@pytest.mark.parametrize('mutation',['corrupt','missing','extra','wrong_attestation'])
def test_v2_seed_integrity_still_required(reviewed,monkeypatch,mutation):
    s=reviewed;p=next(s['native'].glob('*.jar'))
    if mutation=='corrupt':p.write_bytes(b'bad')
    if mutation=='missing':p.unlink()
    if mutation=='extra':(s['native']/'unmanifested.txt').write_text('extra')
    if mutation=='wrong_attestation':monkeypatch.setenv('HIVE_NFRT_SEED_SHA256','0'*64)
    with pytest.raises(ValueError):s['call']()

@pytest.mark.parametrize('entry',['example/App.class','example/AppTest.class','example/generated/Output.class'])
def test_v2_rejects_candidate_classes_even_in_rehashed_seed(reviewed,tmp_path,entry):
    s=reviewed;p=next(s['native'].glob('*.jar'))
    with zipfile.ZipFile(p,'w') as z:z.writestr(entry,b'candidate output')
    row=next(r for r in s['doc']['entries'] if r['path']==p.name);row.update(size=p.stat().st_size,sha256=seed.digest(p));s['pin']()
    with pytest.raises(ValueError,match='candidate'):seed.private_copy(s['native'],tmp_path/'private',s['manifest'],s['expected'])

@pytest.mark.parametrize('entry',['build/classes/App.class','build/tests/Test.class','TEST-output.xml','result.json','.gradle/history.bin','candidate.java'])
def test_v2_cannot_seed_build_outputs_reports_or_history(reviewed,entry):
    s=reviewed;s['doc']['entries'].append({'path':entry,'size':0,'sha256':'0'*64});s['pin']()
    with pytest.raises(ValueError):seed.load_attestation(s['manifest'],s['expected'])

def test_v2_private_copy_keeps_approved_seed_immutable(reviewed,tmp_path):
    s=reviewed;before={p.name:p.read_bytes() for p in s['native'].iterdir()}
    dst=tmp_path/'private';assert seed.private_copy(s['native'],dst,s['manifest'],s['expected'])['private_copy']
    next(dst.glob('*.jar')).write_bytes(b'private runtime update')
    assert before=={p.name:p.read_bytes() for p in s['native'].iterdir()}

def test_v1_cannot_silently_acquire_v2_policy(setup_seed,monkeypatch):
    s=setup_seed;s['doc']['independent_source_policy']={'kind':'reviewed-main-java-v1','roots':['src/main/java']}
    monkeypatch.setenv('HIVE_NFRT_SEED_SHA256',write(s['manifest'],s['doc']))
    with pytest.raises(ValueError,match='ambiguous'):s['call']()

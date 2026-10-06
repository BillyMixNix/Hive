"""Recompute all ten native keys and bind their input/output/tool bytes."""
import re,zipfile
from common import *

def main():
    doc=read(FREEZE['nfrt']['manifest']);native=CACHE/nfrt_seed.PREFIX
    assert nfrt_seed.verify_seed(native,doc)==22
    nodes=[]
    actions={'stripClient':'SplitResourcesFromClassesAction','stripServer':'SplitResourcesFromClassesAction',
        'copyUnpatchedClasses':'CopyUnpatchedClassesAction','binaryWithNeoForge':'InjectZipContentAction',
        'applyDevTransforms':'ApplyDevTransformsAction'}
    for p in sorted(native.glob('*.txt')):
        if not re.fullmatch(r'[A-Za-z]+_[0-9a-f]{40}\.txt',p.name):continue
        key=read(p);material='\n'.join(f"{k}: {v['value']}" for k,v in sorted(key['components'].items()))
        assert hashlib.sha1(material.encode()).hexdigest()==key['hashValue']
        deps=[];inputs=[]
        for name,value in key['components'].items():
            annotation=value.get('annotation','');m=re.search(r'/approved-gradle-cache/(\S+)',annotation)
            row={'component':name,**value}
            if m:
                local=CACHE/m.group(1);assert local.is_file(),local
                row.update(host_file=str(local),file_sha256=sha(local),file_bytes=local.stat().st_size)
                if 'data[' in name or 'dependency[' in name or name.startswith('injectSource'):
                    with zipfile.ZipFile(local) as z:
                        if name=='data dependency[mappings]':selected=json.loads(z.read('config.json'))['data']['mappings']
                        elif name=='data dependency[patch]':selected=json.loads(z.read('config.json'))['binpatches']
                        elif name=='access transformers data[neoForgeAccessTransformers]':selected=json.loads(z.read('config.json'))['ats']
                        elif name=='injectSource[0].cache-key':selected=''
                        else:raise AssertionError(('Unmodeled archive component',name))
                        entries={n:hashlib.sha1(z.read(n)).hexdigest() for n in z.namelist() if not n.endswith('/') and (not selected or n==selected or n.startswith(selected))}
                        computed=hashlib.sha1('\n'.join(f'{n}: {v}' for n,v in sorted(entries.items())).encode()).hexdigest()
                        row.update(archive_selection=selected,selected_entries=len(entries),component_hash_method='NFRT ZipContentHasher sorted entry content hashes')
                else:
                    with local.open('rb') as stream:computed=hashlib.file_digest(stream,'sha1').hexdigest()
                    row['component_hash_method']='whole-file SHA1'
                assert computed==value['value'],(key['type'],name,computed,value['value'])
                row.update(component_content_hash_recomputed=computed,component_content_matches=True)
                if '/intermediate_results/' in str(local).replace('\\','/'):
                    deps.append(local.name.split('_')[0])
                inputs.append(row)
        for name,value in key['components'].items():
            if name.startswith('external tool classpath'):
                parts=value['value'].split(':')
                if len(parts)>=3:
                    folder=CACHE/'caches/modules-2/files-2.1'/parts[0]/parts[1]/parts[2]
                    jars=list(folder.rglob('*.jar'))
                    if not jars:
                        folder=CACHE/'caches/neoformruntime/artifacts'/parts[0].replace('.','/')/parts[1]/parts[2]
                        jars=list(folder.rglob('*.jar'))
                    assert jars,value['value']
                    inputs.extend({'component':name,'coordinate':value['value'],'host_file':str(j),'file_sha256':sha(j),'file_bytes':j.stat().st_size} for j in jars)
        outputs=[r for r in doc['entries'] if r['path'].startswith(key['type']+'_'+key['hashValue']+'_')]
        nodes.append({'node':key['type'],'key_sha1':key['hashValue'],'key_file_sha256':sha(p),'components':key['components'],
            'action':actions.get(key['type'],'ExternalJavaToolAction'),'input_files':inputs,'previous_nodes':sorted(set(deps)),
            'outputs':outputs,'project_application_java_participates':False,'project_resources_participate_in_approved_graph':False,
            'build_scripts':'Indirectly configure graph/artifact coordinates/options; host SHA256-bound',
            'access_transformers':'Dependency-bundled AT data in applyDevTransforms; optional project AT can change this node and descendants',
            'interface_injection':'Optional project input changes applyDevTransforms and descendants; absent in approved graph',
            'mappings_parchment':'Official/NeoForm mappings in mergeMappings and rename. Parchment disabled; enabling is outside approved identity',
            'participation':{'application_java':'absent','project_resources':'absent in approved graph',
                'build_scripts':'indirect graph/configuration determinant',
                'access_transformers':'direct' if key['type']=='applyDevTransforms' else 'transitive' if key['type']=='binaryWithNeoForge' else 'none in approved graph',
                'interface_injection':'optional direct' if key['type']=='applyDevTransforms' else 'optional transitive' if key['type']=='binaryWithNeoForge' else 'none in approved graph',
                'mappings':'direct' if key['type'] in ('mergeMappings','rename') else 'transitive' if key['type'] in ('binaryPatch','copyUnpatchedClasses','applyDevTransforms','binaryWithNeoForge') else 'none in approved graph',
                'parchment':'disabled; any enablement requires new attestation'},
            'key_recomputed':True})
    assert len(nodes)==10
    sources=OUT/'pinned-source'
    model={'versions':{'ModDevGradle':'2.0.147','NFRT':'2.0.31','NeoForge':'21.1.251','Gradle':'9.2.1','Java':'21; exact pinned image'},
        'image_id':FREEZE['verifier']['verifier_image_id'],'seed_files':22,'seed_bytes':sum(r['size'] for r in doc['entries']),
        'nodes':nodes,'actual_reconstruction_inputs':doc['reconstruction_inputs'],
        'source_review':{p.relative_to(sources).as_posix():sha(p) for p in sources.rglob('*.java')},
        'key_limit':'Native content keys are not security attestation. Some tool components are coordinates; the host additionally hashes every approved module/tool byte and binds the image.',
        'model_calls':0}
    save(HERE/'reconstruction-dependency-model.json',model)
    for group,artifact in [('net.neoforged','neoform'),('net.neoforged','neoforge')]:
        for p in (CACHE/'caches/modules-2/files-2.1'/group/artifact).rglob('*'):
            if p.suffix not in ('.zip','.jar'):continue
            with zipfile.ZipFile(p) as z:
                if 'config.json' in z.namelist():
                    save(OUT/'artifact-configs'/(p.stem+'.json'),{'artifact':str(p),'sha256':sha(p),'config':json.loads(z.read('config.json'))})
    table='\n'.join('| '+n['node']+' | '+', '.join(n['previous_nodes'])+' | '+n['action']+' | `'+n['key_sha1']+'` |' for n in nodes)
    (HERE/'reconstruction-dependency-model.md').write_text('''# Pinned reconstruction dependency model

The JSON companion contains every native component (including command arguments), input file SHA-256, output identity and node dependency. All ten key SHA-1 values were independently recomputed. Tool coordinates are additionally bound to host-approved module bytes. Build scripts, Gradle properties, wrapper, verifier image/JDK and downloaded-input manifests remain host-pinned even where NFRT does not put them directly into a node key.

| Node | Previous nodes | Action | Native key |
|---|---|---|---|
'''+table+'''

The base graph comes from the exact NeoForm `config.json`; the NeoForge userdev config adds binary patching and dependency injection. `NeoFormEngine.runNode` collects input components and calls each action's `computeCacheKey`. `CacheKeyBuilder.addPath` hashes bytes; `addDataSource` hashes archive entries under a configured data path; `CacheKey.computeHashValue` hashes the sorted components. An annotation path is explanatory, not part of that key.

Pinned `ModDevArtifactsWorkflow.create` configures reconstruction before `addToSourceSet` adds its outputs to application compile/runtime classpaths. `CreateMinecraftArtifacts.createArtifacts` passes dependency coordinates, selected outputs, AT/II/Parchment files and options. `NeoFormRuntimeTask` supplies artifact-manifest files and the NFRT executable. None of the approved graph's input files or key components contains project Java sources.

This is not a claim that all Java or resources are independent in arbitrary Gradle builds. `DataFileCollections.create` automatically reads `META-INF/accesstransformer.cfg` under main resource roots if it appears. Explicit configuration can select arbitrary paths for transforms or injection, including a `.java`-named file. Such configuration must remain byte-identical, and measured reconstruction input files must not overlap the independently variable class. All resource/config additions remain conservative invalidations unless separately attested.

Parchment is disabled in the approved graph. Official and NeoForm mappings already participate in mergeMappings/rename. Enabling Parchment or changing mapping data cannot reuse this approved identity merely because the old ten filenames remain present. Candidate compilation and test source processing occur downstream; no candidate output is in these 22 dependency intermediates.
''',encoding='utf-8')
    print('Ten node keys independently recomputed; dependency model written.',flush=True)
if __name__=='__main__':main()

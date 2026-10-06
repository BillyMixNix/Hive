"""Fresh source-sensitivity fixtures. Never copies frozen tests into probe projects."""
import zipfile
from common import *

def main():
    assert inventory(SOURCE)==read(OUT/'original-source.json')
    assert external_root.tree_sha256(BASE)==FREEZE['baseline']['sha256']
    inputs=OUT/'sensitivity-inputs';inputs.mkdir(exist_ok=False)
    taskfiles={t['id']:t['files'] for t in FREEZE['tasks']}
    benchmark=set(p for paths in taskfiles.values() for p in paths)
    mains=sorted(p.relative_to(BASE).as_posix() for p in (BASE/'src/main/java').rglob('*.java') if p.relative_to(BASE).as_posix() not in benchmark)
    test=next(p.relative_to(BASE).as_posix() for p in (BASE/'src/test/java').rglob('*.java'))
    cases=[('baseline',[],'unchanged'),('A-main',[mains[0]],'comment'),
        ('B-J001',taskfiles['J001'],'comment'),('C-J002',taskfiles['J002'],'comment'),
        ('D-J003',taskfiles['J003'],'comment'),('E-J004',taskfiles['J004'],'comment'),
        ('F-unrelated',[mains[-1]],'comment'),('G-package-addition',['src/main/java/qualification/independence/Probe.java'],'java_add'),
        ('H-test',[test],'comment'),('I-resource',['src/main/resources/assets/qualification/probe.txt'],'resource'),
        ('J-build-comment',['build.gradle'],'comment'),('J2-binary-option',['build.gradle'],'binary_option'),
        ('K-property',['gradle.properties'],'property'),('L-access-transformer',['src/main/resources/META-INF/accesstransformer.cfg'],'at'),
        ('M-interface-injection',['build.gradle','diagnostic/interface-injection.json'],'ii'),
        ('N-parchment',['build.gradle','diagnostic/parchment.zip'],'parchment'),
        ('O-dependency',['build.gradle'],'dependency'),('P-neoforge',['gradle.properties'],'neoforge')]
    rows=[]
    for name,paths,kind in cases:
        target=inputs/name;external_root.copy_candidate_tree(BASE,target,inputs)
        def append(p,s):
            dest=target/p;dest.parent.mkdir(parents=True,exist_ok=True)
            with dest.open('a',encoding='utf-8',newline='') as f:f.write(s)
        if kind=='comment':
            for p in paths:append(p,'\n// NFRT source-sensitivity probe: no behavior change.\n')
        elif kind=='java_add':append(paths[0],'package qualification.independence; final class Probe {}\n')
        elif kind=='resource':append(paths[0],'Harmless diagnostic application resource.\n')
        elif kind=='binary_option':append('build.gradle',"\ntasks.named('createMinecraftArtifacts') { includeResourcesInGameJar = true }\n")
        elif kind=='property':append('gradle.properties','\norg.gradle.workers.max=1\n')
        elif kind=='at':append(paths[0],'# Controlled access transformer input\npublic net.minecraft.world.entity.Entity\n')
        elif kind=='ii':
            append('diagnostic/interface-injection.json','{}\n')
            append('build.gradle',"\ntasks.named('createMinecraftArtifacts') { interfaceInjectionData.from(file('diagnostic/interface-injection.json')) }\n")
        elif kind=='parchment':
            (target/'diagnostic').mkdir()
            with zipfile.ZipFile(target/'diagnostic/parchment.zip','w') as z:z.writestr('parchment.json','{"version":"1.1.0","packages":[],"classes":[]}')
            append('build.gradle',"\ntasks.named('createMinecraftArtifacts') { parchmentEnabled = true; parchmentData.setFrom(file('diagnostic/parchment.zip')) }\n")
        elif kind=='dependency':append('build.gradle',"\ndependencies { compileOnly('com.google.code.gson:gson:2.10.1') }\n")
        elif kind=='neoforge':append('gradle.properties','\nneo_version=21.1.252\n')
        row={'case':name,'kind':kind,'paths':paths,'candidate_sha256':external_root.tree_sha256(target),'diagnostic_only':True}
        try:attest(target);row['current_policy_compatible']=True
        except Exception as e:row.update(current_policy_compatible=False,current_policy_error={'type':type(e).__name__,'message':str(e)})
        rows.append(row);save(OUT/'sensitivity-fixtures.json',rows)
        print(name,row['current_policy_compatible'],flush=True)
    # Identity-only negative controls are no-runtime attestation probes, not source edits.
    mismatches=[];configure()
    for label,field,value in [('Java-image','image_id','different-image'),('Gradle-profile','profile',{}),('downloaded-artifacts','downloaded_manifest_sha256','0'*64)]:
        args=dict(tree=BASE,cache=CACHE,profile=FREEZE['verifier']['jvm_profile'],baseline_sha256=FREEZE['baseline']['sha256'],image_id=FREEZE['verifier']['verifier_image_id'],downloaded_manifest_sha256=FREEZE['nfrt']['identity']['downloaded_manifest_sha256']);args[field]=value
        try:nfrt_seed.configured_seed(**args);mismatches.append({'case':label,'rejected':False})
        except Exception as e:mismatches.append({'case':label,'rejected':True,'error':str(e)})
    save(OUT/'identity-negative-probes.json',mismatches)
if __name__=='__main__':main()

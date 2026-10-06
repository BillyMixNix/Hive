"""Host creates a new reviewed manifest; approved seed bytes/provenance stay immutable."""
import copy
from common import *

def main():
    seal=read(OUT/'diagnosis-seal.json')
    assert sha(HERE/'diagnosis.md')==seal['diagnosis_sha256']
    assert sha(HERE/'reconstruction-dependency-model.json')==seal['dependency_model_sha256']
    assert sha(OUT/'sensitivity-analysis.json')==seal['sensitivity_analysis_sha256']
    old=read(FREEZE['nfrt']['manifest']);doc=copy.deepcopy(old)
    measured=read(OUT/'normalized-reconstruction-inputs.json')
    main=next(s for s in measured['javaSourceSets'] if s['name']=='main')
    roots=[r.removeprefix('$PROJECT/') for r in main['javaRoots']]
    doc['schema']='hive-nfrt-seed-v2';del doc['independent_java_sources']
    doc['independent_source_policy']={'kind':'reviewed-main-java-v1','roots':roots,
        'review_sha256':seal['diagnosis_sha256'],'dependency_model_sha256':seal['dependency_model_sha256']}
    doc['reconstruction_inputs']=measured
    doc['approval_basis']={'study':'HIVE-NFRT-ATTESTATION-002','previous_attestation_sha256':FREEZE['nfrt']['sha256'],
        'diagnosis_sha256':seal['diagnosis_sha256'],'dependency_model_sha256':seal['dependency_model_sha256'],
        'source_sensitivity_sha256':seal['sensitivity_analysis_sha256'],'pinned_source_inventory_sha256':seal['pinned_source_inventory_sha256']}
    assert all(doc[k]==old[k] for k in ['entries','identity','source_inventory','forbidden_packages'])
    manifest=OUT/'approved-nfrt-seed-v2.json';assert not manifest.exists();save(manifest,doc)
    assert attest(BASE,manifest)
    save(OUT/'attestation-configuration.json',{'at':stamp(),'manifest':str(manifest),'sha256':sha(manifest),
         'identity':doc['identity'],'independent_source_policy':doc['independent_source_policy'],
         'unchanged_seed_identity':True,'model_calls':0})
    print('New manifest validated:',sha(manifest),flush=True)
if __name__=='__main__':main()

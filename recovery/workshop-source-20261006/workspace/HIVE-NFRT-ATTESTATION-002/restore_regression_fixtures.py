"""Copy exact archived regression fixtures; no source or historical evidence mutation."""
import shutil
from common import *
def main():
    prior=ROOT/'HIVE-REVIEWER-POLICY-001/evidence';rows=[]
    for name in ['ordinal-03','planner-input-fixtures','live','ownership-historical-replay.json']:
        source=prior/name;dest=OUT/name;assert source.exists() and not dest.exists()
        if source.is_dir():
            shutil.copytree(source,dest);assert inventory(source)==inventory(dest)
            rows.append({'source':str(source),'destination':str(dest),'files':inventory(dest)})
        else:
            shutil.copyfile(source,dest);assert sha(source)==sha(dest);rows.append({'source':str(source),'destination':str(dest),'sha256':sha(dest)})
    save(OUT/'regression-fixture-provenance.json',rows)
    print('Archived fixtures copied byte-for-byte; previous regression result preserved.',flush=True)
if __name__=='__main__':main()

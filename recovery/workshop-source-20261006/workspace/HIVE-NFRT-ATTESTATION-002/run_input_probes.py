"""Sequential bounded Docker input-only probes; frozen production is untouched."""
import subprocess,time,uuid
from common import *
from workshop.verifier_trace import VerificationTrace

def main():
    cases=[r['case'] for r in read(OUT/'sensitivity-fixtures.json')]
    original=next((ROOT/'HARNESS-QUALIFICATION-001/evidence/controls/A-direct').rglob('invocation.json'))
    base=read(original)['argv'];image=FREEZE['verifier']['verifier_image_id']
    assert subprocess.run([base[0],'image','inspect',base[-3],'--format','{{.Id}}'],capture_output=True,text=True,check=True).stdout.strip()==image
    out=OUT/'input-probes';out.mkdir(exist_ok=False)
    allrows=[]
    for index in range(0,len(cases),3):
        group=cases[index:index+3];name='hive-nfrt-inputs-'+uuid.uuid4().hex[:12]
        cmd=list(base);cmd[cmd.index('--name')+1]=name
        for i,arg in enumerate(cmd):
            if arg.startswith('type=bind,source=') and ',target=/source,readonly' in arg:cmd[i]=f'type=bind,source={OUT/"sensitivity-inputs"},target=/source,readonly'
            elif arg.startswith('type=bind,source=') and ',target=/opt/verifier/jvm_runner.py,readonly' in arg:cmd[i]=f'type=bind,source={SOURCE/"verification/jvm_runner.py"},target=/opt/verifier/jvm_runner.py,readonly'
            elif arg.startswith('HIVE_VERIFICATION_RUN_ID='):cmd[i]=f'HIVE_VERIFICATION_RUN_ID=NFRT-INPUT-{index}'
        cfg=json.loads(cmd[-1]);cfg['probe_cases']=group;cfg['frozen_tests']=[]
        cmd[-2]='/probe/probe_container.py';cmd[-1]=json.dumps(cfg)
        cmd[-3:-3]=['--mount',f'type=bind,source={HERE},target=/probe,readonly','--entrypoint','python3']
        dest=out/f'batch-{index//3+1}';trace=VerificationTrace(OUT/'sensitivity-inputs', 'nfrt-input-diagnostic', dest)
        started=time.monotonic();print('Starting',group,flush=True)
        try:
            cp=trace.capture(cmd,timeout=240,docker=cmd[0],container=name)
            rows=[json.loads(line) for line in cp.stdout.splitlines() if line.startswith('{')]
            assert len(rows)==len(group),(cp.returncode,cp.stdout[-2000:],cp.stderr[-2000:])
            for row in rows:
                lines=row['result'].get('stdout','').splitlines()
                snapshots=[json.loads(line.split(' ',1)[1]) for line in lines if line.startswith('NFRT_INPUT_SNAPSHOT ')]
                row['snapshot']=snapshots[0] if snapshots else None
                save(out/(row['case']+'.json'),row);allrows.append(row)
            save(out/'results.json',allrows)
            save(dest/'batch-result.json',{'returncode':cp.returncode,'seconds':time.monotonic()-started,'cases':group,'diagnostic_only':True})
        finally:
            subprocess.run([cmd[0],'rm','-f',name],capture_output=True,text=True,timeout=15)
        print('Completed',group,flush=True)
if __name__=='__main__':main()

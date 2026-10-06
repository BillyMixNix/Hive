#!/usr/bin/env python3
"""Supplemental execution of unchanged repository JUnit tests and external probes.
This is not the sealed Docker verifier. Uses the host Java17 compiler module.
"""
import argparse,json,os,pathlib,subprocess,sys,time
ROOT=pathlib.Path(__file__).resolve().parent
p=argparse.ArgumentParser();p.add_argument('--repository',type=pathlib.Path,required=True);p.add_argument('--phase',required=True);p.add_argument('--probe',type=pathlib.Path);p.add_argument('--probe-class');a=p.parse_args()
repo=a.repository.resolve();phase=ROOT/a.phase;phase.mkdir(exist_ok=False);classes=phase/'classes';classes.mkdir()
deps=ROOT/'dependencies';cp=os.pathsep.join(str(deps/name) for name in ['gson-2.10.1.jar','junit-platform-console-standalone-1.11.4.jar'])
main=['SnapshotFormatter','GameSnapshot','Observation','Capability','CapabilityStatus']
sources=[str(repo/'src/main/java/dev/atmcompanion/state'/(name+'.java')) for name in main]
sources += [str(repo/'src/test/java/dev/atmcompanion/state'/(name+'.java')) for name in ['SnapshotFormatterTest','SnapshotFixtures']]
if a.probe:sources.append(str(a.probe.resolve()))
commands=[]
def run(name,cmd):
 start=time.monotonic();r=subprocess.run(cmd,cwd=repo,capture_output=True,text=True)
 (phase/(name+'.stdout.log')).write_text(r.stdout);(phase/(name+'.stderr.log')).write_text(r.stderr)
 commands.append({'name':name,'command':cmd,'cwd':str(repo),'exit_code':r.returncode,'seconds':time.monotonic()-start})
 (phase/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
 print(json.dumps({'stage':name,'exit_code':r.returncode}),flush=True)
 return r.returncode
code=run('compile',['java','com.sun.tools.javac.Main','--release','17','-encoding','UTF-8','-cp',cp,'-d',str(classes),*sources])
if code:sys.exit(code)
code=run('existing-junit',['java','-jar',str(deps/'junit-platform-console-standalone-1.11.4.jar'),'execute','--class-path',str(classes)+os.pathsep+str(deps/'gson-2.10.1.jar'),'--select-class','dev.atmcompanion.state.SnapshotFormatterTest','--disable-ansi-colors','--reports-dir',str(phase/'junit-reports'),'--fail-if-no-tests'])
if a.probe:
 if not a.probe_class:raise ValueError('--probe-class is required with --probe')
 code=run('boundary-probes',['java','-cp',str(classes)+os.pathsep+str(deps/'gson-2.10.1.jar'),a.probe_class]) or code
sys.exit(code)

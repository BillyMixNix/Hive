"""Build pinned real-bug fixtures and executed interruption logs, without APIs."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from hive_learning.evaluate import grade
from analysis.state_packet import canonical, digest


def source(repo,sha,path):
    return subprocess.check_output(['git','show',sha+':'+path],cwd=repo,text=True)


def node_for(text,name):
    parts=name.split('.')
    nodes=ast.parse(text).body
    for part in parts:
        node=next(n for n in nodes if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name==part)
        nodes=node.body
    return node


def run_public(files, test):
    # Use the same real pytest evaluator as recipient execution.
    return grade(files, {'test_public.py':test})


def build(boltons, more, output):
    specs=[
        {'id':'unicode_lines','repo':boltons,'upstream':'mahmoud/boltons','pr':475,
         'base':'967864f89791509f9eb36b22b4579d36b72a6df2','fixed':'f268ec349d4a4f13e3e8f2dd86db059959514222',
         'file':'boltons/strutils.py','symbol':'iter_splitlines',
         'goal':'Repair Unicode line and paragraph separator handling in iter_splitlines and indent. Ordinary text containing spaces followed by 28 or 29 must not be split. Preserve other line endings and existing APIs.',
         'smoke':"from boltons.strutils import iter_splitlines\ndef test_smoke():\n    assert list(iter_splitlines('a\\nb')) == ['a','b']\n",
         'public':"from boltons.strutils import iter_splitlines\ndef test_public():\n    text='February 28, 2026'\n    assert list(iter_splitlines(text)) == [text]\n    assert list(iter_splitlines('a\\u2028b')) == ['a','b']\n",
         'hidden':"from boltons.strutils import iter_splitlines, indent\nimport pytest\n@pytest.mark.parametrize('sep',['\\u2028','\\u2029','\\r\\n','\\n','\\r','\\x85'])\ndef test_separators(sep):\n    assert list(iter_splitlines(sep+'one'+sep+'two'+sep)) == ['', 'one','two','']\ndef test_indent_retention():\n    assert indent('February 28\\u2028February 29\\u2029March 1','  ') == '  February 28\\n  February 29\\n  March 1'\n"},
        {'id':'zero_iqr','repo':boltons,'upstream':'mahmoud/boltons','pr':467,
         'base':'967864f89791509f9eb36b22b4579d36b72a6df2','fixed':'4118012d17f31f81e050c4f5270b83efad4c4b3b',
         'file':'boltons/statsutils.py','symbol':'Stats._get_bin_bounds',
         'goal':'Repair automatic histogram bin selection when interquartile range is zero. Constant data and repeated values plus an outlier must produce a single bin spanning the data, without changing explicit-bin behavior or statistical calculations.',
         'smoke':"from boltons.statsutils import Stats\ndef test_smoke():\n    assert Stats([1,2,3]).mean == 2\n",
         'public':"from boltons.statsutils import Stats\ndef test_public():\n    assert Stats([5]*10).get_histogram_counts() == [(5.0,10)]\n",
         'hidden':"from boltons.statsutils import Stats\nimport pytest\n@pytest.mark.parametrize('data',[[0]*10+[100],[-3]*15,[7]*9+[70]])\ndef test_zero_iqr(data):\n    assert Stats(data).get_histogram_counts() == [(float(min(data)),len(data))]\n    assert Stats(data).format_histogram()\ndef test_retention():\n    s=Stats([1,2,3,4,5])\n    assert s.mean == 3\n    assert sum(c for _,c in s.get_histogram_counts(bins=2)) == 5\n    assert Stats([5]*10)._get_bin_bounds(with_max=True) == [5.0,5.0]\n"},
        {'id':'iteration_typeerror','repo':more,'upstream':'more-itertools/more-itertools','pr':1251,
         'base':'a826a4e09e3f2782822c71da6670e9275735ad3e','fixed':'7847d4324a581da8d0919734a8e50b2a6573b780',
         'file':'more_itertools/more.py','symbol':'value_chain',
         'goal':'Repair value_chain so TypeError raised during iteration propagates after previously yielded values. Non-iterable objects, including __iter__ raising TypeError, remain scalar values. Preserve string and bytes behavior.',
         'smoke':"from more_itertools import value_chain\ndef test_smoke():\n    assert list(value_chain(1,[2,3])) == [1,2,3]\n",
         'public':"from more_itertools import value_chain\nimport pytest\ndef test_public():\n    it=value_chain(map(len,['ab',5]))\n    assert next(it)==2\n    with pytest.raises(TypeError): next(it)\n",
         'hidden':"from more_itertools import value_chain\nimport pytest\ndef test_midstream():\n    def gen():\n        yield 1\n        yield 2\n        raise TypeError('inside')\n    it=value_chain(gen(),3)\n    assert [next(it),next(it)]==[1,2]\n    with pytest.raises(TypeError): next(it)\ndef test_scalar_retention():\n    class NotIterable:\n        def __iter__(self): raise TypeError('not iterable')\n    obj=NotIterable()\n    assert list(value_chain(1,obj,[2,3],'abc',b'ab')) == [1,obj,2,3,'abc',b'ab']\n"},
        {'id':'none_combination_index','repo':more,'upstream':'more-itertools/more-itertools','pr':1261,
         'base':'b656ecc0a64e328549a9858af1c4b609f9922b07','fixed':'069b1100383bced92e80acd6533a5a4fa135a74f',
         'file':'more_itertools/more.py','symbol':'combination_with_replacement_index',
         'goal':'Repair combination_with_replacement_index for None values in elements and pools. Return the first matching combination index, support one-shot iterables and duplicate pool values, and reject invalid combinations. Do not enumerate all preceding combinations; retain direct combinatorial calculation.',
         'smoke':"from more_itertools import combination_with_replacement_index as index\ndef test_smoke():\n    assert index('adf','abcdefg') == 20\n",
         'public':"from more_itertools import combination_with_replacement_index as index\nimport pytest\ndef test_public():\n    with pytest.raises(ValueError): index((1,None),[1,2])\n",
         'hidden':"from more_itertools import combination_with_replacement_index as index\nfrom itertools import combinations_with_replacement\nimport pytest\n@pytest.mark.parametrize('pool',[[None,1,2],[1,None,2],[1,2,None],[None,1,None],list('abc')])\ndef test_all(pool):\n    for r in range(4):\n        first={}\n        for i,elem in enumerate(combinations_with_replacement(pool,r)):\n            assert index(iter(elem),iter(pool)) == first.setdefault(elem,i)\n@pytest.mark.parametrize('elem,pool',[((None,),[1,2]),((1,None),[None,1]),((None,2),[1,None])])\ndef test_invalid(elem,pool):\n    with pytest.raises(ValueError): index(elem,pool)\ndef test_large_retention():\n    assert index([99]*20,range(100)) > 0\n"},
    ]
    cases=[]
    for s in specs:
        paths=[s['file'],'boltons/__init__.py'] if s['upstream'].endswith('boltons') else ['more_itertools/more.py','more_itertools/recipes.py','more_itertools/__init__.py']
        files={p:source(s['repo'],s['base'],p) for p in paths}
        reference={**files,s['file']:source(s['repo'],s['fixed'],s['file'])}
        if s['upstream'].endswith('boltons'):
            retention=source(s['repo'],s['base'],'tests/test_'+Path(s['file']).name)
        else:
            tests=source(s['repo'],s['base'],'tests/test_more.py')
            klass='ValueChainTests' if s['id']=='iteration_typeerror' else 'CombinationWithReplacementIndexTests'
            retention='from unittest import TestCase\nfrom itertools import *\nimport more_itertools as mi\n'+ast.get_source_segment(tests,node_for(tests,klass))+'\n'
        retention_result=grade(files,{'test_retention.py':retention})
        assert retention_result['valid'] and retention_result['passed'],(s['id'],'retention baseline invalid',retention_result)
        old=run_public(files,s['public']); fixed=grade(reference,{'test_public.py':s['public'],'test_hidden.py':s['hidden'],'test_smoke.py':s['smoke'],'test_retention.py':retention})
        assert old['valid'] and not old['passed'], (s['id'],'baseline did not fail',old)
        assert fixed['valid'] and fixed['passed'],(s['id'],'reference did not pass',fixed)
        text=files[s['file']]; node=node_for(text,s['symbol'])
        lines=text.splitlines(keepends=True)
        body=node.body[0]; indent=' '*body.col_offset
        abandoned=''.join(lines[:body.lineno-1])+indent+"raise NotImplementedError('abandoned repair')\n"+''.join(lines[node.end_lineno:])
        failed=run_public({**files,s['file']:abandoned},s['public'])
        assert failed['valid'] and not failed['passed']
        smoke=run_public(files,s['smoke']); assert smoke['passed']
        events=[
            {'id':'E0','type':'task','goal':s['goal'],'file':s['file'],'symbol':s['symbol'],'may_edit':[s['file']], 'verification':'Run the current public tests after editing before completion'},
            {'id':'E1','type':'read','revision':'r0','file':s['file'],'content':text},
            {'id':'E2','type':'test','revision':'r0','suite':'smoke','passed':True,'evaluation':smoke},
            {'id':'E3','type':'test','revision':'r0','suite':'public','passed':False,'evaluation':old,'test_source':s['public']},
            {'id':'E4','type':'edit','revision':'r1','file':s['file'],'symbol':s['symbol'],'replacement':ast.get_source_segment(abandoned,node_for(abandoned,s['symbol']))},
            {'id':'E5','type':'test','revision':'r1','suite':'public','passed':False,'evaluation':failed},
            {'id':'E6','type':'rollback','revision':'r2','restore_revision':'r0','file':s['file'],'sha256':hashlib.sha256(text.encode()).hexdigest()},
            {'id':'E7','type':'rejected','action':'edit public tests','reason':'Only the declared implementation module may be edited'},
            {'id':'E8','type':'claim','status':'unverified','text':'The last assistant said the task was finished; no test result supports that claim on r2'},
            {'id':'E9','type':'pause','revision':'r2','uncertainty':'Current revision has not been tested after rollback'},
        ]
        public_files={**files,'test_public.py':s['public'],'test_smoke.py':s['smoke']}
        cases.append({'id':s['id'],'provenance':{k:s[k] for k in ('upstream','pr','base','fixed')},
                      'goal':s['goal'],'file':s['file'],'symbol':s['symbol'],'files':public_files,'history':events,
                      'reference_files':{**reference,'test_public.py':s['public'],'test_smoke.py':s['smoke']},
                      'protected_tests':{'test_hidden.py':s['hidden']},'retention_tests':{'test_retention.py':retention},
                      'required_state':{'revision':'r2','failed_attempts':['r1'],'may_edit':[s['file']],'verified':False},
                      'preflight':{'baseline':old,'reference':fixed,'abandoned':failed,'retention':retention_result}})
    payload={'schema':'hive.real-bug-interruption.v1','cases':cases,
             'scope':'Real upstream defects; constructed, actually executed interruption histories; new to Hive, not guaranteed unseen by the model.'}
    with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('fixtures.json',json.dumps(payload,indent=2)+'\n')
        for repo,label in [(boltons,'boltons'),(more,'more-itertools')]:
            for name in ['LICENSE','LICENSE.txt']:
                p=Path(repo)/name
                if p.exists(): z.writestr(label+'-'+name,p.read_bytes()); break
    print(json.dumps({'tasks':len(cases),'preflight':'all baseline failures and reference passes verified',
                      'sha256':hashlib.sha256(Path(output).read_bytes()).hexdigest()}))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('boltons');p.add_argument('more');p.add_argument('output');a=p.parse_args()
    build(a.boltons,a.more,a.output)

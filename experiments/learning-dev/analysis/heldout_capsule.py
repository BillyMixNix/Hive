"""Task-grounded capsule compiled only from recorded public history."""
import ast
import hashlib
from analysis.heldout_build import node_for
from analysis.state_packet import canonical


def excerpt(text, symbol):
    tree=ast.parse(text)
    root=node_for(text,symbol)
    selected=[root]
    bindings={}
    for n in tree.body:
        if isinstance(n,(ast.FunctionDef,ast.ClassDef)): bindings[n.name]=n
        elif isinstance(n,(ast.Assign,ast.AnnAssign)):
            targets=n.targets if isinstance(n,ast.Assign) else [n.target]
            for target in targets:
                if isinstance(target,ast.Name): bindings[target.id]=n
        elif isinstance(n,(ast.Import,ast.ImportFrom)):
            for alias in n.names: bindings[alias.asname or alias.name.split('.')[0]]=n
    done=set()
    for n in selected:
        for name in {x.id for x in ast.walk(n) if isinstance(x,ast.Name) and isinstance(x.ctx,ast.Load)}:
            if name not in done:
                done.add(name)
                dep=bindings.get(name)
                if dep is not None and dep not in selected and not isinstance(dep,ast.ClassDef): selected.append(dep)
    # Exact source segments retain docs, comments inside nodes and local names.
    result='\n\n'.join(ast.get_source_segment(text,n) for n in sorted(selected,key=lambda n:n.lineno))
    if len(result.encode())>9000: raise ValueError('source dependency excerpt exceeds fixed budget')
    return result


def compile_history(history):
    task=history[0]
    assert task['type']=='task'
    reads={e['revision']:e for e in history if e['type']=='read'}
    rollbacks=[e for e in history if e['type']=='rollback']
    assert len(rollbacks)==1
    current=rollbacks[0]
    original=reads[current['restore_revision']]
    text=original['content']
    assert hashlib.sha256(text.encode()).hexdigest()==current['sha256']
    assert original['file']==current['file']==task['file']
    assert history[-1]['type']=='pause' and history[-1]['revision']==current['revision']
    edits={e['revision'] for e in history if e['type']=='edit'}
    failed=[e['revision'] for e in history if e['type']=='test' and e['revision'] in edits and not e['passed']]
    verified=any(e['type']=='test' and e['revision']==current['revision'] and e['suite']=='public' and e['passed'] for e in history)
    state={'revision':current['revision'],'failed_attempts':sorted(set(failed)),
           'may_edit':task['may_edit'],'verified':verified}
    evidence=[]
    for e in history[2:]:
        # Preserve actions and outcomes, but replace reproducibility digests with
        # event references. They are retained in the separately pinned raw log.
        evidence.append({k:v for k,v in e.items() if k not in {'evaluation','sha256'}})
    capsule={'schema':'hive.compiled-episode.v1','goal':task['goal'],'state':state,
             'file':task['file'],'source_sha256':current['sha256'],
             'source_excerpt':excerpt(text,task['symbol']),
             'evidence':evidence,'verification':task['verification'],
             'history_sha256':hashlib.sha256(canonical(history).encode()).hexdigest(),
             'note':'Excerpt is not the complete module; inspect can retrieve any public symbol. Earlier revisions and claims are not current verification.'}
    encoded=canonical(capsule)
    if len(encoded.encode())>12000: raise ValueError('capsule exceeds fixed ceiling; no silent truncation')
    return encoded,state

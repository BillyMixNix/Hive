
from __future__ import annotations
import re
from . import db

STOP = set("""the a an and or to of in on for is are was were be been being this that it i you we they
my your our their with from as at by if then than but not do does did have has had can could should would
will just about into what when where who why how me us them""".split())

def terms(text):
    return {x for x in re.findall(r"[A-Za-z0-9_'-]{2,}", text.lower()) if x not in STOP}

def relevant(query, limit=8):
    q = terms(query)
    rows = db.list_memories()
    scored = []
    for row in rows:
        t = terms(row["text"] + " " + (row.get("tags") or ""))
        overlap = len(q & t)
        # Recent memories still get a tiny baseline so explicit pinned memory is not invisible.
        score = overlap * 5 + min(len(t), 20) * 0.01
        scored.append((score, row))
    scored.sort(key=lambda z: z[0], reverse=True)
    picked = [r for s,r in scored[:limit] if s > 0]
    return picked

def render(query):
    rows = relevant(query)
    if not rows:
        return ""
    return "\n".join(f"- {r['text']}" for r in rows)

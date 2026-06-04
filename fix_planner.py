"""One-shot fix: ensure `exact_matches` is initialized in
PlannerAgent._extract_explicit_file_from_text (fixes the NameError that blocks the
live lesson study). Idempotent and safe to run more than once.

Run from the repo root:  python fix_planner.py
"""
import re
import shutil
from datetime import datetime
from pathlib import Path

p = Path("planner.py")
if not p.exists():
    raise SystemExit("planner.py not found — run this from the repo root (where planner.py lives).")

src = p.read_text(encoding="utf-8")
key = "def _extract_explicit_file_from_text(self, text):"
if key not in src:
    raise SystemExit("Could not find _extract_explicit_file_from_text — fix manually.")

i = src.index(key)
# Inspect the function body up to the next method at the same indent.
nxt = src.find("\n    def ", i + 1)
body = src[i: nxt if nxt != -1 else len(src)]

if re.search(r"^\s*exact_matches\s*=\s*\[\]", body, re.MULTILINE):
    print("OK: `exact_matches = []` already initialized. No change needed.")
    print("If the NameError persists it is on a different variable — paste the function and I'll look.")
    raise SystemExit(0)

# Insert the init as the first statement of the function (right after the def line).
def_line_end = src.index("\n", i) + 1
m = re.match(r"([ \t]+)\S", src[def_line_end:])
indent = m.group(1) if m else "        "
patched = src[:def_line_end] + f"{indent}exact_matches = []\n" + src[def_line_end:]

backup = p.with_suffix(f".py.bak_{datetime.now():%Y%m%d_%H%M%S}")
shutil.copy2(p, backup)
p.write_text(patched, encoding="utf-8")
print(f"Patched planner.py (backup: {backup.name}). Added `exact_matches = []` init.")
print("Now re-run the study.")

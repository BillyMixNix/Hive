"""One-shot fix: define `hard_fail_keys` at MODULE level in executor.py.

An earlier hand-edit left a reference to `hard_fail_keys` in the patch-apply path
where it is NOT defined locally, so every apply fails with
"name 'hard_fail_keys' is not defined". Defining it once at module scope makes every
function resolve it. Idempotent; backs up before writing.

Run from the repo root:  python fix_executor.py
"""
import re
import shutil
from datetime import datetime
from pathlib import Path

p = Path("executor.py")
if not p.exists():
    raise SystemExit("executor.py not found - run this from the repo root.")

src = p.read_text(encoding="utf-8")

if re.search(r"(?m)^hard_fail_keys\s*=\s*\{", src):
    print("OK: module-level hard_fail_keys already defined. No change needed.")
    print("If the error persists, paste the function that prints 'Patch apply failed'.")
    raise SystemExit(0)

definition = (
    "\n# Module-level fallback so every code path can resolve this set even if a\n"
    "# local definition was dropped by an earlier edit (restores patch-apply).\n"
    "hard_fail_keys = {\n"
    '    "no_method_insertion_inside_live_body",\n'
    '    "no_unreachable_code_after_return",\n'
    '    "no_undefined_method_call",\n'
    '    "helper_call_definition_consistency",\n'
    '    "variable_scope_sanity",\n'
    '    "structural_scope_valid",\n'
    "}\n"
)

m = re.search(r"(?m)^(class |def )", src)
insert_at = m.start() if m else len(src)
patched = src[:insert_at] + definition + "\n" + src[insert_at:]

backup = p.with_suffix(f".py.bak_{datetime.now():%Y%m%d_%H%M%S}")
shutil.copy2(p, backup)
p.write_text(patched, encoding="utf-8")
print("Patched executor.py (backup: " + backup.name + "). Added module-level hard_fail_keys.")
print("Re-run the preflight.")

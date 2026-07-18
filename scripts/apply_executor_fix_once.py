from pathlib import Path


path = Path("executor.py")
text = path.read_text(encoding="utf-8")
old = '''        return {
            "verified": checks["safe_to_apply"],
            "anchor_index": anchor_index,
            "block_span": block_span,
        }
'''
new = '''        return {
            "verified": checks["safe_to_apply"],
            "checks": checks,
            "anchor_index": anchor_index,
            "block_span": block_span,
        }
'''

count = text.count(old)
if count != 1:
    raise SystemExit(
        f"Expected one verify_patch_context return block, found {count}."
    )

path.write_text(text.replace(old, new, 1), encoding="utf-8")

from pathlib import Path
src = Path("coder.py").read_text(encoding="utf-8")
needle = "            except Exception as e:\n                print(f\"[Coder] Exception: {e}\")"
replacement = "            except Exception as e:\n                import traceback; traceback.print_exc()\n                print(f\"[Coder] Exception: {e}\")"
if needle in src:
    Path("coder.py").write_text(src.replace(needle, replacement, 1), encoding="utf-8")
    print("Patched.")
else:
    print("Not found.")
with open("coder.py", "r") as f:
    src = f.read()

bad = """                import traceback
                traceback.print_exc()
"""

if bad.strip() not in src:
    print("Traceback lines not found — already clean or check manually")
else:
    src = src.replace(bad, "", 1)
    with open("coder.py", "w") as f:
        f.write(src)
    print("Reverted.")
with open("coder_validation.py", "r") as f:
    src = f.read()

bad = """
    # Fuzzy filter to handle unexpected input gracefully
    if not isinstance(selected_block, dict):
        raise ValueError("symbol_anchor_drift: selected_block must be a dictionary.")
"""

good = "\n"

if bad.strip() not in src:
    print("ERROR: Could not find the bad block — check manually")
else:
    src = src.replace(bad, good, 1)
    with open("coder_validation.py", "w") as f:
        f.write(src)
    print("Fixed.")
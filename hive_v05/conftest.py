import sys
from pathlib import Path

# Ensure hive_v05 modules (planner, coder, reflector, etc.) take precedence
# over root-level modules of the same name when pytest collects tests from
# the repository root with `pytest -q`.
_hive_v05_root = str(Path(__file__).resolve().parent)
if _hive_v05_root not in sys.path:
    sys.path.insert(0, _hive_v05_root)

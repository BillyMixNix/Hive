"""Launch with python3 -I -S: no user site, .pth hooks or Python env injection."""
import sys
from pathlib import Path

if not sys.flags.isolated or not sys.flags.no_site:
    raise SystemExit('use python3 -I -S portable_verifier/entrypoint.py')
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
if sys.argv[1:] == ['--test']:
    import unittest
    suite = unittest.defaultTestLoader.discover(str(root / 'tests/portable_verifier'))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
from portable_verifier.bootstrap import main
raise SystemExit(main())

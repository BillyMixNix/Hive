"""Byte-preserved FACTORIAL-003R1 engine; only the RC1 adapter is authoritative.

The recovered verifier uses absolute ``verification.nfrt_seed`` and
``workshop.external_root`` imports. Bind those historical package names to
this private copy before importing the engine;
the underlying archived files remain byte-identical.
"""

import sys

from . import verification as _verification
from . import workshop as _workshop

for _name, _package in (("verification", _verification), ("workshop", _workshop)):
    existing = sys.modules.get(_name)
    if existing is not None and existing is not _package:
        raise ImportError(f"another {_name} package is already loaded; RC1 cannot bind recovered authority")
    sys.modules[_name] = _package

"""Byte-preserved FACTORIAL-003R1 engine; only the RC1 adapter is authoritative.

The recovered verifier uses absolute ``verification.nfrt_seed`` imports. Bind
that historical package name to this private copy before importing the engine;
the underlying archived files remain byte-identical.
"""

import sys

from . import verification as _verification

existing = sys.modules.get("verification")
if existing is not None and existing is not _verification:
    raise ImportError("another verification package is already loaded; RC1 cannot bind recovered verifier authority")
sys.modules["verification"] = _verification

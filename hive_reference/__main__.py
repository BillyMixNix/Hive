"""Run the deterministic reference demo or frozen benchmark adapter."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hive_reference.adapter import DEFAULT_CASE_PACK, FrozenDecompressionAdapter
from hive_reference.demo import run_demo, write_demo_result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter-check", action="store_true", help="inspect the frozen codec without inference")
    parser.add_argument("--case-pack", type=Path, default=DEFAULT_CASE_PACK)
    parser.add_argument("--claims", type=Path, default=Path("hive_reference/spec/claims.json"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.adapter_check:
        payload = FrozenDecompressionAdapter().inspect(args.case_pack).to_mapping()
    elif args.output:
        payload = write_demo_result(args.output, claims_path=args.claims)
    else:
        payload = run_demo(claims_path=args.claims)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

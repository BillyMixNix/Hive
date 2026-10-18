from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any


C4_COMMIT = "2feb8c0a142b2e513be69442c24af82dbaf41a25"
C4_BLOB = "0340255f0031ee36bf3f38bc171a4fde8922bc75"
HELLO_BLOB = "ab0650697c4c620bc0a560af5d7582be4f569bef"
RAW_BASE = f"https://raw.githubusercontent.com/rswier/c4/{C4_COMMIT}"
OPERAND_LINE = re.compile(r"^\s*(LEA|IMM|JMP|JSR|BZ|BNZ|ENT|ADJ)\s+(-?\d+)\s*$")


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "hive-trial-003-probe"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def run(args: list[str], cwd: Path, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
        env={**os.environ, "LC_ALL": "C"},
    )


def operand_stream(text: str) -> list[tuple[str, int]]:
    result: list[tuple[str, int]] = []
    for line in text.splitlines():
        match = OPERAND_LINE.match(line)
        if match:
            result.append((match.group(1), int(match.group(2))))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="trial003_probe.json")
    args = parser.parse_args()

    if shutil.which("gcc") is None:
        raise SystemExit("gcc unavailable; Trial 003 probe is inconclusive")

    report: dict[str, Any] = {
        "schema": 1,
        "trial": "Hive External Engineering Trial 003",
        "c4_commit": C4_COMMIT,
        "frozen_git_blobs": {"c4.c": C4_BLOB, "hello.c": HELLO_BLOB},
    }

    with tempfile.TemporaryDirectory(prefix="hive-trial003-") as tmp:
        work = Path(tmp)
        c4 = download(f"{RAW_BASE}/c4.c")
        hello = download(f"{RAW_BASE}/hello.c")

        identities = {
            "c4.c": {
                "git_blob": git_blob_sha(c4),
                "sha256": sha256_bytes(c4),
                "bytes": len(c4),
            },
            "hello.c": {
                "git_blob": git_blob_sha(hello),
                "sha256": sha256_bytes(hello),
                "bytes": len(hello),
            },
        }
        report["identities"] = identities
        if identities["c4.c"]["git_blob"] != C4_BLOB or identities["hello.c"]["git_blob"] != HELLO_BLOB:
            raise SystemExit("frozen source identity mismatch")

        (work / "c4.c").write_bytes(c4)
        (work / "hello.c").write_bytes(hello)

        gcc_version = run(["gcc", "--version"], work, timeout=10)
        report["gcc_version_first_line"] = gcc_version.stdout.splitlines()[0] if gcc_version.stdout else ""

        compile_result = run(
            ["gcc", "-std=gnu11", "-O0", "-fno-pie", "-no-pie", "-o", "c4", "c4.c"],
            work,
        )
        report["compile"] = {
            "returncode": compile_result.returncode,
            "output_sha256": sha256_bytes(compile_result.stdout.encode()),
        }
        if compile_result.returncode != 0:
            raise SystemExit("frozen c4 failed to compile")

        chains = {
            "direct": ["hello.c"],
            "self_host_1": ["c4.c", "hello.c"],
            "self_host_2": ["c4.c", "c4.c", "hello.c"],
        }
        chain_report: dict[str, Any] = {}
        for name, chain_args in chains.items():
            completed = run([str(work / "c4"), *chain_args], work)
            chain_report[name] = {
                "returncode": completed.returncode,
                "contains_hello": "hello, world" in completed.stdout,
                "contains_exit0": "exit(0)" in completed.stdout,
                "stdout_sha256": sha256_bytes(completed.stdout.encode()),
                "stdout_bytes": len(completed.stdout.encode()),
            }
            if completed.returncode != 0 or "hello, world" not in completed.stdout or "exit(0)" not in completed.stdout:
                raise SystemExit(f"{name} chain failed")
        report["chains"] = chain_report

        trace_a = run([str(work / "c4"), "-s", "hello.c"], work)
        trace_b = run([str(work / "c4"), "-s", "hello.c"], work)
        if trace_a.returncode != 0 or trace_b.returncode != 0:
            raise SystemExit("address-variance trace probe failed to execute")

        ops_a = operand_stream(trace_a.stdout)
        ops_b = operand_stream(trace_b.stdout)
        paired = list(zip(ops_a, ops_b))
        differing = [
            {
                "index": index,
                "opcode_a": left[0],
                "operand_a": left[1],
                "opcode_b": right[0],
                "operand_b": right[1],
            }
            for index, (left, right) in enumerate(paired)
            if left != right
        ]
        opcode_diff_counts = Counter(item["opcode_a"] for item in differing)

        report["address_variance_probe"] = {
            "trace_equal": trace_a.stdout == trace_b.stdout,
            "trace_a_sha256": sha256_bytes(trace_a.stdout.encode()),
            "trace_b_sha256": sha256_bytes(trace_b.stdout.encode()),
            "operand_count_a": len(ops_a),
            "operand_count_b": len(ops_b),
            "differing_operand_count": len(differing),
            "differing_opcode_counts": dict(sorted(opcode_diff_counts.items())),
            "first_differences": differing[:20],
        }
        if trace_a.stdout == trace_b.stdout:
            raise SystemExit(
                "fresh-process traces were byte-identical; address-variance observation is inconclusive"
            )

    output = Path(args.output)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

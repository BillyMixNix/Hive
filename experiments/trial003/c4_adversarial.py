from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

C4_COMMIT = "2feb8c0a142b2e513be69442c24af82dbaf41a25"
C4_BLOB = "0340255f0031ee36bf3f38bc171a4fde8922bc75"
HELLO_BLOB = "ab0650697c4c620bc0a560af5d7582be4f569bef"
RAW_BASE = f"https://raw.githubusercontent.com/rswier/c4/{C4_COMMIT}"
OP_RE = re.compile(r"^\s*(LEA|IMM|JMP|JSR|BZ|BNZ|ENT|ADJ|LEV|LI|LC|SI|SC|PSH|OR|XOR|AND|EQ|NE|LT|GT|LE|GE|SHL|SHR|ADD|SUB|MUL|DIV|MOD|OPEN|READ|CLOS|PRTF|MALC|FREE|MSET|MCMP|EXIT)(?:\s+(-?\d+))?\s*$")
INT_LINE_RE = re.compile(r"^\s*(-?\d+)\s*$")


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()


def sha256(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()


def download(name: str) -> bytes:
    req = urllib.request.Request(f"{RAW_BASE}/{name}", headers={"User-Agent": "hive-trial003-c4-adversary"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read()


def run(args: list[str], cwd: Path, *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
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


def first_standalone_int(text: str) -> int | None:
    for line in text.splitlines():
        match = INT_LINE_RE.match(line)
        if match:
            return int(match.group(1))
    return None


def trace_ops(text: str) -> list[tuple[str, int | None]]:
    out: list[tuple[str, int | None]] = []
    for line in text.splitlines():
        match = OP_RE.match(line)
        if match:
            out.append((match.group(1), int(match.group(2)) if match.group(2) is not None else None))
    return out


def opcode_projection(ops: list[tuple[str, int | None]]) -> list[str]:
    return [op for op, _ in ops]


def result(contract_id: str, reproduced: bool, **details: Any) -> dict[str, Any]:
    return {
        "id": contract_id,
        "violation_reproduced": bool(reproduced),
        **details,
    }


def main() -> int:
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "c4_adversarial.json")
    if shutil.which("gcc") is None or shutil.which("bash") is None or shutil.which("dd") is None:
        raise SystemExit("required host tools unavailable; Trial 003 c4 adversary is inconclusive")

    report: dict[str, Any] = {
        "schema": 1,
        "trial": "Hive External Engineering Trial 003",
        "subject": "rswier/c4",
        "commit": C4_COMMIT,
        "invariant": "represented-equivalent state + same future cause => represented-equivalent successor",
        "contracts": [],
    }

    with tempfile.TemporaryDirectory(prefix="hive-c4-adversary-") as td:
        work = Path(td)
        c4_bytes = download("c4.c")
        hello_bytes = download("hello.c")
        if git_blob_sha(c4_bytes) != C4_BLOB or git_blob_sha(hello_bytes) != HELLO_BLOB:
            raise SystemExit("frozen c4 source identity mismatch")
        (work / "c4.c").write_bytes(c4_bytes)
        (work / "hello.c").write_bytes(hello_bytes)

        built = run(["gcc", "-std=gnu11", "-O0", "-fno-pie", "-no-pie", "-o", "c4", "c4.c"], work)
        if built.returncode != 0:
            raise SystemExit(f"frozen c4 compilation failed:\n{built.stdout}")
        c4 = str(work / "c4")

        # T5-A: Symbol-table history is causal compiler state.
        # The future source suffix is byte-identical; only the already-consumed prefix differs.
        # A representation that keeps only the current/future source bytes therefore collapses
        # two compiler realities whose next compilation transitions are not equivalent.
        suffix = "int main(){ return x; }\n"
        src_has_x = "int x;\n" + suffix
        src_no_x = "int y;\n" + suffix
        (work / "sym_a.c").write_text(src_has_x)
        (work / "sym_b.c").write_text(src_no_x)
        sym_a = run([c4, "sym_a.c"], work)
        sym_b = run([c4, "sym_b.c"], work)
        sym_reproduced = (
            sym_a.returncode == 0
            and "exit(0)" in sym_a.stdout
            and sym_b.returncode != 0
            and "undefined variable" in sym_b.stdout
        )
        report["contracts"].append(result(
            "compiler_symbol_table_history_separator",
            sym_reproduced,
            projection={"remaining_source_sha256": sha256(suffix), "remaining_source_bytes": len(suffix.encode())},
            left={"prefix": "int x;", "returncode": sym_a.returncode, "stdout_sha256": sha256(sym_a.stdout)},
            right={"prefix": "int y;", "returncode": sym_b.returncode, "stdout_sha256": sha256(sym_b.stdout)},
            interpretation="remaining source alone is not transition-complete; symbol-table state is authoritative",
        ))

        # T5-B: Diagnostic chronology is state too when diagnostics are observations under contract.
        # Same invalid future suffix, different already-consumed newline history -> different diagnostic truth.
        bad_suffix = "int main(){ return missing; }\n"
        (work / "line_a.c").write_text(bad_suffix)
        (work / "line_b.c").write_text("\n\n\n" + bad_suffix)
        line_a = run([c4, "line_a.c"], work)
        line_b = run([c4, "line_b.c"], work)
        la = re.search(r"(?m)^(\d+): undefined variable", line_a.stdout)
        lb = re.search(r"(?m)^(\d+): undefined variable", line_b.stdout)
        line_a_num = int(la.group(1)) if la else None
        line_b_num = int(lb.group(1)) if lb else None
        line_reproduced = (
            line_a.returncode != 0 and line_b.returncode != 0
            and line_a_num is not None and line_b_num is not None
            and line_a_num != line_b_num
        )
        report["contracts"].append(result(
            "compiler_line_history_observation_separator",
            line_reproduced,
            projection={"remaining_source_sha256": sha256(bad_suffix)},
            left_line=line_a_num,
            right_line=line_b_num,
            interpretation="if diagnostics are authoritative observations, line chronology must be represented or fixed",
        ))

        # T5-C: Raw pointer-bearing compiler output is not a canonical cross-process representation.
        # The opcode sequence is the semantic projection; absolute pointer operands are host-layout representation.
        trace_a = run([c4, "-s", "hello.c"], work)
        trace_b = run([c4, "-s", "hello.c"], work)
        ops_a = trace_ops(trace_a.stdout)
        ops_b = trace_ops(trace_b.stdout)
        opcode_equal = opcode_projection(ops_a) == opcode_projection(ops_b) and len(ops_a) > 0
        raw_equal = trace_a.stdout == trace_b.stdout
        operand_differences = sum(1 for a, b in zip(ops_a, ops_b) if a != b) + abs(len(ops_a) - len(ops_b))
        pointer_reproduced = trace_a.returncode == 0 and trace_b.returncode == 0 and opcode_equal and not raw_equal and operand_differences > 0
        report["contracts"].append(result(
            "raw_host_pointer_representation_is_noncanonical",
            pointer_reproduced,
            trace_a_sha256=sha256(trace_a.stdout),
            trace_b_sha256=sha256(trace_b.stdout),
            opcode_projection_equal=opcode_equal,
            operand_differences=operand_differences,
            interpretation="raw host addresses are representation, not portable semantic authority; fresh-process snapshots need region-relative relocation",
        ))

        # T6-A: Host descriptor allocation is causal environment state.
        # The C program and target file are identical. Occupying inherited fd 3 changes OPEN's result.
        (work / "probe.txt").write_text("same bytes\n")
        fd_program = 'int main(){ int fd; fd=open("probe.txt",0); printf("%lld\\n",fd); if(fd>=0) close(fd); return 0; }\n'
        (work / "fd_probe.c").write_text(fd_program)
        fd_normal = run([c4, "fd_probe.c"], work)
        fd_occupied = run(["bash", "-c", 'exec 3</dev/null; exec "$1" "$2"', "_", c4, "fd_probe.c"], work)
        fd_normal_value = first_standalone_int(fd_normal.stdout)
        fd_occupied_value = first_standalone_int(fd_occupied.stdout)
        fd_reproduced = (
            fd_normal.returncode == 0 and fd_occupied.returncode == 0
            and fd_normal_value is not None and fd_occupied_value is not None
            and fd_normal_value != fd_occupied_value
        )
        report["contracts"].append(result(
            "vm_open_depends_on_unrepresented_host_fd_table",
            fd_reproduced,
            same_program_sha256=sha256(fd_program),
            same_file_sha256=sha256((work / "probe.txt").read_bytes()),
            normal_open_result=fd_normal_value,
            occupied_fd3_open_result=fd_occupied_value,
            interpretation="host descriptor table participates in the OPEN transition unless modeled as explicit environment/cause",
        ))

        # T6-B: File cursor phase is causal environment state.
        # Both runs inherit the same logical fd number pointing to the same bytes; only the host cursor differs.
        # The same READ transition then yields a different accumulator/memory result exposed by printf.
        (work / "cursor.bin").write_bytes(b"AB")
        read_program = 'int main(){ int x; x=0; read(3,&x,1); printf("%lld\\n",x); return 0; }\n'
        (work / "cursor_probe.c").write_text(read_program)
        cursor_zero = run(["bash", "-c", 'exec 3<cursor.bin; exec "$1" "$2"', "_", c4, "cursor_probe.c"], work)
        cursor_one = run(["bash", "-c", 'exec 3<cursor.bin; dd bs=1 count=1 <&3 >/dev/null 2>&1; exec "$1" "$2"', "_", c4, "cursor_probe.c"], work)
        cursor_zero_value = first_standalone_int(cursor_zero.stdout)
        cursor_one_value = first_standalone_int(cursor_one.stdout)
        cursor_reproduced = (
            cursor_zero.returncode == 0 and cursor_one.returncode == 0
            and cursor_zero_value == ord("A") and cursor_one_value == ord("B")
        )
        report["contracts"].append(result(
            "vm_read_depends_on_unrepresented_host_file_cursor",
            cursor_reproduced,
            same_program_sha256=sha256(read_program),
            same_file_sha256=sha256((work / "cursor.bin").read_bytes()),
            fd_number=3,
            cursor0_result=cursor_zero_value,
            cursor1_result=cursor_one_value,
            interpretation="file offset is causal environment phase; fd identity alone is not transition-complete",
        ))

        # T6-C: Host allocator addresses are not stable semantic identity.
        # This is recorded as a stress observation, while the raw compiler trace above is the hard gate.
        malloc_program = 'int main(){ int *p; p=malloc(8); printf("%lld\\n",p); free(p); return 0; }\n'
        (work / "malloc_probe.c").write_text(malloc_program)
        malloc_values: list[int] = []
        malloc_runs: list[dict[str, Any]] = []
        for _ in range(4):
            proc = run([c4, "malloc_probe.c"], work)
            value = first_standalone_int(proc.stdout)
            malloc_runs.append({"returncode": proc.returncode, "pointer": value, "stdout_sha256": sha256(proc.stdout)})
            if proc.returncode == 0 and value is not None:
                malloc_values.append(value)
        report["allocator_stress"] = {
            "same_program_sha256": sha256(malloc_program),
            "runs": malloc_runs,
            "distinct_pointer_values": len(set(malloc_values)),
            "observation": "raw heap addresses are host-process representation; canonical checkpoint state must not use them as portable identity",
        }

        # Positive control: despite representation/environment hazards, fixed explicit causes preserve final semantics.
        hello = run([c4, "hello.c"], work)
        report["positive_control"] = {
            "id": "frozen_hello_semantics",
            "pass": hello.returncode == 0 and "hello, world" in hello.stdout and "exit(0)" in hello.stdout,
            "stdout_sha256": sha256(hello.stdout),
        }

    hard_failures = [c["id"] for c in report["contracts"] if not c["violation_reproduced"]]
    report["all_preregistered_violations_reproduced"] = not hard_failures
    report["unreproduced_contracts"] = hard_failures
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not hard_failures and report["positive_control"]["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

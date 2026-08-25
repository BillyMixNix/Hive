from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import urllib.request
from pathlib import Path

import pytest


C4_COMMIT = "2feb8c0a142b2e513be69442c24af82dbaf41a25"
C4_BLOB = "0340255f0031ee36bf3f38bc171a4fde8922bc75"
HELLO_BLOB = "ab0650697c4c620bc0a560af5d7582be4f569bef"
RAW_BASE = f"https://raw.githubusercontent.com/rswier/c4/{C4_COMMIT}"


def _git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "hive-trial-003"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def _run(args: list[str], *, cwd: Path, timeout: int = 60) -> subprocess.CompletedProcess[str]:
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


@pytest.fixture(scope="module")
def frozen_c4(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if shutil.which("gcc") is None:
        pytest.fail("Trial 003 is inconclusive: gcc is unavailable; do not salvage this run")

    work = tmp_path_factory.mktemp("trial003_c4")
    c4_bytes = _download(f"{RAW_BASE}/c4.c")
    hello_bytes = _download(f"{RAW_BASE}/hello.c")

    assert _git_blob_sha(c4_bytes) == C4_BLOB, "frozen c4.c identity mismatch"
    assert _git_blob_sha(hello_bytes) == HELLO_BLOB, "frozen hello.c identity mismatch"

    (work / "c4.c").write_bytes(c4_bytes)
    (work / "hello.c").write_bytes(hello_bytes)

    compile_result = _run(
        ["gcc", "-std=gnu11", "-O0", "-fno-pie", "-no-pie", "-o", "c4", "c4.c"],
        cwd=work,
    )
    assert compile_result.returncode == 0, (
        "Trial 003 external baseline failed to compile. Output:\n" + compile_result.stdout
    )
    return work


def _assert_hello_chain(work: Path, args: list[str], *, timeout: int = 60) -> str:
    result = _run([str(work / "c4"), *args], cwd=work, timeout=timeout)
    assert result.returncode == 0, (
        f"c4 chain {args!r} returned {result.returncode}. Output:\n{result.stdout}"
    )
    assert "hello, world" in result.stdout, (
        f"c4 chain {args!r} did not execute hello.c. Output:\n{result.stdout}"
    )
    assert "exit(0)" in result.stdout, (
        f"c4 chain {args!r} did not report successful VM termination. Output:\n{result.stdout}"
    )
    return result.stdout


def test_trial003_frozen_c4_runs_hello(frozen_c4: Path) -> None:
    _assert_hello_chain(frozen_c4, ["hello.c"])


def test_trial003_frozen_c4_runs_one_self_host_level(frozen_c4: Path) -> None:
    _assert_hello_chain(frozen_c4, ["c4.c", "hello.c"], timeout=90)


def test_trial003_frozen_c4_runs_two_self_host_levels(frozen_c4: Path) -> None:
    _assert_hello_chain(frozen_c4, ["c4.c", "c4.c", "hello.c"], timeout=120)


def test_trial003_identical_source_exposes_address_sensitive_trace(frozen_c4: Path) -> None:
    """Boundary probe, not a claim that c4 promises canonical traces.

    c4 emits host addresses into its diagnostic assembly stream. Fresh processes with
    identical source should therefore normally produce different raw `-s` bytes under
    ASLR. Trial 003 records this as an adapter hazard: raw host pointer identity must not
    be promoted into process-independent authoritative identity.
    """

    first = _run([str(frozen_c4 / "c4"), "-s", "hello.c"], cwd=frozen_c4)
    second = _run([str(frozen_c4 / "c4"), "-s", "hello.c"], cwd=frozen_c4)

    assert first.returncode == 0 and second.returncode == 0
    assert "hello" in first.stdout and "hello" in second.stdout

    # This is intentionally fail-closed as an adversarial observation. If the host
    # happens to disable ASLR or reuse the exact same addresses, the probe cannot
    # establish the expected address variance and the run is inconclusive rather than
    # silently counting the observation as evidence.
    if first.stdout == second.stdout:
        pytest.fail(
            "Trial 003 address-variance probe was inconclusive: two fresh c4 -s traces "
            "were byte-identical; do not count host-address variance as observed"
        )

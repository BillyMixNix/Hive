"""Host-owned Docker boundary. Never fall back to executing a subject on the host.

The daemon must be local to an expendable, credential-free Linux VM. Containers
share its kernel; this is defense in depth, not a VM escape guarantee.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import selectors
import subprocess
import time
import uuid


class SandboxUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Limits:
    memory_mb: int = 256
    cpus: int = 1
    pids: int = 32
    wall_seconds: int = 20
    output_bytes: int = 262144
    tmpfs_mb: int = 16

    def __post_init__(self):
        for value in asdict(self).values():
            if type(value) is not int or value < 1:
                raise ValueError("Sandbox limits must be positive integers")


@dataclass(frozen=True)
class Run:
    status: str
    exit_code: int | None
    stdout: str
    wall_ms: float
    oom_killed: bool
    cpu_seconds: float | None


def _docker(*args: str, timeout: int = 20) -> str:
    try:
        return subprocess.check_output(
            ["docker", *args], stderr=subprocess.STDOUT, timeout=timeout,
        ).decode("utf-8")
    except (OSError, subprocess.SubprocessError) as exc:
        raise SandboxUnavailable(f"Docker control operation failed: {type(exc).__name__}") from None


class ContainerRunner:
    def __init__(self, image: str, harness: Path, limits: Limits = Limits()):
        # Mutable tags, caller-provided image commands, and remote daemons are forbidden.
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
            raise ValueError("An already-built immutable local image ID is required")
        self.image = image
        self.harness = harness.resolve(strict=True)
        self.limits = limits
        if not self.harness.is_dir():
            raise ValueError("Harness must be a trusted directory")

    def preflight(self) -> dict:
        context = json.loads(_docker("context", "inspect"))[0]
        endpoint = context["Endpoints"]["docker"]["Host"]
        if not endpoint.startswith("unix://"):
            raise SandboxUnavailable("Only a local Unix Docker daemon is supported")
        info = json.loads(_docker("info", "--format", "{{json .}}"))
        security = info.get("SecurityOptions", [])
        if info.get("OSType") != "linux" or not any("seccomp" in s for s in security):
            raise SandboxUnavailable("Linux Docker with default seccomp is required")
        if any(info.get(k) is not True for k in ("MemoryLimit", "PidsLimit", "CpuCfsQuota")):
            raise SandboxUnavailable("Required resource controller unavailable")
        inspected = json.loads(_docker("image", "inspect", self.image))[0]
        if inspected["Id"] != self.image or inspected["Config"].get("Volumes"):
            raise SandboxUnavailable("Image identity or volume policy failed")
        return {"image_id": self.image, "docker_version": info.get("ServerVersion"),
                "kernel": info.get("KernelVersion"), "architecture": info.get("Architecture"),
                "security_options": security, "limits": asdict(self.limits)}

    def command(self, source: Path, name: str, mode: str) -> list[str]:
        if mode not in {"extract", "regressions", "syntax", "probe", "hang", "flood", "oom", "pytest"}:
            raise ValueError("Unknown trusted worker mode")
        source = source.resolve(strict=True)
        if not source.is_dir() or any(p.is_symlink() for p in source.rglob("*")):
            raise ValueError("Subject snapshots must contain only regular files/directories")
        if any("," in str(p) for p in (source, self.harness)):
            raise ValueError("Mount paths cannot contain Docker mount delimiters")
        lim = self.limits
        return [
            "docker", "create", "--name", name, "--pull=never", "--interactive",
            "--network=none", "--read-only", "--user=65534:65534",
            "--cap-drop=ALL", "--security-opt=no-new-privileges:true",
            "--cgroupns=private", "--ipc=none", "--pids-limit", str(lim.pids),
            "--memory", f"{lim.memory_mb}m", "--memory-swap", f"{lim.memory_mb}m",
            "--cpus", str(lim.cpus), "--ulimit", "nofile=128:128",
            "--ulimit", "core=0:0", "--ulimit", "fsize=1048576:1048576",
            "--log-driver=none", "--no-healthcheck",
            "--tmpfs", f"/tmp:rw,nosuid,nodev,noexec,size={lim.tmpfs_mb}m,mode=1777",
            "--mount", f"type=bind,source={source},target=/subject,readonly",
            "--mount", f"type=bind,source={self.harness},target=/harness,readonly",
            "--workdir=/tmp", "--env=PYTHONDONTWRITEBYTECODE=1",
            "--env=PYTHONHASHSEED=0", "--entrypoint=python", self.image,
            "-I", "-B", "/harness/worker.py", mode,
        ]

    def run(self, source: Path, mode: str, payload: dict | None = None) -> Run:
        data = json.dumps(payload or {}, allow_nan=False).encode() + b"\n"
        if len(data) > 65536:
            raise ValueError("Input envelope exceeds 64 KiB")
        name = "hive-ri-" + uuid.uuid4().hex
        command = self.command(source, name, mode)
        process = None
        started = time.monotonic()
        output = bytearray()
        status, code, oom, cpu = "error", None, False, None
        try:
            _docker(*command[1:])
            config = json.loads(_docker("inspect", name))[0]
            host = config["HostConfig"]
            if (not host["ReadonlyRootfs"] or host["Privileged"]
                    or host["NetworkMode"] != "none"
                    or host["Memory"] != self.limits.memory_mb * 1024**2
                    or host["MemorySwap"] != host["Memory"]
                    or host["PidsLimit"] != self.limits.pids
                    or host["NanoCpus"] != self.limits.cpus * 10**9
                    or config["Config"]["User"] != "65534:65534"
                    or any(m["RW"] for m in config["Mounts"] if m["Type"] == "bind")):
                raise SandboxUnavailable("Created container failed policy inspection")
            process = subprocess.Popen(
                ["docker", "start", "--attach", "--interactive", name],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            process.stdin.write(data)
            process.stdin.close()
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                status = "completed"
                deadline = started + self.limits.wall_seconds
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        status = "timeout"
                        break
                    for key, _ in selector.select(min(remaining, 0.1)):
                        chunk = key.fileobj.read1(8192)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        available = self.limits.output_bytes - len(output)
                        output.extend(chunk[:available])
                        if len(chunk) > available:
                            status = "output_limit"
                            break
                    if status != "completed":
                        break
            if status == "completed":
                code = process.wait(timeout=max(0.1, deadline - time.monotonic()))
                state = json.loads(_docker("inspect", name))[0]["State"]
                oom = state.get("OOMKilled", False)
                code = state.get("ExitCode", code)
                if code != 0:
                    status = "oom" if oom else "error"
        except subprocess.TimeoutExpired:
            status = "timeout"
        finally:
            # Disconnect attachment before removal. A flooding subject can otherwise
            # fill the pipe and block daemon teardown behind output backpressure.
            try:
                if process is not None:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=10)
                    process.stdout.close()
            finally:
                # Whole-container removal kills detached descendants as well.
                # A cleanup error propagates, preventing further evaluation.
                _docker("rm", "--force", name, timeout=10)
        return Run(status, code, output.decode("utf-8", errors="replace"),
                   (time.monotonic() - started) * 1000, oom, cpu)

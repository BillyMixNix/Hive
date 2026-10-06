"""Explicit operator-only Gradle dependency-cache priming for external roots.

Priming uses a network-enabled, confined container and a dedicated writable
Gradle user home. Normal verification remains a separate networkless path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


REPO_ROOT = Path(__file__).resolve().parents[1]
HIVE_RUNS = REPO_ROOT / "hive_runs"
APPROVED_CACHE_ROOT = HIVE_RUNS / "approved-gradle-caches"
IMAGE = "nix-workshop-verifier:0.11.1-jvm21-extroot-002d-tmpfscopy"
MAX_PAYLOAD_BYTES = 64_000
DOCKER_TIMEOUT_SECONDS = 1860
PRIME_RUNNER_TIMEOUT_SECONDS = 1800
URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)

sys.path.insert(0, str(REPO_ROOT))
from workshop import external_root, hive_jvm  # noqa: E402


class PrimingError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _inventory_cache(root: Path) -> list[dict]:
    """Hash every regular file populated in a new, dedicated Gradle home."""
    root = root.resolve(strict=True)
    rows = []
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        base = Path(current)
        dirs.sort(key=lambda value: (value.casefold(), value))
        for name in dirs:
            path = base / name
            if path.is_symlink():
                raise PrimingError(f"primed cache contains a linked directory: {path.relative_to(root)}")
        for name in sorted(files, key=lambda value: (value.casefold(), value)):
            path = base / name
            if path.is_symlink() or not path.is_file():
                raise PrimingError(f"primed cache contains a link or special file: {path.relative_to(root)}")
            rel = path.relative_to(root).as_posix()
            if rel == ".hive-priming-provenance" or rel.startswith(".hive-priming-provenance/"):
                continue
            rows.append({"path": rel, "size": path.stat().st_size, "sha256": _sha256_file(path)})
    return sorted(rows, key=lambda item: (item["path"].casefold(), item["path"]))


def _safe_source_url(value: str | None) -> str | None:
    if not isinstance(value, str) or len(value) > 4096:
        return None
    try:
        parsed = urlsplit(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None
        host = parsed.hostname.lower()
        if parsed.port:
            host = f"{host}:{parsed.port}"
        # Remove userinfo, query strings, and fragments from provenance.
        return f"{parsed.scheme.lower()}://{host}{parsed.path}"
    except ValueError:
        return None


def _redact_urls(text: str) -> str:
    text = str(text or "")
    return URL_RE.sub(lambda match: _safe_source_url(match.group(0)) or "[redacted-url]", text)


def _neoform_source_urls(native_root: Path, observed_urls: list[str]) -> dict[str, str]:
    """Map NeoForm-native cached inputs to URLs from their own metadata."""
    sources: dict[str, str] = {}
    artifacts = native_root / "artifacts"
    launcher_manifest = artifacts / "minecraft_launcher_manifest.json"
    launcher_versions: dict[str, str] = {}
    if launcher_manifest.is_file() and not launcher_manifest.is_symlink():
        try:
            document = json.loads(launcher_manifest.read_text(encoding="utf-8"))
            for item in document.get("versions", []):
                if isinstance(item, dict) and isinstance(item.get("id"), str):
                    safe = _safe_source_url(item.get("url"))
                    if safe:
                        launcher_versions[item["id"]] = safe
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            pass

    for path in sorted(artifacts.glob("minecraft_*_version_manifest.json")):
        name = path.name
        version = name.removeprefix("minecraft_").removesuffix("_version_manifest.json")
        relative = path.relative_to(native_root).as_posix()
        if version in launcher_versions:
            sources[relative] = launcher_versions[version]
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        downloads = document.get("downloads", {})
        if isinstance(downloads, dict):
            for label, metadata in downloads.items():
                if not isinstance(label, str) or not isinstance(metadata, dict):
                    continue
                safe = _safe_source_url(metadata.get("url"))
                raw_url = metadata.get("url")
                filename = Path(urlsplit(raw_url).path).name if isinstance(raw_url, str) else ""
                suffix = Path(filename).suffix
                if safe and suffix:
                    target = native_root / "artifacts" / f"minecraft_{version}_{label}{suffix}"
                    if target.is_file() and not target.is_symlink():
                        sources[target.relative_to(native_root).as_posix()] = safe
        asset_index = document.get("assetIndex")
        if isinstance(asset_index, dict) and isinstance(asset_index.get("id"), str):
            safe = _safe_source_url(asset_index.get("url"))
            target = native_root / "assets" / "indexes" / f"{asset_index['id']}.json"
            if safe and target.is_file() and not target.is_symlink():
                sources[target.relative_to(native_root).as_posix()] = safe

    # The launcher manifest is the source of per-version manifest URLs; its
    # own download URL is recorded from NeoForm's emitted request when present.
    launcher_path = "artifacts/minecraft_launcher_manifest.json"
    for raw_url in observed_urls:
        safe = _safe_source_url(raw_url)
        if not safe:
            continue
        parsed = urlsplit(safe)
        if Path(parsed.path).name.casefold().endswith("version_manifest_v2.json"):
            sources.setdefault(launcher_path, safe)

    # Asset-index entries contain SHA-1 and size. NeoForm's native asset
    # object layout maps these deterministically to the documented object URL.
    for index_path in sorted((native_root / "assets" / "indexes").glob("*.json")):
        if index_path.is_symlink() or not index_path.is_file():
            continue
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        objects = index.get("objects", {})
        if not isinstance(objects, dict):
            continue
        for metadata in objects.values():
            if not isinstance(metadata, dict):
                continue
            digest = metadata.get("hash")
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", digest):
                continue
            digest = digest.lower()
            target = native_root / "assets" / "objects" / digest[:2] / digest
            if target.is_file() and not target.is_symlink():
                sources[target.relative_to(native_root).as_posix()] = (
                    f"https://resources.download.minecraft.net/{digest[:2]}/{digest}"
                )
    return sources


def build_external_build_input_records(cache_root: Path, profile: dict, *, baseline_sha256: str,
                                       container_image_id: str, observed_urls: list[str],
                                       acquisition_started_utc: str, acquisition_ended_utc: str,
                                       priming_command: list[str]) -> tuple[dict, dict]:
    """Build deterministic NeoForm input inventory plus per-file provenance."""
    native_spec = profile.get("external_build_inputs")
    if not isinstance(native_spec, dict) or native_spec.get("kind") != "neoformruntime":
        raise PrimingError("repository does not declare the supported NeoForm Runtime input-cache profile")
    native_root = cache_root / native_spec["cache_relative"]
    sources = _neoform_source_urls(native_root, observed_urls)
    origins = _repository_origins(*(f"Downloading {url}" for url in observed_urls))
    files = []
    total_bytes = 0
    for directory in native_spec["input_directories"]:
        root = native_root / directory
        if not root.is_dir() or root.is_symlink():
            raise PrimingError(f"NeoForm Runtime did not populate required native input directory {directory}")
        for current, dirs, names in os.walk(root, topdown=True, followlinks=False):
            base = Path(current)
            dirs.sort(key=lambda name: (name.casefold(), name))
            for name in dirs:
                child = base / name
                if child.is_symlink():
                    raise PrimingError(f"NeoForm native input cache contains a linked directory: {child}")
            for name in sorted(names, key=lambda value: (value.casefold(), value)):
                path = base / name
                if path.is_symlink() or not path.is_file():
                    raise PrimingError(f"NeoForm native input cache contains a link/special file: {path}")
                size = path.stat().st_size
                total_bytes += size
                if len(files) >= 100_000 or total_bytes > 20_000_000_000:
                    raise PrimingError("NeoForm native input cache exceeds its inventory bounds")
                rel = path.relative_to(native_root).as_posix()
                source_url = sources.get(rel)
                source_repository = None
                if source_url:
                    parsed = urlsplit(source_url)
                    source_repository = f"{parsed.scheme}://{parsed.netloc}"
                elif rel.startswith("artifacts/net/") and origins:
                    source_repository = origins[0] if len(origins) == 1 else None
                digest = _sha256_file(path)
                files.append({
                    "path": rel,
                    "size": size,
                    "sha256": digest,
                    "source_url": source_url,
                    "source_repository": source_repository,
                })
    files.sort(key=lambda item: (item["path"].casefold(), item["path"]))
    wrapper_profile = {
        "version": profile["version"],
        "distribution_sha256": profile["distribution_sha256"],
        "wrapper_jar_sha256": profile["wrapper_jar_sha256"],
        "wrapper_properties_sha256": profile["wrapper_properties_sha256"],
        "verification_policy_sha256": profile["verification_policy_sha256"],
    }
    manifest = {
        "schema_version": 1,
        "cache_relative": native_spec["cache_relative"],
        "baseline_sha256": baseline_sha256,
        "container_image_id": container_image_id,
        "gradle_wrapper": wrapper_profile,
        "files": files,
    }
    command_sha256 = hashlib.sha256(json.dumps(
        priming_command, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")).hexdigest()
    provenance_files = []
    for item in files:
        path = native_root.joinpath(*item["path"].split("/"))
        modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        provenance_files.append({
            **item,
            "local_cache_path": str(path.resolve(strict=True)),
            "acquired_at_utc": modified,
            "acquisition_time_basis": "native cache file mtime within recorded priming window",
            "baseline_sha256": baseline_sha256,
            "container_image_id": container_image_id,
            "priming_command_sha256": command_sha256,
        })
    provenance = {
        "schema_version": 1,
        "operation": "explicit_neoform_external_build_input_priming",
        "baseline_sha256": baseline_sha256,
        "container_image_id": container_image_id,
        "gradle_wrapper": wrapper_profile,
        "acquisition_window_utc": {
            "started": acquisition_started_utc,
            "ended": acquisition_ended_utc,
        },
        "priming_command": priming_command,
        "priming_command_sha256": command_sha256,
        "observed_source_urls": sorted({_safe_source_url(url) for url in observed_urls if _safe_source_url(url)}),
        "observed_repository_origins": origins,
        "files": provenance_files,
    }
    return manifest, provenance


def _repository_origins(*texts: str) -> list[str]:
    origins = set()
    for text in texts:
        for line in (text or "").splitlines():
            # Exclude documentation/help links (for example help.gradle.org)
            # and retain only URLs Gradle labels as actual HTTP requests.
            if not re.search(r"\b(?:Downloading\s+|HTTP\s+(?:GET|HEAD|POST|PUT):\s*)", line, re.I):
                continue
            for raw in URL_RE.findall(line):
                raw = raw.rstrip(".,);]}")
                try:
                    parsed = urlsplit(raw)
                    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                        continue
                    host = parsed.hostname.lower()
                    if parsed.port:
                        host = f"{host}:{parsed.port}"
                    origins.add(f"{parsed.scheme.lower()}://{host}")
                except ValueError:
                    continue
    return sorted(origins)


def _docker_path(value: Path) -> str:
    value = value.resolve(strict=True)
    rendered = str(value).replace("\\", "/")
    if "," in rendered:
        raise PrimingError("Docker bind paths containing commas are not supported")
    return rendered


def build_prime_command(docker: str, candidate: Path, cache_root: Path,
                        profile: dict, container_name: str) -> list[str]:
    source = _docker_path(candidate)
    cache = _docker_path(cache_root)
    payload = json.dumps(profile, separators=(",", ":"))
    if len(payload.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise PrimingError("Gradle priming profile exceeds its bounded size")
    return [
        docker, "run", "--rm", "--name", container_name,
        "--network", "bridge",
        "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--pids-limit", "512", "--memory", "4g", "--memory-swap", "4g", "--cpus", "2",
        "--tmpfs", "/work:rw,nosuid,nodev,size=4g,mode=1777",
        "--tmpfs", "/tmp:rw,nosuid,nodev,size=512m,mode=1777",
        "--mount", f"type=bind,source={source},target=/source,readonly",
        "--mount", f"type=bind,source={cache},target=/approved-gradle-cache",
        "--env", "JAVA_HOME=/opt/java/openjdk",
        "--env", "GRADLE_USER_HOME=/approved-gradle-cache",
        "--env", "HOME=/tmp/home", "--env", "TMPDIR=/tmp/tmp",
        "--env", "PATH=/opt/java/openjdk/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "--env", "LANG=C.UTF-8", "--env", "CI=true",
        "--entrypoint", "python3", IMAGE,
        "/opt/verifier/prime_runner.py", payload,
    ]


def _prepare_roots(baseline_value: str, candidate_value: str, cache_value: str) -> tuple[Path, Path, Path, str]:
    runs = HIVE_RUNS.resolve(strict=False)
    baseline = external_root.resolve_external_root(baseline_value, REPO_ROOT, runs)
    candidate = Path(candidate_value).resolve(strict=True)
    external_candidates = (runs / "external_candidates").resolve(strict=True)
    try:
        candidate.relative_to(external_candidates)
    except ValueError as exc:
        raise PrimingError("candidate must be a run-owned directory under HIVE_RUNS/external_candidates") from exc
    run_id = candidate.name
    if (candidate.parent != external_candidates
            or not re.fullmatch(r"[a-f0-9]{12}", run_id)
            or not (runs / run_id).is_dir()):
        raise PrimingError("candidate must use its matching 12-hex run evidence directory")
    if candidate == baseline or candidate in baseline.parents or baseline in candidate.parents:
        raise PrimingError("candidate and immutable baseline must be separate trees")

    cache_root = Path(cache_value).resolve(strict=False)
    approved = APPROVED_CACHE_ROOT.resolve(strict=False)
    try:
        cache_root.relative_to(approved)
    except ValueError as exc:
        raise PrimingError("cache root must be beneath HIVE_RUNS/approved-gradle-caches") from exc
    if cache_root.parent != approved or cache_root.name != run_id:
        raise PrimingError("cache root must be the run-matched approved cache directory")
    if cache_root == baseline or cache_root == candidate:
        raise PrimingError("cache root overlaps a protected source tree")
    evidence = runs / run_id
    for name in ("external-build-inputs.manifest.json", "external-build-inputs.provenance.json"):
        if (evidence / name).exists():
            raise PrimingError(f"run evidence already contains {name}; refusing to overwrite it")
    if cache_root.exists():
        if cache_root.is_symlink() or not cache_root.is_dir() or any(cache_root.iterdir()):
            raise PrimingError("priming requires a new, empty dedicated cache root")
    else:
        cache_root.mkdir(parents=True, exist_ok=False)

    return baseline, candidate, cache_root, run_id


def _inspect_image(docker: str) -> str:
    result = subprocess.run(
        [docker, "image", "inspect", IMAGE, "--format", "{{.Id}}"],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode:
        raise PrimingError(f"fixed verifier image is unavailable: {(result.stderr or result.stdout)[-2000:]}")
    return result.stdout.strip()


def prime_cache(baseline_value: str, candidate_value: str, cache_value: str,
                *, allow_network: bool) -> tuple[int, dict]:
    if not allow_network:
        raise PrimingError("network priming requires explicit --allow-network operator opt-in")
    baseline, candidate, cache_root, run_id = _prepare_roots(
        baseline_value, candidate_value, cache_value
    )
    evidence = (HIVE_RUNS / run_id).resolve(strict=True)
    baseline_before = external_root.tree_sha256(baseline)
    candidate_before = external_root.tree_sha256(candidate)
    profile = hive_jvm.inspect_gradle_project(candidate)
    if not isinstance(profile, dict):
        raise PrimingError("candidate is not an eligible checked-in Gradle project")
    docker = shutil.which("docker")
    if not docker:
        raise PrimingError("Docker is unavailable; no host Gradle fallback is permitted")
    image_id = _inspect_image(docker)
    container_name = f"hive-prime-{run_id}"
    command = build_prime_command(docker, candidate, cache_root, profile, container_name)
    started_utc = _utc_now()
    monotonic_start = time.monotonic()
    outer_returncode = None
    outer_stdout = outer_stderr = ""
    timed_out = False
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=DOCKER_TIMEOUT_SECONDS,
        )
        outer_returncode = completed.returncode
        outer_stdout, outer_stderr = completed.stdout or "", completed.stderr or ""
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        outer_stdout = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        outer_stderr = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        subprocess.run([docker, "rm", "-f", container_name], capture_output=True, text=True, timeout=10)

    container_report = {}
    try:
        container_report = json.loads(outer_stdout)
    except (TypeError, json.JSONDecodeError):
        container_report = {"error": "priming container returned no valid JSON report"}
    ended_utc = _utc_now()
    elapsed = round(time.monotonic() - monotonic_start, 3)

    # The run-owned candidate and immutable source must survive priming byte-for-byte.
    baseline_after = external_root.tree_sha256(baseline)
    candidate_after = external_root.tree_sha256(candidate)
    baseline_unchanged = baseline_before == baseline_after
    candidate_unchanged = candidate_before == candidate_after
    artifacts = _inventory_cache(cache_root)
    manifest_obj = {"schema_version": 1, "artifacts": artifacts}
    manifest_bytes = json.dumps(
        manifest_obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    provenance_dir = cache_root / ".hive-priming-provenance" / run_id
    provenance_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = provenance_dir / "artifacts.manifest.json"
    manifest_path.write_bytes(manifest_bytes)
    external_manifest_path = external_provenance_path = None
    external_manifest_sha256 = None
    external_input_count = 0
    external_input_bytes = 0
    container_commands = container_report.get("commands", [])
    priming_command = next((item.get("argv") for item in container_commands
                            if item.get("phase") == "resolve_documented_gradle_graph"), [])
    output_facts = container_report.get("output_facts", {})
    observed_urls = output_facts.get("observed_urls", []) if isinstance(output_facts, dict) else []
    observed_urls = [url for url in observed_urls if isinstance(url, str)]
    if profile.get("external_build_inputs") is not None:
        external_manifest, external_input_provenance = build_external_build_input_records(
            cache_root, profile, baseline_sha256=baseline_before, container_image_id=image_id,
            observed_urls=observed_urls, acquisition_started_utc=started_utc,
            acquisition_ended_utc=ended_utc, priming_command=priming_command,
        )
        external_input_provenance.update({
            "run_id": run_id,
            "baseline_root": str(baseline),
            "candidate_root": str(candidate),
            "candidate_sha256": candidate_before,
            "network_mode": "bridge",
            "network_opt_in": True,
            "cache_priming_succeeded": container_report.get("cache_priming_succeeded") is True,
            "task_outcome": container_report.get("task_outcome", {}),
        })
        external_manifest_bytes = json.dumps(
            external_manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        external_manifest_sha256 = hashlib.sha256(external_manifest_bytes).hexdigest()
        external_input_provenance["external_build_inputs_manifest_sha256"] = external_manifest_sha256
        external_manifest_path = evidence / "external-build-inputs.manifest.json"
        external_provenance_path = evidence / "external-build-inputs.provenance.json"
        external_manifest_path.write_bytes(external_manifest_bytes)
        external_provenance_path.write_text(
            json.dumps(external_input_provenance, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        # Keep a cache-local recovery copy; verification anchors to the copy in
        # run evidence, which is not inside either read-only input mount.
        (provenance_dir / "external-build-inputs.manifest.json").write_bytes(external_manifest_bytes)
        (provenance_dir / "external-build-inputs.provenance.json").write_text(
            json.dumps(external_input_provenance, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        external_input_count = len(external_manifest["files"])
        external_input_bytes = sum(row["size"] for row in external_manifest["files"])
    repository_origins = _repository_origins(*(f"Downloading {url}" for url in observed_urls))
    task_outcome = container_report.get("task_outcome", {})
    safe_output_facts = dict(output_facts) if isinstance(output_facts, dict) else {}
    safe_output_facts["observed_urls"] = sorted({_safe_source_url(url) for url in observed_urls if _safe_source_url(url)})
    safe_output_facts["diagnostic_lines"] = [
        _redact_urls(line) for line in safe_output_facts.get("diagnostic_lines", []) if isinstance(line, str)
    ]
    provenance = {
        "schema_version": 1,
        "operation": "explicit_gradle_dependency_cache_priming",
        "network_opt_in": True,
        "network_mode": "bridge",
        "started_utc": started_utc,
        "ended_utc": ended_utc,
        "elapsed_wall_seconds": elapsed,
        "repository_root": str(baseline),
        "repository_sha256": baseline_before,
        "repository_sha256_after": baseline_after,
        "candidate_root": str(candidate),
        "candidate_sha256": candidate_before,
        "candidate_sha256_after": candidate_after,
        "baseline_unchanged": baseline_unchanged,
        "candidate_unchanged": candidate_unchanged,
        "gradle_wrapper": {
            "version": profile["version"],
            "distribution": profile["distribution"],
            "distribution_sha256": profile["distribution_sha256"],
            "wrapper_jar_sha256": profile["wrapper_jar_sha256"],
            "wrapper_properties_sha256": profile["wrapper_properties_sha256"],
        },
        "java_version": container_report.get("java_version"),
        "container_image": IMAGE,
        "container_image_id": image_id,
        "container_command": command,
        "commands_executed": container_report.get("commands", []),
        "documented_full_gate_tasks": profile["full_tasks"],
        "repository_origins_observed": repository_origins,
        "repository_origin_capture": "parsed from Gradle --info output where URLs were emitted; credentials/query removed",
        "gradle_user_home": str(cache_root),
        "cache_was_empty_before_priming": True,
        "cache_priming_succeeded": container_report.get("cache_priming_succeeded") is True,
        "full_gate_passed_during_priming": task_outcome.get("full_gate_passed"),
        "priming_failure_classification": task_outcome.get("failure_classification"),
        "new_artifact_count": len(artifacts),
        "new_artifact_bytes": sum(row["size"] for row in artifacts),
        "artifact_manifest": str(manifest_path),
        "artifact_manifest_sha256": manifest_sha256,
        "external_build_inputs_manifest": str(external_manifest_path) if external_manifest_path else None,
        "external_build_inputs_manifest_sha256": external_manifest_sha256,
        "external_build_inputs_provenance": str(external_provenance_path) if external_provenance_path else None,
        "external_build_input_count": external_input_count,
        "external_build_input_bytes": external_input_bytes,
        "priming_container_returncode": outer_returncode,
        "priming_container_timed_out": timed_out,
        "priming_report": {
            key: container_report.get(key)
            for key in ("mode", "cache_priming_succeeded", "java_version", "gradle_wrapper_version",
                        "full_gate_tasks", "commands", "source_unchanged", "task_outcome", "error")
            if key in container_report
        },
        "priming_output_facts": safe_output_facts,
    }
    provenance_path = provenance_dir / "provenance.json"
    provenance_path.write_text(
        json.dumps(provenance, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    success = (
        not timed_out and outer_returncode == 0
        and container_report.get("cache_priming_succeeded") is True
        and baseline_unchanged and candidate_unchanged
    )
    result = {
        "success": success,
        "run_id": run_id,
        "cache_root": str(cache_root),
        "provenance_path": str(provenance_path),
        "artifact_manifest_path": str(manifest_path),
        "artifact_manifest_sha256": manifest_sha256,
        "new_artifact_count": len(artifacts),
        "java_version": container_report.get("java_version"),
        "gradle_version": profile["version"],
        "full_gate_tasks": profile["full_tasks"],
        "repositories_contacted": repository_origins,
        "baseline_unchanged": baseline_unchanged,
        "candidate_unchanged": candidate_unchanged,
        "elapsed_wall_seconds": elapsed,
        "failure": _redact_urls(container_report.get("error") or "\n".join(safe_output_facts.get("diagnostic_lines", [])) or outer_stderr[-4000:]),
    }
    return (0 if success else 1), result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Explicitly prime an isolated Gradle dependency cache.")
    parser.add_argument("--baseline-root", required=True, help="immutable external repository baseline")
    parser.add_argument("--candidate-root", required=True, help="run-owned snapshot under HIVE_RUNS/external_candidates")
    parser.add_argument("--cache-root", required=True, help="new run-matched directory under HIVE_RUNS/approved-gradle-caches")
    parser.add_argument("--allow-network", action="store_true", required=True,
                        help="operator opt-in: the isolated priming container uses Docker bridge networking")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        status, result = prime_cache(
            args.baseline_root, args.candidate_root, args.cache_root,
            allow_network=args.allow_network,
        )
    except Exception as exc:
        result = {"success": False, "error": f"{type(exc).__name__}: {exc}"}
        status = 1
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    return status


if __name__ == "__main__":
    raise SystemExit(main())

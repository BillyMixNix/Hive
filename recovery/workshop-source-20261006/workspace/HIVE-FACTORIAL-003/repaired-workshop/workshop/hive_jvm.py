"""Host-side validation and frozen inputs for isolated Gradle verification."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import stat
from pathlib import Path

from .external_root import _copy_file, _is_reparse_or_link


MAX_FROZEN_TESTS = 16
MAX_FROZEN_TEST_BYTES = 256_000
MAX_FROZEN_TOTAL_BYTES = 1_000_000
MAX_WRAPPER_JAR_BYTES = 8_000_000
GRADLE_DISTRIBUTION_RE = re.compile(r"^gradle-([0-9]+(?:\.[0-9]+){1,3})-(bin|all)\.zip$")
GRADLE_TEST_CLASS_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*$")
GRADLE_TASK_RE = re.compile(r"^:?[A-Za-z][A-Za-z0-9_:-]*$")
GRADLE_DOC_FLAGS = {"--console=plain", "--no-daemon", "--offline", "--rerun-tasks", "--no-build-cache"}
MAX_EXTERNAL_INPUT_FILES = 100_000
MAX_EXTERNAL_INPUT_BYTES = 20_000_000_000
TRUSTED_GAME_TEST_OUTPUTS = {
    "gameTestServer": "run-gametest",
    "questTestServer": "run-questtest",
}


class JVMProfileError(ValueError):
    """An external repository is not safe/ready for the pinned JVM profile."""


def _groovy_tokens(text: str) -> list[tuple[str, str]]:
    """Tokenize only enough Groovy syntax to recognize literal run directories.

    Comments and strings are atomic, so route-like text in either cannot be
    mistaken for executable Gradle configuration.
    """
    tokens: list[tuple[str, str]] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char.isspace():
            index += 1
            continue
        if text.startswith("//", index):
            end = text.find("\n", index + 2)
            index = len(text) if end < 0 else end + 1
            continue
        if text.startswith("/*", index):
            end = text.find("*/", index + 2)
            if end < 0:
                return []
            index = end + 2
            continue
        if char == "/":
            # Groovy slashy regex literals are context-sensitive. Refuse to
            # derive output exclusions from an ambiguous script instead of
            # accidentally treating regex text as executable configuration.
            return []
        if char in "'\"":
            triple = text.startswith(char * 3, index)
            delimiter = char * (3 if triple else 1)
            index += len(delimiter)
            value: list[str] = []
            while index < len(text) and not text.startswith(delimiter, index):
                if text[index] == "\\" and index + 1 < len(text):
                    value.append(text[index + 1])
                    index += 2
                else:
                    value.append(text[index])
                    index += 1
            if index >= len(text):
                return []
            tokens.append(("string", "".join(value)))
            index += len(delimiter)
            continue
        if char.isalpha() or char in "_$":
            end = index + 1
            while end < len(text) and (text[end].isalnum() or text[end] in "_$"):
                end += 1
            tokens.append(("identifier", text[index:end]))
            index = end
            continue
        tokens.append(("symbol", char))
        index += 1
    return tokens


def _declared_runtime_output_dirs(root: Path) -> list[str]:
    """Return only host-approved paths declared in NeoForge's named run blocks."""
    build = root / "build.gradle"
    if not build.exists():
        return []
    info = build.lstat()
    if _is_reparse_or_link(build, info) or not stat.S_ISREG(info.st_mode) or info.st_size > 1_000_000:
        raise JVMProfileError("build.gradle must be a bounded regular file for runtime-output discovery")
    try:
        tokens = _groovy_tokens(build.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise JVMProfileError(f"cannot inspect Gradle runtime-output configuration: {exc}") from exc
    if not tokens:
        return []

    stack: list[tuple[str, tuple[str, ...], int]] = []
    declarations: dict[str, list[str]] = {name: [] for name in TRUSTED_GAME_TEST_OUTPUTS}
    for index, (kind, value) in enumerate(tokens):
        if kind == "symbol" and value == "{":
            previous = tokens[index - 1] if index else ("", "")
            block_name = previous[1] if previous[0] == "identifier" else ""
            ancestors = tuple(item[0] for item in stack)
            stack.append((block_name, ancestors, index))
        elif kind == "symbol" and value == "}" and stack:
            block_name, ancestors, start = stack.pop()
            if block_name not in TRUSTED_GAME_TEST_OUTPUTS or not {"neoForge", "runs"}.issubset(ancestors):
                continue
            body = tokens[start + 1:index]
            assignment_positions = [pos for pos, token in enumerate(body)
                                    if token == ("identifier", "gameDirectory")]
            expected = TRUSTED_GAME_TEST_OUTPUTS[block_name]
            needle = [
                ("identifier", "gameDirectory"), ("symbol", "="),
                ("identifier", "project"), ("symbol", "."),
                ("identifier", "file"), ("symbol", "("),
                ("string", expected), ("symbol", ")"),
            ]
            matches = [pos for pos in assignment_positions
                       if body[pos:pos + len(needle)] == needle]
            if len(assignment_positions) == 1 and len(matches) == 1:
                declarations[block_name].append(expected)

    # Duplicate or conflicting declarations are ambiguous and therefore not
    # eligible for source-digest exclusion.
    return [TRUSTED_GAME_TEST_OUTPUTS[name] for name in TRUSTED_GAME_TEST_OUTPUTS
            if declarations[name] == [TRUSTED_GAME_TEST_OUTPUTS[name]]]


def _external_build_input_profile(root: Path) -> dict | None:
    """Detect NeoForm Runtime from checked-in build declarations, not project names."""
    marker = re.compile(r"net\.neoforged\.moddev(?:legacy)?|neoformruntime", re.IGNORECASE)
    for name in ("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"):
        path = root / name
        if not path.exists():
            continue
        info = path.lstat()
        if _is_reparse_or_link(path, info) or not stat.S_ISREG(info.st_mode) or info.st_size > 1_000_000:
            raise JVMProfileError(f"Gradle build declaration is linked, non-regular, or too large: {name}")
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise JVMProfileError(f"cannot inspect Gradle build declaration {name}: {exc}") from exc
        if marker.search(text):
            # ModDevGradle invokes NeoForm Runtime with this native cache home.
            # External inputs are the native artifact and Mojang asset trees;
            # generated intermediate_results stay on the writable verifier tmpfs.
            return {
                "kind": "neoformruntime",
                "cache_relative": "caches/neoformruntime",
                "input_directories": ["artifacts", "assets"],
            }
    return None


def _documented_gradle_gate(root: Path) -> tuple[list[str], str | None]:
    """Read a fixed task vector from VERIFICATION.md without executing shell text."""
    policy = root / "VERIFICATION.md"
    if not policy.exists():
        return ["check"], None
    info = policy.lstat()
    if _is_reparse_or_link(policy, info) or not stat.S_ISREG(info.st_mode) or info.st_size > 128_000:
        raise JVMProfileError("VERIFICATION.md must be a bounded regular file for Gradle gate discovery")
    try:
        raw = policy.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise JVMProfileError(f"cannot read Gradle verification policy: {exc}") from exc
    heading = re.search(r"(?im)^#{1,3}\s+Exact commands\s*$", text)
    if not heading:
        raise JVMProfileError("VERIFICATION.md exists but has no supported 'Exact commands' section")
    fence = re.search(r"```[^\r\n]*\r?\n(.*?)```", text[heading.end():], re.DOTALL)
    if not fence:
        raise JVMProfileError("VERIFICATION.md exact-command section has no fenced command block")
    for line in fence.group(1).splitlines():
        line = line.strip()
        if not line:
            continue
        wrapper = re.match(r"^(?:\.[\\/])?gradlew(?:\.bat)?(?=\s|$)", line, re.IGNORECASE)
        if not wrapper:
            continue
        try:
            argv = ["gradlew.bat", *shlex.split(line[wrapper.end():], posix=True)]
        except ValueError as exc:
            raise JVMProfileError(f"cannot tokenize documented Gradle gate safely: {exc}") from exc
        tasks = []
        for token in argv[1:]:
            if token in GRADLE_DOC_FLAGS:
                continue
            if token.startswith("-Dorg.gradle.jvmargs="):
                # The verifier supplies its own bounded JVM heap setting.
                continue
            if token.startswith("-") or not GRADLE_TASK_RE.fullmatch(token):
                raise JVMProfileError("documented Gradle gate contains an unsupported option or non-task argument")
            tasks.append(token)
        if not tasks:
            raise JVMProfileError("documented Gradle gate has no task identifiers")
        return tasks, hashlib.sha256(raw).hexdigest()
    raise JVMProfileError("VERIFICATION.md exact-command section contains no checked-in Gradle wrapper invocation")


def _safe_test_path(value: object) -> str:
    path = str(value or "").replace("\\", "/").strip()
    parts = path.split("/")
    if (not path or path.startswith("/") or re.match(r"^[A-Za-z]:", path)
            or any(part in {"", ".", ".."} for part in parts)
            or parts[:3] != ["src", "test", "java"]
            or not path.endswith(".java")):
        raise JVMProfileError("frozen JUnit test path must be a safe src/test/java/**/*.java path")
    return "/".join(parts)


def inspect_gradle_project(root: Path) -> dict | None:
    """Statically identify an external Gradle project and its pinned wrapper."""
    root = Path(root).resolve(strict=True)
    try:
        top = {item.name.casefold() for item in root.iterdir()}
    except OSError as exc:
        raise JVMProfileError(f"cannot inspect external project: {type(exc).__name__}: {exc}") from exc
    markers = {"gradlew", "gradlew.bat", "build.gradle", "build.gradle.kts",
               "settings.gradle", "settings.gradle.kts"}
    java_sources = any(root.rglob("*.java"))
    if not (top & markers) and not java_sources:
        return None
    if top & {"pom.xml"} and not (top & markers):
        raise JVMProfileError("Maven repositories are not supported by the isolated Gradle profile")

    wrapper = root / "gradle" / "wrapper"
    properties = wrapper / "gradle-wrapper.properties"
    jar = wrapper / "gradle-wrapper.jar"
    if not (root / "gradlew").is_file() and not (root / "gradlew.bat").is_file():
        raise JVMProfileError("Gradle project is missing its checked-in gradlew/gradlew.bat wrapper")
    for path, label in ((properties, "gradle-wrapper.properties"), (jar, "gradle-wrapper.jar")):
        try:
            info = path.lstat()
        except OSError as exc:
            raise JVMProfileError(f"Gradle project is missing {label}: {exc}") from exc
        if _is_reparse_or_link(path, info) or not stat.S_ISREG(info.st_mode):
            raise JVMProfileError(f"Gradle wrapper {label} must be a regular in-repository file")
        if label == "gradle-wrapper.jar" and info.st_size > MAX_WRAPPER_JAR_BYTES:
            raise JVMProfileError("Gradle wrapper JAR exceeds the static preflight size limit")
    for launcher in (root / "gradlew", root / "gradlew.bat"):
        if launcher.exists():
            info = launcher.lstat()
            if _is_reparse_or_link(launcher, info) or not stat.S_ISREG(info.st_mode):
                raise JVMProfileError("Gradle wrapper launcher must be a regular in-repository file")

    try:
        text = properties.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise JVMProfileError(f"cannot read Gradle wrapper properties: {exc}") from exc
    if len(text) > 32_000:
        raise JVMProfileError("Gradle wrapper properties exceed the size limit")
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "!")) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        # Java properties escapes used in the checked-in distribution URL.
        value = re.sub(r"\\([:=# !\\])", r"\1", value.strip())
        values[key.strip()] = value
    url = values.get("distributionUrl", "")
    checksum = values.get("distributionSha256Sum", "")
    filename = url.rsplit("/", 1)[-1]
    match = GRADLE_DISTRIBUTION_RE.fullmatch(filename)
    if (not url.startswith("https://services.gradle.org/distributions/") or not match
            or not re.fullmatch(r"[0-9a-fA-F]{64}", checksum)):
        raise JVMProfileError(
            "wrapper must pin an official Gradle distribution URL and distributionSha256Sum"
        )
    full_tasks, verification_policy_sha256 = _documented_gradle_gate(root)
    return {
        "version": match.group(1),
        "distribution": filename,
        "distribution_sha256": checksum.lower(),
        "wrapper_jar_sha256": hashlib.sha256(jar.read_bytes()).hexdigest(),
        "wrapper_properties_sha256": hashlib.sha256(properties.read_bytes()).hexdigest(),
        "full_tasks": full_tasks,
        "verification_policy_sha256": verification_policy_sha256,
        "external_build_inputs": _external_build_input_profile(root),
        "runtime_output_dirs": _declared_runtime_output_dirs(root),
    }


def freeze_junit_tests(root: Path, specs: list[dict] | None) -> list[dict]:
    """Validate acceptance-test requests and freeze their source bytes in a run.

    Test source is supplied explicitly by the build requester. It is not read
    from arbitrary host paths and is never added to worker write authority.
    """
    root = Path(root).resolve(strict=True)
    specs = specs or []
    if not isinstance(specs, list) or len(specs) > MAX_FROZEN_TESTS:
        raise JVMProfileError(f"frozen_junit_tests must contain at most {MAX_FROZEN_TESTS} tests")
    frozen = []
    total = 0
    seen_paths, seen_classes = set(), set()
    for item in specs:
        if not isinstance(item, dict):
            raise JVMProfileError("each frozen JUnit test must be an object")
        path = _safe_test_path(item.get("path"))
        class_name = str(item.get("class_name") or "").strip()
        expected_cases = item.get("expected_cases")
        source = item.get("source")
        if not GRADLE_TEST_CLASS_RE.fullmatch(class_name):
            raise JVMProfileError("frozen JUnit class_name must be a fully qualified Java class name")
        expected_path_class = ".".join(path[len("src/test/java/"):-len(".java")].split("/"))
        if class_name != expected_path_class:
            raise JVMProfileError("frozen JUnit class_name must match its src/test/java path")
        if isinstance(expected_cases, bool) or not isinstance(expected_cases, int) or not 1 <= expected_cases <= 5000:
            raise JVMProfileError("frozen JUnit expected_cases must be an integer from 1 to 5000")
        if not isinstance(source, str) or not source.strip():
            raise JVMProfileError("frozen JUnit test source is required")
        encoded = source.encode("utf-8")
        if len(encoded) > MAX_FROZEN_TEST_BYTES:
            raise JVMProfileError("a frozen JUnit test exceeds the per-file size limit")
        total += len(encoded)
        if total > MAX_FROZEN_TOTAL_BYTES:
            raise JVMProfileError("frozen JUnit tests exceed the total size limit")
        if path in seen_paths or class_name in seen_classes:
            raise JVMProfileError("frozen JUnit test paths and class names must be unique")
        candidate_file = root.joinpath(*path.split("/"))
        if candidate_file.exists():
            if candidate_file.is_symlink() or not candidate_file.is_file():
                raise JVMProfileError(f"frozen JUnit destination is not a regular source file: {path}")
            if hashlib.sha256(candidate_file.read_bytes()).hexdigest() != hashlib.sha256(encoded).hexdigest():
                raise JVMProfileError(f"frozen JUnit source conflicts with immutable baseline file: {path}")
        seen_paths.add(path)
        seen_classes.add(class_name)
        frozen.append({
            "path": path,
            "class_name": class_name,
            "expected_cases": expected_cases,
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "source": source,
        })
    return frozen


def store_frozen_junit_tests(specs: list[dict], run_dir: Path) -> list[dict]:
    """Persist frozen source under run evidence; return content-free metadata."""
    run_dir = Path(run_dir).resolve(strict=False)
    frozen_dir = run_dir / "frozen-junit"
    if frozen_dir.exists():
        raise JVMProfileError("run-owned frozen-test directory already exists")
    frozen_dir.mkdir(parents=True)
    metadata = []
    try:
        for item in specs:
            artifact = frozen_dir / item["path"]
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(item["source"], encoding="utf-8", newline="\n")
            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
            if digest != item["sha256"]:
                raise JVMProfileError("frozen JUnit source changed while being stored")
            metadata.append({key: item[key] for key in ("path", "class_name", "expected_cases", "sha256")}
                            | {"artifact_path": str(artifact.resolve(strict=True)),
                               "artifact_root": str(frozen_dir.resolve(strict=True))})
    except Exception:
        shutil.rmtree(frozen_dir, ignore_errors=True)
        raise
    return metadata


def verify_frozen_artifacts(specs: list[dict], run_dir: Path) -> bool:
    if not specs:
        return True
    run_dir = Path(run_dir).resolve(strict=True)
    allowed = (run_dir / "frozen-junit").resolve(strict=True)
    try:
        for item in specs:
            _read_frozen_artifact(item, run_dir)
    except (KeyError, OSError, RuntimeError, TypeError, ValueError):
        return False
    return True


def _read_frozen_artifact(item: dict, run_dir: Path) -> bytes:
    run_dir = Path(run_dir).resolve(strict=True)
    allowed_raw = run_dir / "frozen-junit"
    if _is_reparse_or_link(allowed_raw, allowed_raw.lstat()):
        raise JVMProfileError("run-owned frozen-test directory is aliased by a link or junction")
    allowed = allowed_raw.resolve(strict=True)
    original = Path(item["artifact_path"])
    original_root = Path(item["artifact_root"])
    if original.is_symlink() or _is_reparse_or_link(original_root, original_root.lstat()):
        raise JVMProfileError("frozen JUnit artifact path is aliased by a link or junction")
    expected_root = original_root.resolve(strict=True)
    if expected_root != allowed:
        raise JVMProfileError("frozen JUnit artifact root is not the run-owned frozen-test directory")
    if _is_reparse_or_link(original, original.lstat()):
        raise JVMProfileError("frozen JUnit artifact is aliased by a link or junction")
    path = original.resolve(strict=True)
    path.relative_to(allowed)
    current = allowed
    for part in path.relative_to(allowed).parts:
        current = current / part
        info = current.lstat()
        if _is_reparse_or_link(current, info):
            raise JVMProfileError("frozen JUnit artifact path contains a link or junction")
    if not stat.S_ISREG(path.lstat().st_mode):
        raise JVMProfileError("frozen JUnit artifact is not a regular file")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FROZEN_TEST_BYTES:
            raise JVMProfileError("frozen JUnit artifact is not a bounded regular file")
        data = handle.read(MAX_FROZEN_TEST_BYTES + 1)
        after = os.fstat(handle.fileno())
    if len(data) > MAX_FROZEN_TEST_BYTES or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise JVMProfileError("frozen JUnit artifact changed or exceeded its bound while being read")
    if hashlib.sha256(data).hexdigest() != item["sha256"]:
        raise JVMProfileError("frozen JUnit artifact hash no longer matches its immutable manifest")
    return data


def _gradle_user_home() -> Path:
    configured = os.environ.get("GRADLE_USER_HOME")
    if configured:
        root = Path(configured).expanduser()
    else:
        home = os.environ.get("USERPROFILE") or os.environ.get("HOME")
        if not home:
            raise JVMProfileError("GRADLE_USER_HOME is unset and no user home is available")
        root = Path(home) / ".gradle"
    try:
        return root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise JVMProfileError(f"Gradle user home is unavailable: {exc}") from exc


def gradle_cache_locations(profile: dict) -> tuple[Path, Path]:
    """Resolve only the dependency cache and exact wrapper-distribution cache."""
    root = _gradle_user_home()
    modules = root / "caches" / "modules-2"
    distributions = root / "wrapper" / "dists" / Path(profile["distribution"]).stem
    for path, label in ((modules, "Gradle module dependency cache"),
                        (distributions, "exact checked-in Gradle wrapper distribution cache")):
        try:
            info = path.lstat()
        except OSError as exc:
            raise JVMProfileError(f"{label} is unavailable: {exc}") from exc
        if _is_reparse_or_link(path, info) or not stat.S_ISDIR(info.st_mode):
            raise JVMProfileError(f"{label} must be a real directory")
    available = False
    for child in distributions.iterdir():
        if child.is_symlink() or not child.is_dir():
            continue
        distribution = child / f"gradle-{profile['version']}"
        executable = distribution / "bin" / "gradle"
        if (distribution.is_dir() and not distribution.is_symlink()
                and executable.is_file() and not executable.is_symlink()):
            available = True
            break
    if not available:
        raise JVMProfileError(
            f"the exact Gradle {profile['version']} wrapper distribution is not cached; network fallback is disabled"
        )
    if "," in str(modules) or "," in str(distributions):
        raise JVMProfileError("Gradle cache paths containing commas cannot be safely mounted")
    return modules, distributions


def external_build_input_locations(profile: dict, *, baseline_sha256: str,
                                    container_image_id: str) -> tuple[Path, Path] | None:
    """Validate the run-frozen native input manifest and return assets/artifacts.

    The manifest is anchored in the sibling run-evidence directory, while the
    data itself remains in NeoForm Runtime's native Gradle-user-home layout.
    Exact inventory matching rejects both tampering and unmanifested files.
    """
    spec = profile.get("external_build_inputs") if isinstance(profile, dict) else None
    if spec is None:
        return None
    if (not isinstance(spec, dict) or spec.get("kind") != "neoformruntime"
            or spec.get("cache_relative") != "caches/neoformruntime"
            or spec.get("input_directories") != ["artifacts", "assets"]):
        raise JVMProfileError("unsupported external build-input cache profile")
    if not re.fullmatch(r"[0-9a-f]{64}", str(baseline_sha256 or "")):
        raise JVMProfileError("external Gradle verification requires the immutable baseline SHA-256")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(container_image_id or "")):
        raise JVMProfileError("external Gradle verification requires the inspected verifier image digest")

    gradle_home = _gradle_user_home()
    cache_root = gradle_home.resolve(strict=True)
    run_id = cache_root.name
    if (not re.fullmatch(r"[a-f0-9]{12}", run_id)
            or cache_root.parent.name != "approved-gradle-caches"
            or cache_root.parent.parent.name != "hive_runs"):
        raise JVMProfileError("external Gradle cache must be the run-matched approved cache under HIVE_RUNS")
    evidence = cache_root.parent.parent / run_id
    if not evidence.is_dir() or evidence.is_symlink():
        raise JVMProfileError("run evidence for the approved external-input cache is missing or linked")
    manifest_path = evidence / "external-build-inputs.manifest.json"
    provenance_path = evidence / "external-build-inputs.provenance.json"
    for path, label in ((manifest_path, "external-input manifest"),
                        (provenance_path, "external-input provenance")):
        try:
            info = path.lstat()
        except OSError as exc:
            raise JVMProfileError(f"{label} is missing: {exc}") from exc
        if _is_reparse_or_link(path, info) or not stat.S_ISREG(info.st_mode) or info.st_size > 32_000_000:
            raise JVMProfileError(f"{label} must be a bounded regular file")
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JVMProfileError(f"external-input manifest/provenance is invalid: {exc}") from exc

    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    expected_profile = {
        "version": profile.get("version"),
        "distribution_sha256": profile.get("distribution_sha256"),
        "wrapper_jar_sha256": profile.get("wrapper_jar_sha256"),
        "wrapper_properties_sha256": profile.get("wrapper_properties_sha256"),
        "verification_policy_sha256": profile.get("verification_policy_sha256"),
    }
    if (manifest.get("schema_version") != 1
            or manifest.get("cache_relative") != "caches/neoformruntime"
            or manifest.get("baseline_sha256") != baseline_sha256
            or manifest.get("container_image_id") != container_image_id
            or manifest.get("gradle_wrapper") != expected_profile
            or provenance.get("external_build_inputs_manifest_sha256") != manifest_hash
            or provenance.get("baseline_sha256") != baseline_sha256
            or provenance.get("container_image_id") != container_image_id
            or provenance.get("cache_priming_succeeded") is not True):
        raise JVMProfileError("external build-input manifest is not bound to this baseline, wrapper, image, and priming run")

    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries or len(entries) > MAX_EXTERNAL_INPUT_FILES:
        raise JVMProfileError("external build-input manifest has no bounded file inventory")
    expected: dict[str, tuple[int, str]] = {}
    total = 0
    for item in entries:
        if not isinstance(item, dict):
            raise JVMProfileError("external build-input manifest contains a malformed entry")
        rel = item.get("path")
        parts = rel.split("/") if isinstance(rel, str) else []
        if (not parts or parts[0] not in {"artifacts", "assets"}
                or any(part in {"", ".", ".."} for part in parts)
                or "\\" in rel or rel.startswith("/")
                or not isinstance(item.get("size"), int) or item["size"] < 0
                or not re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", "")))
                or rel in expected):
            raise JVMProfileError("external build-input manifest contains an unsafe or duplicate entry")
        total += item["size"]
        if total > MAX_EXTERNAL_INPUT_BYTES:
            raise JVMProfileError("external build-input manifest exceeds its size limit")
        expected[rel] = (item["size"], item["sha256"])

    native_root = cache_root / "caches" / "neoformruntime"
    actual: dict[str, Path] = {}
    for directory in ("artifacts", "assets"):
        start = native_root / directory
        try:
            start_info = start.lstat()
        except OSError as exc:
            raise JVMProfileError(f"NeoForm Runtime {directory} cache is missing: {exc}") from exc
        if _is_reparse_or_link(start, start_info) or not stat.S_ISDIR(start_info.st_mode):
            raise JVMProfileError(f"NeoForm Runtime {directory} cache must be a real directory")
        for current, dirs, files in os.walk(start, topdown=True, followlinks=False):
            base = Path(current)
            for name in dirs:
                child = base / name
                if _is_reparse_or_link(child, child.lstat()):
                    raise JVMProfileError("NeoForm Runtime external-input cache contains a linked directory")
            for name in files:
                child = base / name
                info = child.lstat()
                if _is_reparse_or_link(child, info) or not stat.S_ISREG(info.st_mode):
                    raise JVMProfileError("NeoForm Runtime external-input cache contains a link or special file")
                actual[child.relative_to(native_root).as_posix()] = child
    if set(actual) != set(expected):
        raise JVMProfileError("NeoForm Runtime external-input cache is missing or contains unmanifested files")
    for rel, path in actual.items():
        expected_size, expected_hash = expected[rel]
        if path.stat().st_size != expected_size:
            raise JVMProfileError(f"manifested external build input size changed: {rel}")
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected_hash:
            raise JVMProfileError(f"manifested external build input hash changed: {rel}")
    assets = native_root / "assets"
    artifacts = native_root / "artifacts"
    if any("," in str(path) for path in (assets, artifacts)):
        raise JVMProfileError("external build-input cache paths containing commas cannot be mounted safely")
    return assets, artifacts


def copy_external_verification_input(root: Path, destination: Path, frozen_tests: list[dict]) -> None:
    """Copy source plus frozen tests; reject links, escapes, and special files."""
    from .external_root import _inventory

    root = Path(root).resolve(strict=True)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    inventory = _inventory(root)
    for source, rel, info in inventory:
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.name.casefold() in {".env", "credentials", "credentials.json", "secrets.json"}:
            continue
        if source.suffix.casefold() in {".pem", ".key", ".p12", ".pfx", ".db", ".sqlite", ".sqlite3"}:
            continue
        _copy_file(source, target, root, info)
        try:
            os.chmod(target, stat.S_IMODE(info.st_mode) | stat.S_IWUSR)
        except OSError:
            pass
    for item in frozen_tests:
        data = _read_frozen_artifact(item, Path(item["artifact_root"]).parent)
        target = destination / item["path"]
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != item["sha256"]:
            raise JVMProfileError(f"frozen JUnit test conflicts with candidate source: {item['path']}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

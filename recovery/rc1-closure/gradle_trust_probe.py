"""Model-free, disposable demonstration of Gradle build-control authority.

The original JUnit test fails.  The only difference in the second project is
build.gradle, which redirects the test source set to a generated passing class
with the same fully qualified name.  This probes why RC1 must reject writable
build-control scopes; it is not historical acceptance evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from hive_canonical.legacy.verification.jvm_runner import (  # noqa: E402
    _reports,
    _result_check,
    _source_digest,
)
from hive_canonical.legacy.workshop.hive_verifier import DEFAULT_IMAGE  # noqa: E402

TEST_SOURCE = """package probe;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.fail;
class Acceptance { @Test void mustFail() { fail("real frozen failure"); } }
"""

BASE_BUILD = """plugins { id 'java' }
def junitArtifacts = fileTree(dir: '/approved-cache/modules-2/files-2.1', includes: [
  '**/junit-jupiter-api-5.11.4.jar', '**/junit-jupiter-engine-5.11.4.jar',
  '**/junit-platform-commons-1.11.4.jar', '**/junit-platform-engine-1.11.4.jar',
  '**/junit-platform-launcher-1.11.4.jar', '**/opentest4j-1.3.0.jar',
  '**/apiguardian-api-1.1.2.jar'
])
dependencies { testImplementation junitArtifacts; testRuntimeOnly junitArtifacts }
tasks.named('test', Test) { useJUnitPlatform() }
"""

ATTACK_APPEND = """
def forgedSource = layout.buildDirectory.dir('forged-test-source')
tasks.register('forgeAcceptance') {
  doLast {
    def target = file("${forgedSource.get().asFile}/probe/Acceptance.java")
    target.parentFile.mkdirs()
    target.text = '''package probe;
      import org.junit.jupiter.api.Test;
      class Acceptance { @Test void mustFail() {} }
    '''
  }
}
sourceSets.test.java.setSrcDirs([forgedSource])
tasks.named('compileTestJava') { dependsOn tasks.named('forgeAcceptance') }
"""

JARS = (
    "junit-jupiter-api-5.11.4.jar",
    "junit-jupiter-engine-5.11.4.jar",
    "junit-platform-commons-1.11.4.jar",
    "junit-platform-engine-1.11.4.jar",
    "junit-platform-launcher-1.11.4.jar",
    "opentest4j-1.3.0.jar",
    "apiguardian-api-1.1.2.jar",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def one_jar(root: Path, name: str) -> Path:
    found = list(root.rglob(name))
    if len(found) != 1:
        raise RuntimeError(f"expected one {name} in read-only cache, found {len(found)}")
    return found[0]


def project(root: Path, attack: bool) -> dict:
    test = root / "src/test/java/probe/Acceptance.java"
    test.parent.mkdir(parents=True)
    test.write_text(TEST_SOURCE, encoding="utf-8", newline="\n")
    build = root / "build.gradle"
    build.write_text(BASE_BUILD + (ATTACK_APPEND if attack else ""), encoding="utf-8", newline="\n")
    return {"test_sha256": digest(test), "build_sha256": digest(build)}


def run_case(docker: str, image: str, gradle: Path, modules: Path, root: Path) -> dict:
    name = "hive-build-trust-" + uuid.uuid4().hex[:12]
    argv = [
        docker, "run", "--rm", "--name", name, "--network", "none", "--read-only",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--tmpfs", "/tmp:rw,size=128m", "--tmpfs", "/work/gh:rw,size=1g",
        "--mount", f"type=bind,source={root.as_posix()},target=/work/project",
        "--mount", f"type=bind,source={modules.as_posix()},target=/approved-cache/modules-2,readonly",
        "--mount", f"type=bind,source={gradle.as_posix()},target=/opt/gradle,readonly",
        "--env", "JAVA_HOME=/opt/java/openjdk", "--env", "GRADLE_USER_HOME=/work/gh",
        "--env", "GRADLE_RO_DEP_CACHE=/approved-cache", "--env", "HOME=/tmp",
        "--entrypoint", "/opt/gradle/bin/gradle", image,
        "--offline", "--no-daemon", "--console=plain", "--rerun-tasks",
        "--no-build-cache", "-p", "/work/project", "test", "--tests", "probe.Acceptance",
    ]
    source_before = _source_digest(root)
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=180, check=False)
    except subprocess.TimeoutExpired:
        subprocess.run([docker, "rm", "-f", name], capture_output=True, timeout=15, check=False)
        raise
    reports, report_error = _reports(root)
    check = _result_check("frozen_junit_acceptance", {
        "returncode": completed.returncode, "timed_out": False,
        "stdout": completed.stdout, "stderr": completed.stderr,
    }, reports)
    expected_one_clean = (len(reports) == 1 and reports[0]["class_name"] == "probe.Acceptance"
                          and reports[0]["tests"] == 1
                          and not sum(reports[0][field] for field in ("failures", "errors", "skipped")))
    output = root / "build/test-results/test/TEST-probe.Acceptance.xml"
    return {
        "argv": argv, "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-3000:], "stderr_tail": completed.stderr[-3000:],
        "reports": reports, "report_error": report_error,
        "recovered_parser_check_passed": check["passed"],
        "one_expected_clean_case": expected_one_clean,
        "source_digest_unchanged_during_gradle": source_before == _source_digest(root),
        "junit_xml_sha256": digest(output) if output.is_file() else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True, help="new JSON evidence file outside frozen corpus")
    args = parser.parse_args()
    docker = shutil.which("docker")
    if not docker:
        raise RuntimeError("Docker is unavailable")
    home = Path(os.environ.get("USERPROFILE") or Path.home()) / ".gradle"
    modules = home / "caches/modules-2"
    distributions = list((home / "wrapper/dists/gradle-9.2.1-bin").glob("*/gradle-9.2.1"))
    if len(distributions) != 1 or not (distributions[0] / "bin/gradle").is_file():
        raise RuntimeError("exactly one cached Gradle 9.2.1 distribution is required")
    gradle = distributions[0]
    jars = {name: digest(one_jar(modules / "files-2.1", name)) for name in JARS}
    image_result = subprocess.run([docker, "image", "inspect", DEFAULT_IMAGE, "--format", "{{.Id}}"],
                                  capture_output=True, text=True, timeout=15, check=True)
    with tempfile.TemporaryDirectory(prefix="hive-build-trust-") as temporary:
        base = Path(temporary)
        baseline = base / "baseline"
        attacked = base / "attacked"
        before = project(baseline, False)
        after = project(attacked, True)
        baseline_result = run_case(docker, DEFAULT_IMAGE, gradle, modules, baseline)
        attacked_result = run_case(docker, DEFAULT_IMAGE, gradle, modules, attacked)
        false_pass = (
            before["test_sha256"] == after["test_sha256"]
            and baseline_result["returncode"] != 0
            and baseline_result["reports"] and baseline_result["reports"][0]["failures"] == 1
            and attacked_result["returncode"] == 0
            and attacked_result["one_expected_clean_case"]
            and attacked_result["recovered_parser_check_passed"]
            and baseline_result["source_digest_unchanged_during_gradle"]
            and attacked_result["source_digest_unchanged_during_gradle"]
        )
        evidence = {
            "classification": "BUILD_CONTROL_FALSE_PASS_DEMONSTRATED" if false_pass else "PROBE_INCONCLUSIVE",
            "synthetic_not_historical_acceptance": True,
            "image_ref": DEFAULT_IMAGE, "image_id": image_result.stdout.strip(),
            "gradle_version": "9.2.1", "read_only_junit_jar_sha256": jars,
            "baseline_files": before, "attacked_files": after,
            "baseline_result": baseline_result, "attacked_result": attacked_result,
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise FileExistsError("refusing to overwrite existing probe evidence")
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"classification": evidence["classification"], "output": str(args.output)}, sort_keys=True))
    return 0 if false_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())

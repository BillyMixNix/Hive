"""Legacy test scratch-path compatibility; assertions and source stay unchanged.

Only test modules and frozen benchmark helpers redirect _tmp_* fixture artifacts
beneath the tests directory. Other production modules retain pathlib.Path. Source
and tests are still mounted read-only. This is not an independent score oracle.
"""
import os
import sys
from pathlib import Path, PosixPath
import tempfile


def fixture_path_class(subject, scratch):
    tests = Path(subject).resolve() / "tests"
    scratch = Path(scratch).resolve()

    def redirect(path):
        try:
            relative = Path(path).absolute().relative_to(tests)
        except ValueError:
            return path
        if relative.parts and relative.parts[0].startswith("_tmp_"):
            return Path(scratch, *relative.parts)
        return path

    class FixturePath(PosixPath):
        def __new__(cls, *args, **kwargs):
            original = Path(*args)
            mapped = redirect(original)
            if mapped != original:
                return mapped
            return super().__new__(cls, *args, **kwargs)

        def __truediv__(self, other):
            return redirect(super().__truediv__(other))

    return FixturePath


def run_pytest(subject):
    import pytest
    subject = Path(subject).resolve()
    scratch = Path(tempfile.mkdtemp(prefix="hive-regression-"))
    work, artifacts = scratch / "work", scratch / "fixtures"
    work.mkdir()
    artifacts.mkdir()
    # Relative reads of production files resolve to the immutable snapshot. New
    # lesson/state files are ordinary scratch data, never evaluator definitions.
    for path in subject.iterdir():
        (work / path.name).symlink_to(path)
    os.chdir(work)
    fixture_path = fixture_path_class(subject, artifacts)

    class Compatibility:
        def pytest_collection_modifyitems(self, items):
            for module in {item.module for item in items}:
                if module.__dict__.get("Path") is Path:
                    module.Path = fixture_path
            # These frozen legacy benchmark helpers also create _tmp_reliability
            # fixtures. Only their Path alias changes; assertions and algorithms do not.
            for name in ("benchmark_harness", "hive_lesson_reuse_patch.benchmark_harness"):
                module = sys.modules.get(name)
                if module is not None and module.__dict__.get("Path") is Path:
                    module.Path = fixture_path

    return pytest.main(["-q", "-p", "no:cacheprovider", str(subject)], plugins=[Compatibility()])

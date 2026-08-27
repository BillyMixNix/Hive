from repo_map import RepoMap


def test_repo_map_build_contains_main():
    rm = RepoMap(root='.')
    data = rm.build()
    assert isinstance(data, dict)
    assert 'known_files' in data
    # repository should include main.py
    assert 'main.py' in data['known_files']


def test_repo_map_excludes_generated_test_sandboxes(tmp_path):
    canonical = tmp_path / "worker.py"
    canonical.write_text(
        "def target():\n"
        "    return 'canonical'\n",
        encoding="utf-8",
    )
    sandbox = tmp_path / "tests" / "_tmp_reliability_active" / "worker.py"
    sandbox.parent.mkdir(parents=True)
    sandbox.write_text(
        "\n\n\n"
        "def target():\n"
        "    return 'sandbox'\n",
        encoding="utf-8",
    )

    data = RepoMap(root=tmp_path).build()

    span = data["symbol_to_span"]["target"]
    assert span["lineno"] == 1
    assert span["end_lineno"] == 2

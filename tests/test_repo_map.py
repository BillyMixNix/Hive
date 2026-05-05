from repo_map import RepoMap


def test_repo_map_build_contains_main():
    rm = RepoMap(root='.')
    data = rm.build()
    assert isinstance(data, dict)
    assert 'known_files' in data
    # repository should include main.py
    assert 'main.py' in data['known_files']

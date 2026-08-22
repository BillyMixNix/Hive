from kingdom.construction import ConstructionGraph


def _graph_with_two_children(mode):
    graph = ConstructionGraph()
    root = graph.add("resolve parent", kind="capability", status="blocked")
    left = graph.add("left prerequisite", kind="experiment", parent_id=root.target_id, status="open")
    right = graph.add("right prerequisite", kind="experiment", parent_id=root.target_id, status="open")
    graph.set_resolution_mode(root.target_id, mode)
    return graph, root, left, right


def test_all_dependencies_require_every_child():
    graph, root, left, right = _graph_with_two_children("all")

    graph.set_status(left.target_id, "verified")
    graph.resolve_dependencies()
    assert graph.targets[root.target_id].status == "blocked"

    graph.set_status(right.target_id, "verified")
    graph.resolve_dependencies()
    assert graph.targets[root.target_id].status == "verified"


def test_any_dependency_accepts_one_verified_alternative():
    graph, root, left, _right = _graph_with_two_children("any")

    graph.set_status(left.target_id, "verified")
    graph.resolve_dependencies()

    assert graph.targets[root.target_id].status == "verified"


def test_all_dependency_rejects_parent_when_required_child_rejected():
    graph, root, left, _right = _graph_with_two_children("all")

    graph.set_status(left.target_id, "rejected")
    graph.resolve_dependencies()

    assert graph.targets[root.target_id].status == "rejected"


def test_any_dependency_rejects_only_when_all_alternatives_rejected():
    graph, root, left, right = _graph_with_two_children("any")

    graph.set_status(left.target_id, "rejected")
    graph.resolve_dependencies()
    assert graph.targets[root.target_id].status == "blocked"

    graph.set_status(right.target_id, "rejected")
    graph.resolve_dependencies()
    assert graph.targets[root.target_id].status == "rejected"
